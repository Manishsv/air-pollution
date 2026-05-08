"""H3 Expert Agent — analyses a single H3 cell across all domains.

Provider-agnostic: works with Ollama (local), Groq, Together, OpenRouter,
OpenAI, LM Studio, or any OpenAI-compatible endpoint.  No provider SDK is
imported here — all LLM calls go through urban_platform.agents.llm_client.

Usage
-----
    from urban_platform.agents.h3_expert import H3ExpertAgent
    agent = H3ExpertAgent(h3_id="8a1b00000007fff", city_id="bangalore")
    insight = agent.run()
    print(insight["finding"])

CLI
---
    python -m urban_platform.agents.h3_expert --city bangalore --top-risk 5
    python -m urban_platform.agents.h3_expert --city bangalore --h3 8a1b00000007fff
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

from urban_platform.agents.llm_client import (
    LLMClient,
    ToolCall,
    assistant_msg,
    tool_result_msg,
    user_msg,
    make_tool,
    make_parameters,
)
from urban_platform.agents.llm_config import LLMConfig, load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions — OpenAI function-calling format
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    make_tool(
        name="get_signal_history",
        description=(
            "Retrieve the time-series of a specific signal for this H3 cell over the past N days. "
            "Use this to check trends, detect recent spikes, or compare current vs baseline. "
            "Example: domain='air', signal='AQI', lookback_days=14 → two weeks of air quality."
        ),
        parameters=make_parameters(
            properties={
                "domain":        {"type": "string", "description": "Domain: air, water, noise, fire, heat, flood, construction, green, waste"},
                "signal":        {"type": "string", "description": "Signal name e.g. AQI, WQI, NRI, CRI, GCCI, LST, FRP"},
                "lookback_days": {"type": "integer", "description": "Days to look back (default 30)", "default": 30},
            },
            required=["domain", "signal"],
        ),
    ),
    make_tool(
        name="get_neighbor_context",
        description=(
            "Fetch the latest domain assessments for all H3 cells within k rings of this cell. "
            "Use this to understand if a risk is localised or part of a broader cluster, "
            "and to detect spatial spillover (e.g. fire smoke drifting from neighbouring cells)."
        ),
        parameters=make_parameters(
            properties={
                "ring": {"type": "integer", "description": "k-ring radius (1=immediate neighbours, 2=wider area)", "default": 1},
            },
        ),
    ),
    make_tool(
        name="get_city_summary",
        description=(
            "Fetch city-wide risk distribution and top insights from the past N hours. "
            "Use this to contextualise whether this cell's risk is an isolated anomaly "
            "or part of a city-wide pattern."
        ),
        parameters=make_parameters(
            properties={
                "lookback_hours": {"type": "integer", "description": "Hours to look back (default 24)", "default": 24},
            },
        ),
    ),
    make_tool(
        name="get_packets_for_domain",
        description=(
            "Retrieve recent decision packets for a specific domain in this cell, "
            "including their outcome status (verified / false_positive / pending). "
            "Use this to check whether prior alerts were real — helps calibrate confidence."
        ),
        parameters=make_parameters(
            properties={
                "domain": {"type": "string", "description": "Domain name"},
                "limit":  {"type": "integer", "description": "Max packets to return (default 5)", "default": 5},
            },
            required=["domain"],
        ),
    ),
    make_tool(
        name="submit_insight",
        description=(
            "Submit your final cross-domain insight. Call this ONCE when analysis is complete. "
            "This is the structured output written to the knowledge store and surfaced in the dashboard."
        ),
        parameters=make_parameters(
            properties={
                "finding": {
                    "type": "string",
                    "description": "Single clear headline sentence describing the cross-domain pattern or risk (≤200 chars)",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence 0.0–1.0. Be honest — lower if data is sparse or proxy-derived.",
                },
                "domains_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which domains are part of this finding e.g. ['air', 'construction', 'noise']",
                },
                "causal_chain": {
                    "type": "array",
                    "description": "Ordered reasoning steps from evidence to conclusion",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step":      {"type": "integer"},
                            "evidence":  {"type": "string"},
                            "inference": {"type": "string"},
                        },
                    },
                },
                "recommended_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific, actionable recommendations for city officers",
                },
                "uncertainty_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What you are unsure about; what data would increase confidence",
                },
            },
            required=["finding", "confidence", "domains_involved", "causal_chain"],
        ),
    ),
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an H3 Expert Agent embedded in the AirOS urban intelligence platform.
You have been assigned cell {h3_id} in {city_id}. Your sole responsibility is to
become the expert on this specific geographic cell — its terrain, environmental
signals across all domains, its history, and how it relates to neighbouring cells.

Your analysis role
------------------
Domain-specific rule pipelines already flag individual risks (high AQI, flooding, etc.).
Your job is to go BEYOND single-domain rules and find:

1. COMPOUND RISKS — when two or more domains interact to make each other worse.
   Example: active construction (high CRI + BSI) + low wind + high AQI
   → dust is re-suspended rather than dispersed, amplifying PM2.5 beyond what
   either domain would flag alone.

2. CAUSAL CHAINS — the actual mechanism linking signals across domains.
   Example: upstream deforestation (GCCI loss) → reduced soil retention → elevated
   flood risk even on moderate rainfall days.

3. PERSISTENT vs TRANSIENT risks — is this a spike or a structural problem?
   Check signal history to distinguish.

4. SPATIAL CONTEXT — is this cell an isolated hotspot or part of a cluster?
   Check neighbours before concluding a risk is localised.

5. EXPECTED vs ANOMALOUS signals — a high NRI near an airport is expected;
   flag only if it is anomalously higher than the baseline for that proximity band.

How to use your tools
---------------------
- Start by reviewing the initial context (signals, assessments, packets).
- Call get_signal_history() if you need trends or to check recent changes.
- Call get_neighbor_context() if you suspect spatial spillover.
- Call get_city_summary() to contextualise against city-wide patterns.
- Call get_packets_for_domain() to check prior alert outcomes.
- End ALWAYS with submit_insight() — one call, one structured finding.

Output quality bar
------------------
- Be specific: name signals, their values, and the date range.
- Calibrate confidence honestly: 0.9+ only with multiple corroborating signals.
- Recommended actions must be concrete: "Dispatch field inspector to verify dust
  source at construction site north of cell centroid" not "investigate further".
- If nothing notable: say so clearly with confidence > 0.8 and a finding like
  "No cross-domain compound risk detected in this cell over the analysis window."
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class H3ExpertAgent:
    """LLM-powered agent that analyses a single H3 cell across all domains.

    The agent is provider-agnostic — configure the LLM via env vars or by
    passing an LLMConfig / dict of overrides.

    Parameters
    ----------
    h3_id, city_id : str
        The cell to analyse.
    config : LLMConfig | dict | None
        LLM configuration.  If None, loads from env vars (LLM_PROVIDER etc.).
        Pass a dict of overrides to selectively change provider/model/etc.
    signals_lookback_days : int
        How many days of signal history to include in the initial context.
    """

    MAX_TOOL_CALLS = 8

    def __init__(
        self,
        h3_id: str,
        city_id: str,
        *,
        config: LLMConfig | dict | None = None,
        signals_lookback_days: int = 7,
    ) -> None:
        self.h3_id   = h3_id
        self.city_id = city_id
        self.signals_lookback_days = signals_lookback_days

        if isinstance(config, dict):
            cfg = load_config(overrides=config)
        elif config is None:
            cfg = load_config()
        else:
            cfg = config

        self._client = LLMClient(cfg)
        logger.info(
            "H3ExpertAgent init: %s/%s via %s (%s)",
            h3_id, city_id, cfg.provider, cfg.model,
        )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_get_signal_history(self, domain: str, signal: str, lookback_days: int = 30) -> dict:
        from urban_platform.h3_knowledge.reader import get_signals_history
        df = get_signals_history(
            self.h3_id, self.city_id,
            domain=domain, signal=signal,
            lookback_days=lookback_days,
        )
        if df.empty:
            return {"rows": [], "message": f"No {signal} history for domain={domain}"}
        return {
            "signal": signal, "domain": domain,
            "row_count": len(df),
            "min":    float(df["value"].min()),
            "max":    float(df["value"].max()),
            "mean":   round(float(df["value"].mean()), 3),
            "latest": float(df["value"].iloc[-1]),
            "rows":   df[["hour_bucket", "value", "source"]].tail(20).to_dict(orient="records"),
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
            try:
                r["packet"] = json.loads(r.pop("packet_json") or "{}")
            except Exception:
                r.pop("packet_json", None)
            rows.append(r)
        return {"domain": domain, "packets": rows}

    def _dispatch_tool(self, tool_call: ToolCall) -> Any:
        name  = tool_call.name
        args  = tool_call.arguments
        if name == "get_signal_history":
            return self._tool_get_signal_history(**args)
        if name == "get_neighbor_context":
            return self._tool_get_neighbor_context(**args)
        if name == "get_city_summary":
            return self._tool_get_city_summary(**args)
        if name == "get_packets_for_domain":
            return self._tool_get_packets_for_domain(**args)
        if name == "submit_insight":
            return {"status": "received"}
        return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the agent and return the structured insight dict."""
        from urban_platform.h3_knowledge.reader import get_h3_context
        from urban_platform.h3_knowledge.writer import write_insight

        ctx      = get_h3_context(
            self.h3_id, self.city_id,
            signals_lookback_days=self.signals_lookback_days,
            include_neighbors=False,
        )
        system   = _SYSTEM_PROMPT.format(h3_id=self.h3_id, city_id=self.city_id)
        messages = [user_msg(self._build_context_message(ctx))]

        insight_payload: dict | None = None
        tool_call_count = 0

        while tool_call_count < self.MAX_TOOL_CALLS:
            response = self._client.chat_with_tools(
                messages,
                AGENT_TOOLS,
                system=system,
            )

            logger.debug("Response: %s", response)

            # Capture any text content
            if response.content:
                messages.append(assistant_msg(content=response.content))

            # No tool calls — agent is done
            if not response.has_tool_calls:
                break

            # Append assistant message with tool calls
            messages.append(assistant_msg(tool_calls=response.tool_calls))

            # Dispatch each tool and collect results
            result_msgs = []
            for tc in response.tool_calls:
                tool_call_count += 1
                logger.info(
                    "Tool [%d/%d]: %s(%s)",
                    tool_call_count, self.MAX_TOOL_CALLS,
                    tc.name, list(tc.arguments.keys()),
                )

                if tc.name == "submit_insight":
                    insight_payload = tc.arguments
                    result_msgs.append(
                        tool_result_msg(tc.id, {"status": "insight_received"})
                    )
                    break   # done
                else:
                    result = self._dispatch_tool(tc)
                    result_msgs.append(tool_result_msg(tc.id, result))

            messages.extend(result_msgs)

            if insight_payload is not None:
                break

        # Fallback if agent never called submit_insight
        if insight_payload is None:
            insight_payload = self._extract_text_insight(messages)

        # Persist
        insight_id = write_insight(
            h3_id=self.h3_id,
            city_id=self.city_id,
            agent_type="h3_expert",
            domains_involved=insight_payload.get("domains_involved", []),
            finding=insight_payload.get("finding", "Agent completed without structured finding."),
            confidence=float(insight_payload.get("confidence", 0.3)),
            causal_chain=insight_payload.get("causal_chain", []),
        )

        return {
            "insight_id":    insight_id,
            "h3_id":         self.h3_id,
            "city_id":       self.city_id,
            "provider":      self._client.config.provider,
            "model":         self._client.config.model,
            "tool_calls":    tool_call_count,
            "created_at":    datetime.now(timezone.utc).isoformat(),
            **insight_payload,
        }

    # ------------------------------------------------------------------
    # Context message builder
    # ------------------------------------------------------------------

    def _build_context_message(self, ctx: dict) -> str:
        parts = [f"## H3 Cell Context: `{self.h3_id}` ({self.city_id})\n"]

        meta = ctx.get("metadata", {})
        if meta:
            parts.append("### Cell identity")
            if meta.get("centroid_lat"):
                parts.append(f"- Centroid: {meta['centroid_lat']:.4f}°N, {meta['centroid_lon']:.4f}°E")
            if meta.get("land_use_class"):
                parts.append(f"- Land use: {meta['land_use_class']}")
            if meta.get("known_features"):
                parts.append(f"- Known features: {', '.join(meta['known_features'])}")
            parts.append("")

        signals = ctx.get("signals", [])
        if signals:
            by_domain: dict[str, list] = {}
            for s in signals:
                by_domain.setdefault(s.get("domain", "?"), []).append(s)
            parts.append(f"### Recent signals ({len(signals)} readings, last {self.signals_lookback_days}d)")
            for domain, rows in sorted(by_domain.items()):
                latest = rows[0]
                parts.append(
                    f"**{domain}**: {latest['signal']}={latest['value']:.3g}"
                    f" {latest.get('unit','') or ''}"
                    f" (source={latest.get('source','?')}, {len(rows)} readings)"
                )
            parts.append("")

        assessments = ctx.get("assessments", [])
        if assessments:
            parts.append("### Current domain assessments")
            for a in assessments:
                issue = f" — {a['dominant_issue']}" if a.get("dominant_issue") else ""
                val   = f" ({a['primary_index']}={a['primary_value']:.3g})" if a.get("primary_value") else ""
                parts.append(f"- **{a['domain']}**: {a['risk_level'].upper()}{val}{issue}")
            parts.append("")
        else:
            parts.append("### Current domain assessments\n_No assessments in store for this cell._\n")

        packets = ctx.get("packets", [])
        if packets:
            parts.append("### Recent decision packets")
            for p in packets[:5]:
                parts.append(
                    f"- [{p['domain']}] {p['risk_level']} — outcome: **{p.get('outcome_status','pending')}**"
                    f" (conf={p.get('confidence_score') or '?'})"
                )
            parts.append("")

        insights = ctx.get("insights", [])
        if insights:
            parts.append("### Prior agent insights (context only — do not repeat)")
            for i in insights[:3]:
                parts.append(
                    f"- [{str(i.get('created_at','?'))[:10]}] {i['finding'][:120]}"
                    f" (conf={i.get('confidence','?')})"
                )
            parts.append("")

        parts.append(
            "---\n"
            "Analyse this cell. Use tools if you need more data, "
            "then call `submit_insight` with your final cross-domain finding."
        )
        return "\n".join(parts)

    def _extract_text_insight(self, messages: list[dict]) -> dict:
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return {
                    "finding": str(msg["content"])[:200],
                    "confidence": 0.2,
                    "domains_involved": [],
                    "causal_chain": [],
                    "uncertainty_notes": ["Agent did not call submit_insight."],
                }
        return {
            "finding": "Agent completed without producing a finding.",
            "confidence": 0.0,
            "domains_involved": [],
            "causal_chain": [],
        }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_top_risk_cells(
    city_id: str,
    *,
    top_n: int = 5,
    domains: list[str] | None = None,
    config: LLMConfig | dict | None = None,
) -> list[dict]:
    """Run H3ExpertAgent on the top-N highest-risk cells missing a recent insight."""
    from urban_platform.h3_knowledge.store import H3KnowledgeStore

    domain_filter = ""
    params: list = [city_id]
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
        logger.info("No eligible cells for city=%s", city_id)
        return []

    results = []
    for h3_id in df["h3_id"].tolist():
        try:
            agent = H3ExpertAgent(h3_id=h3_id, city_id=city_id, config=config)
            results.append(agent.run())
        except Exception as exc:
            logger.error("H3ExpertAgent failed [%s/%s]: %s", h3_id, city_id, exc)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="H3 Expert Agent")
    ap.add_argument("--h3",       help="Specific H3 cell ID")
    ap.add_argument("--city",     required=True, help="City ID e.g. bangalore")
    ap.add_argument("--top-risk", type=int, default=0, help="Run on top-N highest-risk cells")
    ap.add_argument("--provider", help="LLM provider (overrides LLM_PROVIDER env var)")
    ap.add_argument("--model",    help="Model name (overrides LLM_MODEL env var)")
    ap.add_argument("--base-url", help="Base URL (overrides LLM_BASE_URL env var)")
    ap.add_argument("--lookback", type=int, default=7, help="Signal lookback days")
    args = ap.parse_args()

    overrides: dict = {}
    if args.provider: overrides["provider"] = args.provider
    if args.model:    overrides["model"]    = args.model
    if args.base_url: overrides["base_url"] = args.base_url

    cfg = load_config(overrides or None)
    print(f"\nUsing: provider={cfg.provider} model={cfg.model} base_url={cfg.base_url}\n")

    if args.h3:
        agent = H3ExpertAgent(h3_id=args.h3, city_id=args.city,
                              config=cfg, signals_lookback_days=args.lookback)
        result = agent.run()
        print(json.dumps(result, indent=2, default=str))

    elif args.top_risk > 0:
        results = run_top_risk_cells(args.city, top_n=args.top_risk, config=cfg)
        for r in results:
            print(f"\n[{r['h3_id']}] {r['finding']}")
            print(f"  confidence={r['confidence']:.2f} | domains={r.get('domains_involved')}")
            print(f"  provider={r.get('provider')} model={r.get('model')}")
    else:
        ap.print_help()


if __name__ == "__main__":
    _cli()
