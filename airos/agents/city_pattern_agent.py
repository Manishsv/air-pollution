"""City Pattern Agent — second-pass sweep synthesiser.

After the H3 Expert Agent has analysed a batch of individual cells, this agent
reads all insights generated in the last N hours, identifies city-wide themes
(e.g. "heat + air co-elevation across 12 cells in the northeast quadrant"),
and writes a city-level summary back to the knowledge store.

Usage
-----
    from airos.agents.city_pattern_agent import CityPatternAgent
    agent = CityPatternAgent(city_id="bangalore")
    summary = agent.run()

CLI
---
    python -m airos.agents.city_pattern_agent --city bangalore
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from airos.agents.llm_client import (
    LLMClient,
    assistant_msg,
    user_msg,
)
from airos.agents.llm_config import LLMConfig, load_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB schema for city-level pattern summaries
# ---------------------------------------------------------------------------

DDL_CITY_PATTERNS = """
CREATE TABLE IF NOT EXISTS city_patterns (
    pattern_id    TEXT PRIMARY KEY,
    city_id       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    lookback_hours INTEGER NOT NULL,
    n_insights    INTEGER NOT NULL,
    theme_count   INTEGER NOT NULL,
    summary_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_city_patterns_city_created
    ON city_patterns (city_id, created_at DESC);
"""


def _ensure_table() -> None:
    from airos.drivers.store.store import H3KnowledgeStore
    store = H3KnowledgeStore.get()
    for stmt in DDL_CITY_PATTERNS.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            store.execute(stmt)


# ---------------------------------------------------------------------------
# Context builder — reads recent cell insights
# ---------------------------------------------------------------------------

def _build_sweep_context(city_id: str, lookback_hours: int = 6) -> dict:
    """Pull recent cell-level insights and cross-correlation stats for the LLM."""
    from airos.drivers.store.store import H3KnowledgeStore
    from airos.drivers.store.reader import get_domain_cross_correlation

    store = H3KnowledgeStore.get()

    # All cell insights from the sweep window
    insights_df = store.fetchdf(
        f"""
        SELECT insight_id, h3_id, agent_type, created_at,
               domains_involved, finding, confidence, priority_tier,
               hypothesis_chain_json, recommended_actions_json
        FROM h3_insights
        WHERE city_id = ?
          AND created_at >= datetime('now', '-{lookback_hours} hours')
          AND agent_type = 'h3_expert'
        ORDER BY confidence DESC, created_at DESC
        LIMIT 200
        """,
        [city_id],
    )

    if insights_df.empty:
        return {"city_id": city_id, "insights": [], "n_insights": 0}

    insights = []
    for row in insights_df.to_dict(orient="records"):
        row.pop("hypothesis_chain_json", None)
        row.pop("recommended_actions_json", None)
        if row.get("domains_involved"):
            row["domains"] = row.pop("domains_involved").split(",")
        insights.append(row)

    # Domain frequency — which domains appear most in findings
    all_domains: list[str] = []
    for ins in insights:
        all_domains.extend(ins.get("domains", []))
    from collections import Counter
    domain_freq = dict(Counter(all_domains).most_common(10))

    # Top domain pairs (by frequency of co-appearance in same insight)
    pair_counter: Counter = Counter()
    for ins in insights:
        doms = sorted(set(ins.get("domains", [])))
        for i, da in enumerate(doms):
            for db in doms[i + 1:]:
                pair_counter[(da, db)] += 1
    top_pairs = [(list(k), v) for k, v in pair_counter.most_common(5)]

    # Spatial cluster — which cells appear in multiple insights
    cell_freq = Counter(ins["h3_id"] for ins in insights)
    hotspot_cells = [cell for cell, cnt in cell_freq.most_common(10) if cnt >= 2]

    # Cross-correlation for the top domain pair (if any)
    corr_data: list[dict] = []
    for pair, count in pair_counter.most_common(3):
        da, db = pair
        try:
            corr = get_domain_cross_correlation(
                city_id, da, db,
                risk_threshold="moderate",
                lookback_days=7,
            )
            corr_data.append(corr)
        except Exception as exc:
            logger.debug("Cross-corr %s/%s failed: %s", da, db, exc)

    # Assessment counts — how many cells at each risk level city-wide
    risk_df = store.fetchdf(
        """
        SELECT risk_level, COUNT(DISTINCT h3_id) AS n_cells
        FROM (
            SELECT h3_id, domain, risk_level,
                   ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE city_id = ?
              AND assessed_at >= datetime('now', '-24 hours')
        ) WHERE rn = 1
        GROUP BY risk_level
        """,
        [city_id],
    )
    city_risk_dist = risk_df.to_dict(orient="records") if not risk_df.empty else []

    # Domain-level assessment summary — worst risk per domain + top issue
    # This gives the pattern agent visibility into ALL domains, even those
    # without H3 expert insights (e.g. green, water, construction).
    domain_summary_df = store.fetchdf(
        """
        SELECT domain,
               MAX(CASE risk_level WHEN 'severe' THEN 4 WHEN 'high' THEN 3
                   WHEN 'moderate' THEN 2 WHEN 'low' THEN 1 ELSE 0 END) AS risk_score,
               COUNT(*) AS n_cells,
               SUM(CASE WHEN risk_level = 'severe' THEN 1 ELSE 0 END) AS n_severe,
               SUM(CASE WHEN risk_level = 'high'   THEN 1 ELSE 0 END) AS n_high,
               AVG(primary_value) AS avg_value,
               MAX(primary_value) AS max_value,
               primary_index
        FROM (
            SELECT domain, risk_level, primary_value, primary_index,
                   ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE city_id = ?
              AND assessed_at >= datetime('now', '-24 hours')
        ) WHERE rn = 1
        GROUP BY domain, primary_index
        ORDER BY risk_score DESC
        """,
        [city_id],
    )
    # Also get top dominant_issue per domain
    issue_df = store.fetchdf(
        """
        SELECT domain, dominant_issue, COUNT(*) AS n
        FROM (
            SELECT domain, dominant_issue,
                   ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE city_id = ?
              AND assessed_at >= datetime('now', '-24 hours')
              AND dominant_issue IS NOT NULL
        ) WHERE rn = 1
        GROUP BY domain, dominant_issue
        ORDER BY domain, n DESC
        """,
        [city_id],
    )
    top_issues: dict[str, str] = {}
    for row in issue_df.to_dict(orient="records"):
        dom = row["domain"]
        if dom not in top_issues:
            top_issues[dom] = str(row["dominant_issue"])

    domain_assessment_summary = []
    _score_to_risk = {4: "severe", 3: "high", 2: "moderate", 1: "low", 0: "unknown"}
    for row in domain_summary_df.to_dict(orient="records"):
        dom = row["domain"]
        score = int(row.get("risk_score") or 0)
        domain_assessment_summary.append({
            "domain":       dom,
            "worst_risk":   _score_to_risk.get(score, "unknown"),
            "n_cells":      int(row.get("n_cells") or 0),
            "n_severe":     int(row.get("n_severe") or 0),
            "n_high":       int(row.get("n_high") or 0),
            "avg_value":    round(float(row["avg_value"]), 3) if row.get("avg_value") else None,
            "max_value":    round(float(row["max_value"]), 3) if row.get("max_value") else None,
            "primary_index": row.get("primary_index"),
            "top_issue":    top_issues.get(dom),
        })

    return {
        "city_id": city_id,
        "lookback_hours": lookback_hours,
        "n_insights": len(insights),
        "domain_frequency": domain_freq,
        "top_domain_pairs": top_pairs,
        "hotspot_cells": hotspot_cells,
        "cross_correlations": corr_data,
        "city_risk_distribution": city_risk_dist,
        "domain_assessment_summary": domain_assessment_summary,
        "insights": insights,
    }


def _build_prompt(ctx: dict) -> str:
    """Format the sweep context into an LLM prompt."""
    parts = [
        f"# City Pattern Analysis — {ctx['city_id']}",
        f"Sweep window: last {ctx['lookback_hours']}h | Insights analysed: {ctx['n_insights']}",
        "",
    ]

    if not ctx["insights"]:
        parts.append("No cell insights found in the sweep window.")
        return "\n".join(parts)

    # Domain frequency
    parts.append("## Domain frequency in insights")
    for dom, cnt in ctx["domain_frequency"].items():
        parts.append(f"- {dom}: {cnt} insights")
    parts.append("")

    # Top co-appearing domain pairs
    if ctx["top_domain_pairs"]:
        parts.append("## Most common domain combinations in single insights")
        for pair, cnt in ctx["top_domain_pairs"]:
            parts.append(f"- {' + '.join(pair)}: {cnt} insights")
        parts.append("")

    # Cross-correlations
    if ctx["cross_correlations"]:
        parts.append("## City-wide cross-domain co-elevation stats (past 7 days)")
        for corr in ctx["cross_correlations"]:
            lift = corr.get("lift")
            n_both = corr.get("n_co_elevated", 0)
            n_total = corr.get("n_total_cells", "?")
            interp = corr.get("interpretation", "")
            parts.append(
                f"- **{corr['domain_a']} ↔ {corr['domain_b']}**: "
                f"lift={lift}, co-elevated cells={n_both}/{n_total} — {interp}"
            )
        parts.append("")

    # City risk distribution
    if ctx["city_risk_distribution"]:
        parts.append("## City-wide risk distribution (last 24h, all domains)")
        for row in ctx["city_risk_distribution"]:
            parts.append(f"- {row['risk_level']}: {row['n_cells']} cells")
        parts.append("")

    # Domain assessment summary — includes domains without H3 expert insights
    # (e.g. green, water, construction) so the pattern covers ALL risk domains.
    domain_summary = ctx.get("domain_assessment_summary", [])
    if domain_summary:
        parts.append("## Domain risk summary (rule-based assessments, ALL domains)")
        parts.append(
            "NOTE: Some domains below have satellite/sensor data but no LLM insights yet. "
            "Your pattern MUST address ALL domains showing high or severe risk, "
            "even if the evidence comes only from the assessment summary below."
        )
        for d in domain_summary:
            risk  = d.get("worst_risk", "unknown")
            dom   = d.get("domain", "?")
            n     = d.get("n_cells", 0)
            nsev  = d.get("n_severe", 0)
            nhigh = d.get("n_high", 0)
            issue = d.get("top_issue") or "—"
            pidx  = d.get("primary_index") or ""
            avg_v = d.get("avg_value")
            val_str = f", {pidx} avg={avg_v:.3f}" if (avg_v is not None and pidx) else ""
            sev_str = f"({nsev} severe, {nhigh} high)" if nsev + nhigh > 0 else ""
            parts.append(
                f"- **{dom}**: worst_risk={risk}, {n} cells {sev_str}"
                f", top_issue={issue}{val_str}"
            )
        parts.append("")

    # Hotspot cells (appearing in multiple insights)
    if ctx["hotspot_cells"]:
        parts.append(f"## Multi-insight hotspot cells ({len(ctx['hotspot_cells'])} cells appear in ≥2 insights)")
        parts.append(", ".join(ctx["hotspot_cells"][:10]))
        parts.append("")

    # Individual insights (truncated — top 30 by confidence to keep prompt compact)
    parts.append("## Cell-level insights from this sweep (highest confidence first, max 30)")
    for ins in ctx["insights"][:30]:
        domains = ", ".join(ins.get("domains", []))
        tier = ins.get("priority_tier", "?")
        conf = ins.get("confidence", "?")
        finding = (ins.get("finding") or "")[:160]  # truncate long findings
        parts.append(
            f"- [{ins['h3_id']}][{tier}] conf={conf} | {domains} | {finding}"
        )

    return "\n".join(parts)


SYSTEM_PROMPT = """\
You are a city-level urban intelligence analyst. You have been given a batch of \
H3-cell-level insights from a sweep of a city. Your task is to identify \
city-wide patterns, themes, and emerging risks that are NOT visible at the \
individual cell level.

You must produce a structured JSON response with EXACTLY this schema:
{
  "executive_summary": "<2-3 sentences: the most important city-wide finding>",
  "themes": [
    {
      "title": "<short theme name>",
      "description": "<2-4 sentences: what pattern you see and why it matters>",
      "domains": ["domain1", "domain2"],
      "n_cells_affected": <integer>,
      "confidence": <float 0.0-1.0>,
      "evidence": "<what data supports this — be specific about lift scores, cell counts, signal levels>",
      "recommended_city_action": "<one specific city-level intervention, not just 'monitor'>",
      "priority": "high" | "medium" | "low"
    }
  ],
  "emerging_risks": ["<risk description>", ...],
  "data_quality_note": "<honest note about data limitations affecting this synthesis>"
}

Rules:
- Identify 2-5 themes. Do not pad with weak observations.
- A theme must span ≥3 cells OR appear in ≥2 independent insights to be valid.
- Cite specific evidence (lift scores, cell counts, domain frequencies).
- Do NOT invent patterns not supported by the data.
- Data quality note must be specific — if n_insights < 10, say so and lower confidence.
- Output ONLY valid JSON. No markdown fences, no preamble.
"""


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class CityPatternAgent:
    """Synthesises cell-level H3 insights into city-wide pattern summaries."""

    def __init__(
        self,
        city_id: str,
        *,
        lookback_hours: int = 6,
        config: LLMConfig | dict | None = None,
    ) -> None:
        self.city_id       = city_id
        self.lookback_hours = lookback_hours
        self._cfg = (
            config if isinstance(config, LLMConfig)
            else LLMConfig(**(config or {})) if isinstance(config, dict)
            else load_config()
        )
        self._llm = LLMClient(self._cfg)
        _ensure_table()

    def run(self) -> dict[str, Any]:
        """Run city pattern analysis and persist to DB. Returns the summary dict."""
        ctx = _build_sweep_context(self.city_id, lookback_hours=self.lookback_hours)

        if ctx["n_insights"] == 0:
            logger.info("CityPatternAgent: no insights for %s in last %dh", self.city_id, self.lookback_hours)
            return {"city_id": self.city_id, "n_insights": 0, "themes": [], "skipped": True}

        logger.info(
            "CityPatternAgent: synthesising %d insights for %s",
            ctx["n_insights"], self.city_id,
        )

        prompt = _build_prompt(ctx)
        messages = [user_msg(prompt)]

        response = self._llm.chat(
            messages,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
        )

        # Parse JSON response — LLMResponse.content is a plain string
        raw: str = response.content or ""

        summary: dict[str, Any] = {}
        try:
            clean = raw.strip()
            # Strip markdown code fences (```json ... ```)
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1]
                if "```" in clean:
                    clean = clean.rsplit("```", 1)[0]
                clean = clean.strip()
            # Try to find JSON object if surrounded by prose
            if not clean.startswith("{"):
                start = clean.find("{")
                end   = clean.rfind("}")
                if start != -1 and end != -1:
                    clean = clean[start:end + 1]
            summary = json.loads(clean)
        except Exception as exc:
            logger.warning("CityPatternAgent: JSON parse failed (%s) — storing raw response", exc)
            summary = {
                "executive_summary": raw[:500] if raw else "Parse error",
                "themes": [],
                "emerging_risks": [],
                "data_quality_note": "Response was not valid JSON.",
                "parse_error": str(exc),
            }

        # Persist to DB
        self._persist(ctx, summary)
        return summary

    def _persist(self, ctx: dict, summary: dict) -> None:
        """Write the city pattern summary to the DB."""
        import uuid
        from airos.drivers.store.store import H3KnowledgeStore

        store = H3KnowledgeStore.get()
        pattern_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        themes = summary.get("themes", [])

        store.execute(
            """
            INSERT INTO city_patterns
                (pattern_id, city_id, created_at, lookback_hours, n_insights, theme_count, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                pattern_id,
                self.city_id,
                now,
                ctx["lookback_hours"],
                ctx["n_insights"],
                len(themes),
                json.dumps(summary),
            ],
        )
        logger.info(
            "CityPatternAgent: persisted pattern_id=%s (%d themes) for %s",
            pattern_id, len(themes), self.city_id,
        )


# ---------------------------------------------------------------------------
# Reader helper (for dashboard / scheduler)
# ---------------------------------------------------------------------------

def get_latest_city_pattern(city_id: str) -> dict | None:
    """Return the most recent city pattern summary for a city, or None."""
    from airos.drivers.store.store import H3KnowledgeStore
    df = H3KnowledgeStore.get().fetchdf(
        """
        SELECT pattern_id, created_at, lookback_hours, n_insights, theme_count, summary_json
        FROM city_patterns
        WHERE city_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [city_id],
    )
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    try:
        row["summary"] = json.loads(row.pop("summary_json"))
    except Exception:
        pass
    return row


def get_city_pattern_history(city_id: str, limit: int = 10):
    """Return recent city pattern entries as a DataFrame."""
    from airos.drivers.store.store import H3KnowledgeStore
    return H3KnowledgeStore.get().fetchdf(
        f"""
        SELECT pattern_id, created_at, lookback_hours, n_insights, theme_count
        FROM city_patterns
        WHERE city_id = ?
        ORDER BY created_at DESC
        LIMIT {limit}
        """,
        [city_id],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="City Pattern Agent")
    parser.add_argument("--city", required=True, help="City ID")
    parser.add_argument("--lookback", type=int, default=6, help="Hours to look back for insights (default 6)")
    args = parser.parse_args()

    agent = CityPatternAgent(args.city, lookback_hours=args.lookback)
    result = agent.run()

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _main()
