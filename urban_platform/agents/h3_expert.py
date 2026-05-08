"""H3 Expert Agent — a Claude agent that becomes the expert on a single H3 cell.

Each agent instance:
  1. Loads the full multi-level context for its assigned cell from the H3 Knowledge Store
  2. Uses tools to fetch additional context (neighbours, city summary, signal history)
  3. Reasons across all domains holistically — finding patterns a domain-specific
     rule pipeline cannot see
  4. Returns a structured Insight and writes it back to h3_insights

Usage
-----
    from urban_platform.agents.h3_expert import H3ExpertAgent
    agent = H3ExpertAgent(h3_id="8a1b00000007fff", city_id="bangalore")
    insight = agent.run()          # calls Claude, writes insight to store
    print(insight["finding"])

CLI
---
    python -m urban_platform.agents.h3_expert --h3 8a1b00000007fff --city bangalore
    python -m urban_platform.agents.h3_expert --city bangalore --top-risk 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions — what the agent can call during reasoning
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "get_signal_history",
        "description": (
            "Retrieve the time-series of a specific signal for this H3 cell over the past N days. "
            "Use this to check trends, detect recent spikes, or compare current vs baseline. "
            "Example: call with signal='AQI', domain='air', lookback_days=14 to see two weeks of air quality."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain":        {"type": "string", "description": "Domain name e.g. 'air', 'water', 'noise'"},
                "signal":        {"type": "string", "description": "Signal name e.g. 'AQI', 'WQI', 'NRI', 'GCCI'"},
                "lookback_days": {"type": "integer", "description": "How many days back to fetch (default 30)", "default": 30},
            },
            "required": ["domain", "signal"],
        },
    },
    {
        "name": "get_neighbor_context",
        "description": (
            "Fetch the latest domain assessments for all H3 cells within k rings of this cell. "
            "Use this to understand if a risk is localised to this cell or part of a broader cluster, "
            "and to detect spatial spillover (e.g. fire smoke drifting from neighbouring cells)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ring": {"type": "integer", "description": "k-ring radius (1=immediate neighbours, 2=wider area)", "default": 1},
            },
        },
    },
    {
        "name": "get_city_summary",
        "description": (
            "Fetch city-wide risk distribution and top insights from the past 24 hours. "
            "Use this to contextualise whether this cell's risk is an isolated anomaly or part of a city-wide pattern."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lookback_hours": {"type": "integer", "description": "Hours to look back (default 24)", "default": 24},
            },
        },
    },
    {
        "name": "get_packets_for_domain",
        "description": (
            "Retrieve recent decision packets for a specific domain in this cell, including their outcome status. "
            "Use this to check if prior alerts were verified, false positives, or still pending — "
            "this helps calibrate confidence in new findings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain name"},
                "limit":  {"type": "integer", "description": "Max packets to return (default 5)", "default": 5},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "submit_insight",
        "description": (
            "Submit your final cross-domain insight. Call this ONCE when you have completed your analysis. "
            "This is the structured output that will be written to the knowledge store and surfaced in the dashboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "A single clear headline sentence describing the cross-domain pattern or risk (max 200 chars)",
                },
                "confidence": {
                    "type": "number",
                    "description": "Your confidence in this finding, 0.0-1.0. Be honest — lower if data is sparse or proxy-derived.",
                },
                "domains_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which domains are part of this finding e.g. ['air', 'construction', 'noise']",
                },
                "causal_chain": {
                    "type": "array",
                    "description": "Ordered list of reasoning steps from evidence to conclusion",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step":      {"type": "integer"},
                            "evidence":  {"type": "string", "description": "Observation or data point"},
                            "inference": {"type": "string", "description": "What you conclude from this evidence"},
                        },
                    },
                },
                "recommended_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific, actionable recommendations for city officers (be concrete, not generic)",
                },
                "uncertainty_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What you are unsure about; what data would increase confidence",
                },
            },
            "required": ["finding", "confidence", "domains_involved", "causal_chain"],
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an H3 Expert Agent embedded in the AirOS urban intelligence platform.
You have been assigned cell {h3_id} in {city_id}. Your sole responsibility is to
become the expert on this specific geographic cell — its terrain, its environmental
signals across all domains, its history, and how it relates to neighbouring cells.

Your analysis role
------------------
Domain-specific rule pipelines already flag individual risks (high AQI, flooding, etc.).
Your job is to go BEYOND single-domain rules and find:

1. COMPOUND RISKS — when two or more domains interact to make each other worse.
   Example: active construction (high CRI + BSI) + low wind (stagnant air) + high AQI
   → dust is re-suspended rather than dispersed, amplifying PM2.5 far beyond what
   either domain would flag alone.

2. CAUSAL CHAINS — the actual mechanism linking signals across domains.
   Example: upstream deforestation (GCCI loss) → reduced soil retention → elevated
   flood risk score even on moderate rainfall days.

3. PERSISTENT vs TRANSIENT risks — is this a spike or a structural problem?
   Check signal history to distinguish.

4. SPATIAL CONTEXT — is this cell an isolated hotspot or part of a cluster?
   Check neighbours before concluding a risk is localised.

5. FALSE POSITIVE SIGNALS — a high NRI near an airport is expected; flag it only if
   it is anomalously higher than the baseline for that proximity band.

How to use your tools
---------------------
- Start by reviewing the initial context provided (signals, assessments, packets).
- Call get_signal_history() if you need to understand trends or recent changes.
- Call get_neighbor_context() if you suspect spatial spillover.
- Call get_city_summary() if you need to contextualise against city-wide patterns.
- Call get_packets_for_domain() to check prior alert outcomes (verified / false_positive).
- End ALWAYS with submit_insight() — one call, one structured finding.

Output quality bar
------------------
- Be specific: name the signals, their values, and the date range.
- Calibrate confidence honestly: 0.9+ only if you have multiple corroborating signals.
- Recommended actions must be concrete: "Dispatch field inspector to verify dust source
  at construction site north of cell centroid" not "investigate further".
- If there is nothing notable, say so clearly with confidence > 0.8 and a finding
  like "No cross-domain compound risk detected in this cell over the analysis window."
"""


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class H3ExpertAgent:
    """Claude-powered agent that analyses a single H3 cell across all domains."""

    def __init__(
        self,
        h3_id: str,
        city_id: str,
        *,
        model: str = "claude-opus-4-5",
        max_tokens: int = 4096,
        signals_lookback_days: int = 7,
        anthropic_api_key: str | None = None,
    ) -> None:
        self.h3_id   = h3_id
        self.city_id = city_id
        self.model   = model
        self.max_tokens = max_tokens
        self.signals_lookback_days = signals_lookback_days

        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set — cannot run H3 Expert Agent.")
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Tool implementations (called when Claude requests them)
    # ------------------------------------------------------------------

    def _tool_get_signal_history(self, domain: str, signal: str, lookback_days: int = 30) -> dict:
        from urban_platform.h3_knowledge.reader import get_signals_history
        df = get_signals_history(self.h3_id, self.city_id,
                                 domain=domain, signal=signal,
                                 lookback_days=lookback_days)
        if df.empty:
            return {"rows": [], "message": f"No {signal} history found for domain={domain}"}
        rows = df[["hour_bucket", "value", "source"]].tail(100).to_dict(orient="records")
        return {
            "signal": signal,
            "domain": domain,
            "row_count": len(df),
            "min_value": float(df["value"].min()),
            "max_value": float(df["value"].max()),
            "mean_value": float(df["value"].mean()),
            "latest_value": float(df["value"].iloc[-1]),
            "rows": rows[-20:],  # last 20 data points for Claude to inspect
        }

    def _tool_get_neighbor_context(self, ring: int = 1) -> dict:
        from urban_platform.h3_knowledge.reader import get_neighbors_summary
        return get_neighbors_summary(self.h3_id, self.city_id, ring=ring)

    def _tool_get_city_summary(self, lookback_hours: int = 24) -> dict:
        from urban_platform.h3_knowledge.reader import get_city_summary
        return get_city_summary(self.city_id, lookback_hours=lookback_hours)

    def _tool_get_packets_for_domain(self, domain: str, limit: int = 5) -> dict:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        df = H3KnowledgeStore.get().fetchdf(
            f"""
            SELECT packet_id, created_at, risk_level, confidence_score,
                   outcome_status, packet_json
            FROM h3_packets
            WHERE h3_id = ? AND city_id = ? AND domain = ?
            ORDER BY created_at DESC
            LIMIT {limit}
            """,
            [self.h3_id, self.city_id, domain],
        )
        rows = []
        for r in df.to_dict(orient="records"):
            if r.get("packet_json"):
                try:
                    r["packet"] = json.loads(r.pop("packet_json"))
                except Exception:
                    r.pop("packet_json", None)
            rows.append(r)
        return {"domain": domain, "packets": rows}

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> Any:
        if tool_name == "get_signal_history":
            return self._tool_get_signal_history(**tool_input)
        if tool_name == "get_neighbor_context":
            return self._tool_get_neighbor_context(**tool_input)
        if tool_name == "get_city_summary":
            return self._tool_get_city_summary(**tool_input)
        if tool_name == "get_packets_for_domain":
            return self._tool_get_packets_for_domain(**tool_input)
        if tool_name == "submit_insight":
            return tool_input  # captured in run()
        return {"error": f"Unknown tool: {tool_name}"}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the agent, return the structured insight dict."""
        from urban_platform.h3_knowledge.reader import get_h3_context
        from urban_platform.h3_knowledge.writer import write_insight

        # Load initial context
        ctx = get_h3_context(
            self.h3_id, self.city_id,
            signals_lookback_days=self.signals_lookback_days,
            include_neighbors=False,  # agent can call the tool if it wants neighbours
        )

        # Build the initial user message — summary of all data we have
        user_msg = self._build_context_message(ctx)

        messages: list[dict] = [{"role": "user", "content": user_msg}]
        system = _SYSTEM_PROMPT.format(h3_id=self.h3_id, city_id=self.city_id)

        insight_payload: dict | None = None
        tool_call_count = 0
        MAX_TOOL_CALLS = 8  # safety limit

        logger.info("H3ExpertAgent starting: %s / %s", self.h3_id, self.city_id)

        while True:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                tools=_TOOLS,
                messages=messages,
            )

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            # Check stop reason
            if response.stop_reason == "end_turn":
                logger.info("Agent finished without submit_insight — stop_reason=end_turn")
                break

            if response.stop_reason != "tool_use":
                logger.warning("Unexpected stop_reason: %s", response.stop_reason)
                break

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_call_count += 1
                logger.info("Tool call [%d]: %s(%s)", tool_call_count,
                            block.name, list(block.input.keys()))

                if block.name == "submit_insight":
                    insight_payload = block.input
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"status": "insight_received", "finding": block.input.get("finding", "")[:80]}),
                    })
                    break  # no need to process more tools

                result = self._dispatch_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            messages.append({"role": "user", "content": tool_results})

            if insight_payload is not None:
                break

            if tool_call_count >= MAX_TOOL_CALLS:
                logger.warning("Hit MAX_TOOL_CALLS limit (%d) without submit_insight", MAX_TOOL_CALLS)
                break

        # If agent never called submit_insight, extract best-effort from text
        if insight_payload is None:
            insight_payload = self._extract_text_insight(messages)

        # Persist to store
        insight_id = write_insight(
            h3_id=self.h3_id,
            city_id=self.city_id,
            agent_type="h3_expert",
            domains_involved=insight_payload.get("domains_involved", []),
            finding=insight_payload.get("finding", "Agent completed without structured finding."),
            confidence=insight_payload.get("confidence", 0.3),
            causal_chain=insight_payload.get("causal_chain", []),
        )

        result = {
            "insight_id": insight_id,
            "h3_id": self.h3_id,
            "city_id": self.city_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool_calls": tool_call_count,
            **insight_payload,
        }
        logger.info("Insight written: %s | confidence=%.2f | %s",
                    insight_id, insight_payload.get("confidence", 0),
                    insight_payload.get("finding", "")[:80])
        return result

    # ------------------------------------------------------------------
    # Context message builder
    # ------------------------------------------------------------------

    def _build_context_message(self, ctx: dict) -> str:
        parts = [
            f"## H3 Cell Context: `{self.h3_id}` ({self.city_id})\n",
        ]

        # Metadata
        meta = ctx.get("metadata", {})
        if meta:
            parts.append("### Cell identity")
            parts.append(f"- Resolution: {meta.get('resolution', '?')}")
            parts.append(f"- Centroid: {meta.get('centroid_lat', '?'):.4f}°N, {meta.get('centroid_lon', '?'):.4f}°E"
                         if meta.get('centroid_lat') else "- Centroid: unknown")
            if meta.get("land_use_class"):
                parts.append(f"- Land use: {meta['land_use_class']}")
            if meta.get("known_features"):
                parts.append(f"- Known features: {', '.join(meta['known_features'])}")
            parts.append("")

        # Signals summary
        signals = ctx.get("signals", [])
        if signals:
            parts.append(f"### Recent signals ({len(signals)} readings, last {self.signals_lookback_days}d)")
            by_domain: dict[str, list] = {}
            for s in signals:
                by_domain.setdefault(s.get("domain", "?"), []).append(s)
            for domain, rows in sorted(by_domain.items()):
                latest = rows[0]  # already sorted desc
                parts.append(f"**{domain}**: {latest['signal']}={latest['value']:.3g} "
                              f"{latest.get('unit','') or ''} "
                              f"(source={latest.get('source','?')}, "
                              f"{len(rows)} readings in window)")
            parts.append("")

        # Assessments
        assessments = ctx.get("assessments", [])
        if assessments:
            parts.append("### Current domain assessments")
            for a in assessments:
                issue = f" — {a['dominant_issue']}" if a.get("dominant_issue") else ""
                val   = f" ({a['primary_index']}={a['primary_value']:.3g})" if a.get("primary_value") else ""
                parts.append(f"- **{a['domain']}**: {a['risk_level'].upper()}{val}{issue}")
            parts.append("")
        else:
            parts.append("### Current domain assessments\n_No assessments yet in the knowledge store for this cell._\n")

        # Packets
        packets = ctx.get("packets", [])
        if packets:
            parts.append("### Recent decision packets")
            for p in packets[:5]:
                status = p.get("outcome_status", "pending")
                parts.append(f"- [{p['domain']}] {p['risk_level']} risk — outcome: **{status}** "
                              f"(conf={p.get('confidence_score') or '?'})")
            parts.append("")

        # Prior insights
        insights = ctx.get("insights", [])
        if insights:
            parts.append("### Prior agent insights (context only — do not repeat)")
            for i in insights[:3]:
                parts.append(f"- [{i.get('created_at','?')[:10]}] {i['finding'][:120]} "
                              f"(confidence={i.get('confidence','?')})")
            parts.append("")

        parts.append(
            "---\n"
            "Now analyse this cell. Use the tools if you need more data, "
            "then call `submit_insight` with your final cross-domain finding."
        )
        return "\n".join(parts)

    def _extract_text_insight(self, messages: list) -> dict:
        """Fallback: pull the last assistant text block as a plain finding."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text") and block.text:
                            return {
                                "finding": block.text[:200],
                                "confidence": 0.2,
                                "domains_involved": [],
                                "causal_chain": [],
                                "recommended_actions": [],
                                "uncertainty_notes": ["Agent did not call submit_insight — unstructured response."],
                            }
        return {
            "finding": "Agent completed without producing a finding.",
            "confidence": 0.0,
            "domains_involved": [],
            "causal_chain": [],
        }


# ---------------------------------------------------------------------------
# Batch runner — top-N highest-risk cells in a city
# ---------------------------------------------------------------------------

def run_top_risk_cells(
    city_id: str,
    *,
    top_n: int = 5,
    domains: list[str] | None = None,
    model: str = "claude-opus-4-5",
) -> list[dict]:
    """Run H3ExpertAgent on the top-N highest-risk cells in a city.

    Selects cells with the most 'high' or 'severe' domain assessments
    that don't yet have a recent agent insight.
    """
    from urban_platform.h3_knowledge.store import H3KnowledgeStore

    domain_filter = ""
    params = [city_id]
    if domains:
        placeholders = ",".join(["?" for _ in domains])
        domain_filter = f"AND domain IN ({placeholders})"
        params.extend(domains)

    df = H3KnowledgeStore.get().fetchdf(
        f"""
        SELECT h3_id, count(*) AS high_domain_count
        FROM h3_assessments
        WHERE city_id = ?
          AND risk_level IN ('high', 'severe')
          AND day_bucket >= current_date - INTERVAL '3 days'
          {domain_filter}
          AND h3_id NOT IN (
              SELECT h3_id FROM h3_insights
              WHERE city_id = ?
                AND agent_type = 'h3_expert'
                AND created_at >= now() - INTERVAL '6 hours'
          )
        GROUP BY h3_id
        ORDER BY high_domain_count DESC
        LIMIT {top_n}
        """,
        params + [city_id],
    )

    if df.empty:
        logger.info("No eligible cells found for city=%s", city_id)
        return []

    results = []
    for h3_id in df["h3_id"].tolist():
        try:
            agent = H3ExpertAgent(h3_id=h3_id, city_id=city_id, model=model)
            insight = agent.run()
            results.append(insight)
        except Exception as exc:
            logger.error("H3ExpertAgent failed for %s/%s: %s", h3_id, city_id, exc)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="H3 Expert Agent CLI")
    ap.add_argument("--h3",      help="Specific H3 cell ID to analyse")
    ap.add_argument("--city",    required=True, help="City ID e.g. bangalore")
    ap.add_argument("--top-risk", type=int, default=0,
                    help="Run on top-N highest-risk cells (alternative to --h3)")
    ap.add_argument("--model",   default="claude-opus-4-5", help="Claude model to use")
    ap.add_argument("--lookback", type=int, default=7, help="Signal lookback days")
    args = ap.parse_args()

    if args.h3:
        agent = H3ExpertAgent(h3_id=args.h3, city_id=args.city,
                              model=args.model,
                              signals_lookback_days=args.lookback)
        result = agent.run()
        print(json.dumps(result, indent=2, default=str))

    elif args.top_risk > 0:
        results = run_top_risk_cells(args.city, top_n=args.top_risk, model=args.model)
        for r in results:
            print(f"\n[{r['h3_id']}] {r['finding']}")
            print(f"  confidence={r['confidence']:.2f} | domains={r.get('domains_involved')}")
    else:
        ap.print_help()


if __name__ == "__main__":
    _cli()
