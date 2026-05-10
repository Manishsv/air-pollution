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
from urban_platform.agents.web_search import (
    WebSearchConfig,
    load_web_search_config,
    search as web_search,
    format_results_for_llm,
)

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
            "Example: domain='air', signal='AQI', lookback_days=14 → two weeks of air quality. "
            "For weather context use domain='weather' with signals: WIND_SPEED_KMH, WIND_DIR_DEG, "
            "HUMIDITY_PCT, PRESSURE_HPA, TEMPERATURE_C, PRECIP_MM."
        ),
        parameters=make_parameters(
            properties={
                "domain":        {"type": "string", "description": "Domain: air, water, noise, fire, heat, flood, construction, green, waste, weather, buildings, roads, drains, crowd"},
                "signal":        {"type": "string", "description": "Signal name e.g. AQI, WQI, NRI, CRI, GCCI, LST, FRP, WIND_SPEED_KMH, WIND_DIR_DEG, HUMIDITY_PCT, PRESSURE_HPA, BUILDING_DENSITY, ROAD_DENSITY, FLOOD_DRAIN_CAPACITY, CROWD_DENSITY, CROWD_INDEX, GATHERING_ALERT, PEOPLE_COUNT"},
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
        name="search_web",
        description=(
            "Search recent news and web sources to validate or contextualise a hypothesis "
            "about this cell's location. Use ONLY when sensor signals suggest a specific "
            "mechanism and you want to check whether known local events corroborate it. "
            "Good queries: 'illegal waste dumping fire Bahadurgarh Haryana 2026', "
            "'construction project Whitefield Bangalore', 'CAQM air quality alert Delhi NCR'. "
            "Do NOT use for general background research — one targeted query per hypothesis. "
            "Treat results as supporting context, not sensor-level evidence. "
            "Cite the source and date in your causal chain if it affects your confidence."
        ),
        parameters=make_parameters(
            properties={
                "query": {
                    "type":        "string",
                    "description": "Focused search query. Include location, suspected mechanism, and year.",
                },
                "max_results": {
                    "type":        "integer",
                    "description": "Results to return (default 3, max 5)",
                    "default":     3,
                },
            },
            required=["query"],
        ),
    ),
    make_tool(
        name="get_domain_cross_correlation",
        description=(
            "Query how strongly two domains co-occur at elevated risk across the CITY over the "
            "past N days. Returns a lift score: lift > 1.5 means the domains co-elevate more "
            "than chance; lift > 3.0 is very strong. Use this to validate or challenge a "
            "cross-domain hypothesis before submitting. "
            "Example: domain_a='air', domain_b='heat' → 'Do high-air-risk cells also have "
            "high heat risk more than chance?' "
            "IMPORTANT: this is a city-wide signal, not cell-specific — interpret it as prior "
            "probability context, not proof for this cell."
        ),
        parameters=make_parameters(
            properties={
                "domain_a":       {"type": "string", "description": "First domain (e.g. air, heat, flood, noise, waste, water, drains, buildings, roads)"},
                "domain_b":       {"type": "string", "description": "Second domain to correlate against domain_a"},
                "risk_threshold": {"type": "string", "description": "Minimum risk level to count as elevated: 'low', 'moderate', 'high' (default), 'severe'", "default": "high"},
                "lookback_days":  {"type": "integer", "description": "Days of assessment history to include (default 30)", "default": 30},
            },
            required=["domain_a", "domain_b"],
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
                    "description": (
                        "Single clear headline describing the inferred risk condition (≤200 chars). "
                        "Frame as a risk assessment, not an event report. "
                        "Good: 'Elevated waste-fire risk — extreme heat, accumulated garbage, moderate wind.' "
                        "Bad: 'Landfill fire is occurring.' "
                        "The hypothesis_chain is where you explain the mechanism and how to test it."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Confidence 0.0–1.0. Be honest — lower if data is sparse or proxy-derived. "
                        "This drives priority_tier: ≥0.75=high, 0.45–0.74=medium, <0.45=low. "
                        "Do not inflate — this score is calibrated against field outcomes over time."
                    ),
                },
                "domains_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which domains are part of this finding e.g. ['air', 'construction', 'noise']",
                },
                "hypothesis_chain": {
                    "type": "array",
                    "description": (
                        "Ordered reasoning steps from evidence to hypothesis. "
                        "Each item is a HypothesisItem with exactly three fields: "
                        "'proposition' (a falsifiable statement — use 'consistent with', "
                        "'suggests', not 'caused'), "
                        "'testable_by' (how a field officer could verify or refute it), "
                        "'confidence' (float 0.0–1.0 for this specific step). "
                        "MUST NOT be empty."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "proposition": {
                                "type": "string",
                                "description": "Falsifiable statement. No causal language.",
                            },
                            "testable_by": {
                                "type": "string",
                                "description": "How a field officer could verify or refute this",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence in this specific step (0.0–1.0)",
                            },
                        },
                        "required": ["proposition", "testable_by", "confidence"],
                    },
                    "minItems": 1,
                },
                "recommended_actions": {
                    "type": "array",
                    "description": (
                        "Specific, actionable recommendations. Each item is a RecommendedAction: "
                        "'action' (what to do, ≤120 chars), "
                        "'actor' (role: ward_engineer / zonal_officer / department), "
                        "'urgency' (immediate / within_4h / within_24h / this_week / plan), "
                        "'condition' (when this action applies), "
                        "'blocked_if' (optional — circumstance that would prevent this action)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action":     {"type": "string"},
                            "actor":      {"type": "string"},
                            "urgency":    {"type": "string"},
                            "condition":  {"type": "string"},
                            "blocked_if": {"type": "string"},
                        },
                        "required": ["action", "actor", "urgency", "condition"],
                    },
                },
                "uncertainty_notes": {
                    "type": "array",
                    "description": (
                        "What you are unsure about and what data would increase confidence. "
                        "Each item has 'note' (description) and 'impact' (low/medium/high). "
                        "MUST NOT be empty — at least one uncertainty note is always required."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "note":   {"type": "string"},
                            "impact": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "required": ["note", "impact"],
                    },
                    "minItems": 1,
                },
                "priority_tier": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": (
                        "Urgency tier for the Review Dashboard inbox. Set based on RISK SEVERITY, "
                        "not just analytical confidence:\n"
                        "  critical — GATHERING_ALERT=1 + active hazard, OR ≥3 domains at high/severe "
                        "with consistent multi-day trend\n"
                        "  high     — ≥2 domains at high/severe with plausible compound mechanism "
                        "(e.g. heat + waste fire, flood + no drainage, high AQI + low wind + construction)\n"
                        "  medium   — one domain elevated or compound risk possible but uncertain\n"
                        "  low      — no compound risk found, isolated low-severity signal, or "
                        "'No cross-domain compound risk detected' findings\n"
                        "IMPORTANT: 'No compound risk' findings MUST use priority_tier='low'."
                    ),
                },
            },
            required=["finding", "confidence", "domains_involved", "hypothesis_chain", "uncertainty_notes"],
        ),
    ),
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an H3 Expert Agent embedded in the AirOS urban intelligence platform.
You have been assigned cell {h3_id} in the {city_id} data region. Your sole
responsibility is to become the expert on this specific geographic cell — its
terrain, environmental signals across all domains, its history, and how it
relates to neighbouring cells.

Important: `city_id` is a data collection region label, not an administrative
boundary. For example, city_id="delhi" covers the broader NCR region and may
include cells in Haryana (e.g. Bahadurgarh, Gurugram, Faridabad) or Uttar Pradesh
(e.g. Noida, Ghaziabad). Always use the cell's centroid coordinates (lat/lon) to
determine the actual geographic location. When the cell falls outside the named
city's administrative boundary, note this in your analysis — it affects which
government body has jurisdiction over recommended actions.

Your analysis role
------------------
Domain-specific rule pipelines already flag individual risks (high AQI, flooding, etc.).
Your job is to go BEYOND single-domain rules and find:

1. COMPOUND RISKS — when two or more domains interact to make each other worse.
   Example: active construction (high CRI + BSI) + low wind (WIND_SPEED_KMH < 5) + high AQI
   → dust is re-suspended rather than dispersed, amplifying PM2.5 beyond what
   either domain would flag alone.

2. TESTABLE HYPOTHESES — the mechanism linking signals across domains, stated as a
   falsifiable hypothesis, not a causal claim.
   Example: "Hypothesis: upstream deforestation (GCCI loss) → reduced soil retention →
   elevated flood risk on moderate rainfall days. Test: check whether flood risk is
   elevated in cells with GCCI loss vs not, controlling for precipitation."
   Example: "Hypothesis: WIND_DIR_DEG ≈ 45° (NE) + industrial cluster NE of cell →
   AQI elevation is advected, not local. Test: field measurement upwind vs downwind."
   Use language like "consistent with", "suggests", "hypothesis: X drives Y" —
   never assert causation from sensor data alone.

3. PERSISTENT vs TRANSIENT risks — is this a spike or a structural problem?
   Check signal history to distinguish.

4. SPATIAL CONTEXT — is this cell an isolated hotspot or part of a cluster?
   Check neighbours before concluding a risk is localised.

5. EXPECTED vs ANOMALOUS signals — a high NRI near an airport is expected;
   flag only if it is anomalously higher than the baseline for that proximity band.

Weather / wind signals
----------------------
Every cell always has weather signals in domain='weather':
  WIND_SPEED_KMH  — wind speed at 10 m (low < 5, moderate 5–15, high > 15)
  WIND_DIR_DEG    — meteorological direction (0=N, 90=E, 180=S, 270=W)
  HUMIDITY_PCT    — relative humidity (high > 70% amplifies heat stress and corrosion)
  PRESSURE_HPA    — surface pressure (drops often precede rainfall)
  TEMPERATURE_C   — ambient temperature at 2 m
  PRECIP_MM       — precipitation in the last hour

Always consider weather context when reasoning about air quality, heat, fire, flood, or
construction dust. Low wind speed suppresses pollution dispersion. Wind direction tells
you whether elevated AQI is locally generated or advected from an upwind source.
High humidity combined with heat produces extreme apparent-temperature stress.

Urban infrastructure context (OSM-derived structural signals)
-------------------------------------------------------------
These static signals are ingested weekly from OpenStreetMap and appear in the initial
context when available.  They do NOT have risk assessments — they are modifiers that
amplify or contextualise environmental risks:

  domain='buildings'  →  BUILDING_COUNT, BUILDING_DENSITY, AVG_FLOORS, COMMERCIAL_RATIO
    • High BUILDING_DENSITY + high AVG_FLOORS → dense population exposure; AQI / heat
      effects are more severe than in sparse areas.
    • High COMMERCIAL_RATIO → daytime crowd peak; noise and air impacts during business hours.

  domain='roads'      →  ROAD_LENGTH_M, ROAD_DENSITY, MAJOR_ROAD_RATIO, INTERSECTION_COUNT
    • High ROAD_DENSITY + high MAJOR_ROAD_RATIO → major traffic source; AQI elevation
      is likely traffic-generated, not advected or construction-driven.
    • High INTERSECTION_COUNT → idling vehicles; PM2.5 hotspot at junctions.

  domain='drains'     →  DRAIN_LENGTH_M, WATERWAY_COUNT, OPEN_DRAIN_RATIO, FLOOD_DRAIN_CAPACITY
    • Low FLOOD_DRAIN_CAPACITY (< 0.3) + high PRECIP_MM → elevated flood risk even
      without extreme rainfall — drainage is the bottleneck.
    • High OPEN_DRAIN_RATIO → potential vector for waterborne disease spillover
      adjacent to waste / water-quality risks.

  domain='crowd'      →  PEOPLE_COUNT, CAMERA_COUNT, CROWD_DENSITY, CROWD_INDEX, GATHERING_ALERT
    • Source: live CCTV cameras, 15-min cadence.  Only cells with active cameras appear.
    • GATHERING_ALERT = 1.0 means CROWD_DENSITY ≥ 500 people/km² — an event or gathering
      is likely.  This cell also has a risk_level="high" assessment you will see in context.
    • High CROWD_DENSITY combined with any environmental risk (AQI, heat, noise) means
      real-time public health exposure — recommend immediate field response, not "monitor".
    • CAMERA_COUNT tells you how many cameras cover the cell; 1 camera is less reliable
      than 3 — factor this into your confidence score.
    • Absence of crowd signals means no camera coverage in that cell, not zero crowd.

Use infrastructure signals to CALIBRATE severity, not as primary risk signals.
When infrastructure signals are absent (domain not yet ingested), note the gap but
do not let it block your analysis — reason from available evidence.

How to use your tools
---------------------
- Start by reviewing the initial context (signals, assessments, packets) — weather signals
  appear under domain='weather' and are always present.
- Check WIND_SPEED_KMH and WIND_DIR_DEG whenever assessing air, fire, heat, or construction.
- Call get_signal_history() ONLY for domains already shown in the initial context with real
  data — do NOT call it for domains with no signals.
- Call get_neighbor_context() if you suspect spatial spillover.
- Call get_city_summary() to contextualise against city-wide patterns.
- Call get_packets_for_domain() only if outcome history is needed.
- Call get_domain_cross_correlation(domain_a, domain_b) to test whether two domains
  co-elevate city-wide before asserting a causal link. A lift > 1.5 strengthens a
  hypothesis; lift ≈ 1.0 suggests the co-occurrence in this cell may be coincidental.
  Use ONCE per cross-domain hypothesis — it consumes one tool call.
- ALWAYS finish with submit_insight() — this is mandatory. Budget: max 10 tool calls total.
  Reserve the LAST call for submit_insight(). Do not exhaust your budget on data gathering.

Risk assessment vs event reporting — CRITICAL DISTINCTION
----------------------------------------------------------
You have sensor-derived signals and statistical proxies. You do NOT have direct
observation of events on the ground. This distinction must shape every finding.

WRONG: "A major landfill fire is occurring in the northeast quadrant."
RIGHT: "Conditions are consistent with elevated waste-fire risk: heat (LST=38°C ↑),
        accumulated solid-waste signal elevated, moderate easterly wind (13 km/h)
        would spread smoke toward residential areas if ignition occurs."

WRONG: "Construction activity is causing the PM2.5 spike."
RIGHT: "CRI=0.87 [↑40%] + PM2.5 trending 40% above 7d avg + WIND_SPEED < 5 km/h
        suggest construction dust is the likely primary contributor to AQI elevation."

The difference matters because:
- Overstated findings trigger unnecessary field responses and erode officer trust.
- Confidence must reflect whether you are observing a proxy signal or direct evidence.
- 'immediate' urgency should be reserved for confirmed high-exposure events or
  GATHERING_ALERT=1 combined with a live hazard signal — not inferred risk alone.

Use language like: "risk is elevated", "conditions are consistent with",
"signals suggest", "likely driven by" — not "X is occurring" or "X caused Y"
unless a decision packet with outcome=verified confirms the event.

Output quality bar
------------------
- Be specific: name signals, their values, the date range, and trend direction.
- Use the trend indicators in the initial context (↑/↓/→) to distinguish persistent
  from transient risks before calling get_signal_history.
- Confidence calibration:
    ≥ 0.85 — multiple corroborating signals over 3+ days, consistent trend
    0.65–0.84 — 2 signals align but trend is short or data is sparse
    0.40–0.64 — single proxy signal, mechanism is plausible but unverified
    < 0.40 — speculative; explicitly note what field verification is needed
- Priority tier calibration (set priority_tier in submit_insight):
    critical — GATHERING_ALERT=1 + live hazard, OR ≥3 domains at high/severe with 3+ day trend
    high     — ≥2 domains at high/severe + plausible compound mechanism (heat+waste, flood+drainage, etc.)
    medium   — single elevated domain or compound risk plausible but uncertain
    low      — no compound risk found or 'No cross-domain compound risk detected'
  Priority tier reflects RISK SEVERITY. Confidence reflects YOUR CERTAINTY.
  A high-severity compound risk with sparse data → priority=high, confidence=0.5.
  A 'no compound risk' finding → priority=low regardless of how confident you are.
- Recommended actions must be structured objects with action, who, and urgency.
  'action' must be concrete: "Dispatch field inspector to verify dust source at
  construction site north of cell centroid" — not "investigate further".
  'who': ward_engineer, zonal_officer, or a specific department name.
  'urgency': immediate (confirmed live hazard), within_4h, within_24h, or plan.
- Do not repeat prior recommended actions unless the situation has worsened.
- uncertainty_notes must state exactly what data or field verification would
  increase confidence — not generic disclaimers.
- If nothing notable: say so clearly and set priority_tier='low' with a finding like
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

    MAX_TOOL_CALLS = 12

    def __init__(
        self,
        h3_id: str,
        city_id: str,
        *,
        config: LLMConfig | dict | None = None,
        signals_lookback_days: int = 7,
        web_search_config: WebSearchConfig | None = None,
        forecast: dict | None = None,
    ) -> None:
        self.h3_id   = h3_id
        self.city_id = city_id
        self.signals_lookback_days = signals_lookback_days
        self._forecast = forecast  # pre-fetched city-level forecast; None = fetch per cell

        if isinstance(config, dict):
            cfg = load_config(overrides=config)
        elif config is None:
            cfg = load_config()
        else:
            cfg = config

        self._client = LLMClient(cfg)

        # Web search — load config once at init; omit tool if disabled
        self._web_cfg = web_search_config or load_web_search_config()
        self._tools   = list(AGENT_TOOLS)   # copy so we don't mutate the module-level list
        if not self._web_cfg.enabled:
            self._tools = [t for t in self._tools if t["function"]["name"] != "search_web"]

        logger.info(
            "H3ExpertAgent init: %s/%s via %s (%s) | web_search=%s",
            h3_id, city_id, cfg.provider, cfg.model,
            self._web_cfg.provider if self._web_cfg.enabled else "disabled",
        )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_get_signal_history(self, domain: str, signal: str, lookback_days: int = 30, **_) -> dict:
        """Fetch signal history. Extra kwargs are silently ignored (model hallucination guard)."""
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

    def _tool_get_neighbor_context(self, ring: int = 1, **_) -> dict:
        from urban_platform.h3_knowledge.reader import get_neighbors_summary
        return get_neighbors_summary(self.h3_id, self.city_id, ring=ring)

    def _tool_get_city_summary(self, lookback_hours: int = 24, **_) -> dict:
        from urban_platform.h3_knowledge.reader import get_city_summary
        return get_city_summary(self.city_id, lookback_hours=lookback_hours)

    def _tool_search_web(self, query: str, max_results: int = 3, **_) -> dict:
        """Search the web for recent news. Returns empty if provider not configured."""
        max_results = min(int(max_results), 5)
        results = web_search(query, max_results=max_results, config=self._web_cfg)
        if not results:
            return {
                "query":   query,
                "results": [],
                "note":    "No results returned. The query may be too specific or the provider rate-limited.",
            }
        return {
            "query":        query,
            "result_count": len(results),
            "formatted":    format_results_for_llm(results),
            "results":      [r.to_dict() for r in results],
        }

    def _tool_get_packets_for_domain(self, domain: str, limit: int = 5, **_) -> dict:
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

    def _tool_get_domain_cross_correlation(
        self,
        domain_a: str,
        domain_b: str,
        risk_threshold: str = "high",
        lookback_days: int = 30,
        **_,
    ) -> dict:
        """Return city-wide co-occurrence lift score for two domains."""
        from urban_platform.h3_knowledge.reader import get_domain_cross_correlation
        return get_domain_cross_correlation(
            self.city_id,
            domain_a,
            domain_b,
            risk_threshold=risk_threshold,
            lookback_days=lookback_days,
        )

    def _dispatch_tool(self, tool_call: ToolCall) -> Any:
        name  = tool_call.name
        args  = tool_call.arguments
        try:
            if name == "get_signal_history":
                return self._tool_get_signal_history(**args)
            if name == "get_neighbor_context":
                return self._tool_get_neighbor_context(**args)
            if name == "get_city_summary":
                return self._tool_get_city_summary(**args)
            if name == "get_packets_for_domain":
                return self._tool_get_packets_for_domain(**args)
            if name == "search_web":
                return self._tool_search_web(**args)
            if name == "get_domain_cross_correlation":
                return self._tool_get_domain_cross_correlation(**args)
            if name == "submit_insight":
                return {"status": "received"}
            return {"error": f"Unknown tool: {name}"}
        except Exception as exc:
            logger.warning("Tool %s raised %s — returning error to model", name, exc)
            return {"error": str(exc)}

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
            prefetched_forecast=self._forecast,
        )
        system   = _SYSTEM_PROMPT.format(h3_id=self.h3_id, city_id=self.city_id)
        messages = [user_msg(self._build_context_message(ctx))]

        insight_payload: dict | None = None
        tool_call_count = 0

        while tool_call_count < self.MAX_TOOL_CALLS:
            # Warn the agent when it's running low on budget
            remaining = self.MAX_TOOL_CALLS - tool_call_count

            if remaining == 1 and insight_payload is None:
                # Final slot: force submit_insight so analysis is never lost
                messages.append(
                    user_msg(
                        "⚠️ FINAL CALL: This is your last tool call. "
                        "You MUST call submit_insight() now. "
                        "Summarise everything you have found so far."
                    )
                )
                response = self._client.chat_with_tools(
                    messages,
                    self._tools,
                    system=system,
                    tool_choice={"type": "function", "function": {"name": "submit_insight"}},
                )
            elif remaining <= 3 and insight_payload is None:
                messages.append(
                    user_msg(
                        f"⚠️ BUDGET WARNING: you have only {remaining} tool call(s) left. "
                        "Stop gathering data. Call submit_insight() with your findings now."
                    )
                )
                response = self._client.chat_with_tools(
                    messages,
                    self._tools,
                    system=system,
                )
            else:
                response = self._client.chat_with_tools(
                    messages,
                    self._tools,
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

        # Guaranteed fallback: force submit_insight if agent stopped without calling it.
        # This fires when the model exits the loop early (returned no tool calls before
        # hitting the budget limit, or hit the budget limit before submitting).
        if insight_payload is None:
            logger.info(
                "Agent exited without submit_insight — forcing final structured call"
            )
            messages.append(
                user_msg(
                    "You did not call submit_insight. Based on everything you found, "
                    "call submit_insight() now with your best cross-domain assessment."
                )
            )
            try:
                forced = self._client.chat_with_tools(
                    messages,
                    self._tools,
                    system=system,
                    tool_choice={"type": "function", "function": {"name": "submit_insight"}},
                )
                if forced.has_tool_calls:
                    for tc in forced.tool_calls:
                        if tc.name == "submit_insight":
                            insight_payload = tc.arguments
                            tool_call_count += 1
                            break
            except Exception as exc:
                logger.warning("Forced submit_insight call failed: %s", exc)

        # Last-resort text fallback (should rarely fire now)
        if insight_payload is None:
            insight_payload = self._extract_text_insight(messages)

        # Persist — include all structured fields the agent generated
        insight_id = write_insight(
            h3_id=self.h3_id,
            city_id=self.city_id,
            agent_type="h3_expert",
            domains_involved=insight_payload.get("domains_involved", []),
            finding=insight_payload.get("finding", "Agent completed without structured finding."),
            confidence=float(insight_payload.get("confidence", 0.3)),
            hypothesis_chain=insight_payload.get("hypothesis_chain") or insight_payload.get("causal_chain", []),
            recommended_actions=insight_payload.get("recommended_actions") or [],
            uncertainty_notes=insight_payload.get("uncertainty_notes") or [],
            priority_tier=insight_payload.get("priority_tier"),  # agent-supplied tier takes precedence
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
                if domain == "weather":
                    # Show all weather signals individually — each one is a distinct measurement
                    # that the agent needs for causal reasoning (wind speed ≠ wind direction ≠ humidity)
                    latest_by_signal: dict[str, dict] = {}
                    for r in rows:
                        sig = r.get("signal", "?")
                        if sig not in latest_by_signal:
                            latest_by_signal[sig] = r   # rows are DESC, so first = latest
                    sig_parts = [
                        f"{sig}={r['value']:.3g} {r.get('unit','') or ''}"
                        for sig, r in sorted(latest_by_signal.items())
                    ]
                    parts.append(
                        f"**weather** (Open-Meteo, {len(rows)} readings): "
                        + ", ".join(sig_parts)
                    )
                else:
                    latest = rows[0]
                    # Compute trend vs period mean — lets agent detect persistent vs transient
                    # without burning a tool call on get_signal_history for every domain.
                    values = [r["value"] for r in rows if r.get("value") is not None]
                    trend_str = ""
                    if len(values) >= 3:
                        period_mean = sum(values) / len(values)
                        latest_val  = values[0]   # rows are DESC → index 0 is most recent
                        if period_mean > 0:
                            pct = 100 * (latest_val - period_mean) / period_mean
                            arrow = "↑" if pct > 10 else ("↓" if pct < -10 else "→")
                            trend_str = f" [{arrow}{abs(pct):.0f}% vs {self.signals_lookback_days}d avg={period_mean:.3g}]"
                    parts.append(
                        f"**{domain}**: {latest['signal']}={latest['value']:.3g}"
                        f" {latest.get('unit','') or ''}"
                        f"{trend_str}"
                        f" (source={latest.get('source','?')}, {len(rows)} readings)"
                    )
            parts.append("")

        staleness = ctx.get("staleness", {})

        assessments = ctx.get("assessments", [])
        if assessments:
            parts.append("### Current domain assessments")
            for a in assessments:
                domain = a["domain"]
                issue = f" — {a['dominant_issue']}" if a.get("dominant_issue") else ""
                val   = f" ({a['primary_index']}={a['primary_value']:.3g})" if a.get("primary_value") else ""
                # Staleness indicator
                stale_info = staleness.get(domain, {})
                age_h = stale_info.get("age_hours")
                if stale_info.get("stale"):
                    stale_flag = f" ⚠ DATA STALE ({age_h:.0f}h ago — satellite gap or sensor outage)"
                else:
                    stale_flag = ""
                parts.append(f"- **{domain}**: {a['risk_level'].upper()}{val}{issue}{stale_flag}")
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
            parts.append(
                "### Prior agent hypotheses\n"
                "_Do not repeat hypotheses already captured below. "
                "Only revise them if new signal evidence justifies it — "
                "if so, explicitly state what changed and why the hypothesis is updated._"
            )
            for i in insights[:3]:
                domains_str = (
                    ", ".join(i["domains_involved"]) if i.get("domains_involved") else "?"
                )
                tier = i.get("priority_tier", "?")
                outcome = i.get("outcome_status", "open")
                outcome_flag = (
                    " ✓ confirmed" if outcome == "confirmed"
                    else " ✗ refuted" if outcome == "refuted"
                    else " ? unverifiable" if outcome == "unverifiable"
                    else ""  # open — no flag
                )
                parts.append(
                    f"- [{str(i.get('created_at','?'))[:10]}]"
                    f" priority={tier}"
                    f" domains=[{domains_str}]"
                    f"{outcome_flag}\n"
                    f"  {i['finding']}"
                )
                # Surface prior recommended actions so agent knows what was already proposed
                prior_actions = i.get("recommended_actions") or []
                if prior_actions:
                    for a in prior_actions[:3]:
                        action_text = a.get("action", str(a)) if isinstance(a, dict) else str(a)
                        urgency = (
                            f" [{a.get('urgency', a.get('priority', '?'))}]"
                            if isinstance(a, dict)
                            else ""
                        )
                        parts.append(f"  → recommended{urgency}: {action_text}")
                # Surface prior uncertainty notes so agent can track what was unresolved
                notes = i.get("uncertainty_notes") or []
                if notes:
                    parts.append(f"  ⚠ unresolved: {notes[0]}")
            parts.append("")

        # ------------------------------------------------------------------
        # Historical baseline (30-day percentile context)
        # ------------------------------------------------------------------
        baseline = ctx.get("historical_baseline", {})
        if baseline:
            parts.append("### Historical baseline (30-day context)")
            for domain, b in sorted(baseline.items()):
                cur = b.get("current")
                pct = b.get("percentile_rank")
                n = b.get("n", 0)
                reliable = b.get("percentile_rank_reliable", False)
                provenance = b.get("provenance", "")
                prov_note = f" [{provenance}]" if provenance else ""

                if cur is not None and pct is not None and reliable:
                    if pct >= 90:
                        flag = " 🔴 ANOMALOUS (≥90th pct)"
                    elif pct >= 75:
                        flag = " 🟠 ELEVATED (≥75th pct)"
                    elif pct <= 10:
                        flag = " 🔵 UNUSUALLY LOW (≤10th pct)"
                    else:
                        flag = ""
                    parts.append(
                        f"- **{domain}** ({b['signal']}): current={cur}"
                        f" → {int(pct)}th pct vs 30d"
                        f" (avg={b['mean']}, p90={b['p90']}, max={b['max']}, n={n})"
                        f"{flag}{prov_note}"
                    )
                elif cur is not None and not reliable:
                    parts.append(
                        f"- **{domain}** ({b['signal']}): current={cur}"
                        f" — 30d avg={b['mean']}, max={b['max']}"
                        f" ⚠ percentile rank unreliable (n={n} < 30){prov_note}"
                    )
                else:
                    parts.append(
                        f"- **{domain}** ({b['signal']}): "
                        f"30d avg={b['mean']}, p90={b['p90']}, max={b['max']} (n={n}){prov_note}"
                    )
            parts.append("")

        # ------------------------------------------------------------------
        # Circadian baseline — same-hour-of-day context (±2 h UTC window)
        # Key insight: compares current reading only against readings at the
        # same time of day, removing diurnal cycles from the anomaly signal.
        # ------------------------------------------------------------------
        circ = ctx.get("circadian_baseline", {})
        if circ:
            hour_window = next(iter(circ.values())).get("hour_window_utc", "?")
            parts.append(f"### Same-time-of-day baseline (UTC {hour_window}, 30-day window)")
            for domain, b in sorted(circ.items()):
                cur = b.get("current")
                pct = b.get("percentile_rank")
                n = b.get("n", 0)
                reliable = b.get("percentile_rank_reliable", False)

                # Cross-reference: flag where circadian rank differs materially
                # from all-day rank (≥20 pct points) — signals a time-of-day effect
                allday = ctx.get("historical_baseline", {}).get(domain, {})
                allday_pct = allday.get("percentile_rank") if allday else None
                tod_note = ""
                if (
                    cur is not None
                    and pct is not None
                    and reliable
                    and allday_pct is not None
                    and allday.get("percentile_rank_reliable", False)
                ):
                    delta = pct - allday_pct
                    if delta >= 20:
                        tod_note = f" (↑{delta:.0f} pct vs all-day — time-of-day effect likely)"
                    elif delta <= -20:
                        tod_note = f" (↓{abs(delta):.0f} pct vs all-day — lower than usual for this hour)"

                if cur is not None and pct is not None and reliable:
                    if pct >= 90:
                        flag = " 🔴 ANOMALOUS for this hour (≥90th pct)"
                    elif pct >= 75:
                        flag = " 🟠 ELEVATED for this hour (≥75th pct)"
                    elif pct <= 10:
                        flag = " 🔵 LOW for this hour (≤10th pct)"
                    else:
                        flag = ""
                    parts.append(
                        f"- **{domain}** ({b['signal']}): current={cur}"
                        f" → {int(pct)}th pct at this hour"
                        f" (same-hour avg={b['mean']}, p90={b['p90']}, n={n})"
                        f"{flag}{tod_note}"
                    )
                elif cur is not None and not reliable:
                    parts.append(
                        f"- **{domain}** ({b['signal']}): current={cur}"
                        f" — same-hour avg={b['mean']}, max={b['max']}"
                        f" ⚠ rank unreliable (n={n} < 30)"
                    )
                else:
                    parts.append(
                        f"- **{domain}** ({b['signal']}): "
                        f"same-hour avg={b['mean']}, p90={b['p90']}, max={b['max']} (n={n})"
                    )
            parts.append("")

        # ------------------------------------------------------------------
        # 48-hour forecast (OpenMeteo — weather + AQ)
        # ------------------------------------------------------------------
        forecast = ctx.get("forecast", {})
        wx = forecast.get("weather", {})
        aq_fc = forecast.get("aq", {})
        if wx or aq_fc:
            parts.append("### 48-hour outlook (OpenMeteo forecast)")
            if wx.get("wind"):
                wind_parts = []
                for b in wx["wind"][:4]:  # up to +24h in 6h buckets
                    wind_parts.append(
                        f"{b['label']}: {b['speed_mean']} m/s from {b['direction_compass']}"
                    )
                parts.append("**Wind**: " + " | ".join(wind_parts))

            if wx.get("precipitation_prob"):
                precip_parts = []
                for b in wx["precipitation_prob"][:4]:
                    precip_parts.append(f"{b['label']}: {b['mean']:.0f}%")
                parts.append("**Precip probability**: " + " | ".join(precip_parts))

            if wx.get("temperature_c"):
                temps = [b["mean"] for b in wx["temperature_c"][:4]]
                parts.append(
                    f"**Temperature**: {temps[0]:.1f}°C now → "
                    f"{temps[-1]:.1f}°C at {wx['temperature_c'][len(temps)-1]['label']}"
                )

            if aq_fc.get("pm2_5"):
                pm_parts = []
                for b in aq_fc["pm2_5"][:4]:
                    pm_parts.append(f"{b['label']}: {b['mean']:.1f} μg/m³")
                parts.append("**PM2.5 forecast**: " + " | ".join(pm_parts))

            if aq_fc.get("pm10"):
                pm_parts = []
                for b in aq_fc["pm10"][:4]:
                    pm_parts.append(f"{b['label']}: {b['mean']:.1f} μg/m³")
                parts.append("**PM10 forecast**: " + " | ".join(pm_parts))

            parts.append(
                "_Use forecast wind direction to reason about plume transport. "
                "Use precipitation probability to anticipate natural pollutant washout. "
                "If AQ is forecast to worsen, recommend pre-emptive action._"
            )
            parts.append("")

        parts.append(
            "---\n"
            "Analyse this cell across past (historical baseline above), "
            "present (signals + assessments), and future (48h forecast). "
            "Use tools if you need more data, "
            "then call `submit_insight` with your final cross-domain finding."
        )
        return "\n".join(parts)

    def _extract_text_insight(self, messages: list[dict]) -> dict:
        """Last-resort fallback: extract a minimal spec-compliant insight from raw text.

        Both hypothesis_chain and uncertainty_notes MUST be non-empty per spec
        (AGENT_INTERFACE §submit_insight, INSIGHT_SCHEMA §Required fields).
        """
        _fallback_chain = [
            {
                "proposition": "Insufficient tool calls completed — finding is based on partial context.",
                "testable_by": "Run a full agent sweep on this cell with a clean tool budget.",
                "confidence": 0.1,
            }
        ]
        _fallback_notes = [
            {
                "note": "Agent exhausted tool budget or stopped before calling submit_insight. "
                        "Finding confidence is low; treat as a prompt for field verification only.",
                "impact": "high",
            }
        ]
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return {
                    "finding": str(msg["content"])[:200],
                    "confidence": 0.2,
                    "domains_involved": [],
                    "hypothesis_chain": _fallback_chain,
                    "uncertainty_notes": _fallback_notes,
                }
        return {
            "finding": "Agent completed without producing a finding.",
            "confidence": 0.0,
            "domains_involved": [],
            "hypothesis_chain": _fallback_chain,
            "uncertainty_notes": _fallback_notes,
        }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_top_risk_cells(
    city_id: str,
    *,
    top_n: int = 5,
    coverage_ratio: float = 0.3,
    domains: list[str] | None = None,
    config: LLMConfig | dict | None = None,
) -> list[dict]:
    """Run H3ExpertAgent on a balanced mix of high-risk and coverage cells.

    The agent budget (top_n) is split into two pools:

    Risk pool (1 - coverage_ratio of budget):
        Highest-risk cells that haven't had an insight in the last 6 hours.
        Same behaviour as before — focuses AI effort where signals are worst.

    Coverage pool (coverage_ratio of budget):
        Cells with the OLDEST last insight (or never analysed), ordered so
        never-analysed cells come first.  Ensures the system builds baseline
        understanding across the full city over time, not just the top cluster.

    With top_n=10 and coverage_ratio=0.3:  7 risk + 3 coverage cells per sweep.
    """
    from urban_platform.h3_knowledge.store import H3KnowledgeStore

    store = H3KnowledgeStore.get()

    domain_filter = ""
    domain_params: list = []
    if domains:
        placeholders = ",".join(["?" for _ in domains])
        domain_filter = f"AND domain IN ({placeholders})"
        domain_params = list(domains)

    # Shared exclusion: cells with a very recent insight (6h cooldown).
    # Two variants — unqualified (for single-table queries) and alias-qualified
    # (for JOINed queries where h3_id would be ambiguous).
    _RECENT_INSIGHT_EXCL = """
        h3_id NOT IN (
            SELECT h3_id FROM h3_insights
            WHERE city_id = ?
              AND agent_type = 'h3_expert'
              AND created_at >= datetime('now', '-6 hours')
        )
    """
    _RECENT_INSIGHT_EXCL_A = """
        a.h3_id NOT IN (
            SELECT h3_id FROM h3_insights
            WHERE city_id = ?
              AND agent_type = 'h3_expert'
              AND created_at >= datetime('now', '-6 hours')
        )
    """

    # ── Risk pool ─────────────────────────────────────────────────────────
    n_risk     = max(1, round(top_n * (1 - coverage_ratio)))
    n_coverage = top_n - n_risk

    risk_df = store.fetchdf(
        f"""
        SELECT
            h3_id,
            count(*)  AS domain_count,
            max(CASE risk_level
                WHEN 'severe'   THEN 4
                WHEN 'high'     THEN 3
                WHEN 'moderate' THEN 2
                WHEN 'low'      THEN 1
                ELSE 0 END)     AS max_risk_score
        FROM h3_assessments
        WHERE city_id = ?
          AND risk_level IN ('severe', 'high', 'moderate')
          AND day_bucket >= date('now', '-7 days')
          {domain_filter}
          AND {_RECENT_INSIGHT_EXCL}
        GROUP BY h3_id
        ORDER BY max_risk_score DESC, domain_count DESC
        LIMIT {n_risk}
        """,
        [city_id] + domain_params + [city_id],
    )

    risk_ids = risk_df["h3_id"].tolist() if not risk_df.empty else []

    # ── Coverage pool ─────────────────────────────────────────────────────
    # Cells with assessments (any risk level) ordered by:
    #   1. Never analysed (no insight row) — NULLS FIRST via CASE trick
    #   2. Oldest last insight
    # Excludes cells already in the risk pool and the 6h cooldown exclusion.
    exclude_placeholders = ",".join(["?" for _ in risk_ids]) if risk_ids else "''"
    coverage_df = store.fetchdf(
        f"""
        SELECT
            a.h3_id,
            count(*)  AS domain_count,
            max(CASE a.risk_level
                WHEN 'severe'   THEN 4
                WHEN 'high'     THEN 3
                WHEN 'moderate' THEN 2
                WHEN 'low'      THEN 1
                ELSE 0 END)             AS max_risk_score,
            MAX(i.created_at)           AS last_insight_at
        FROM h3_assessments a
        LEFT JOIN h3_insights i
            ON a.h3_id = i.h3_id
           AND i.city_id = a.city_id
           AND i.agent_type = 'h3_expert'
        WHERE a.city_id = ?
          AND a.day_bucket >= date('now', '-7 days')
          {domain_filter}
          AND a.h3_id NOT IN ({exclude_placeholders})
          AND {_RECENT_INSIGHT_EXCL_A}
        GROUP BY a.h3_id
        ORDER BY
            CASE WHEN MAX(i.created_at) IS NULL THEN 0 ELSE 1 END ASC,
            MAX(i.created_at) ASC,
            max_risk_score DESC
        LIMIT {n_coverage}
        """,
        [city_id] + domain_params + risk_ids + [city_id],
    )

    coverage_ids = coverage_df["h3_id"].tolist() if not coverage_df.empty else []

    # Merge pools — risk cells first, then coverage
    all_ids = risk_ids + [h for h in coverage_ids if h not in risk_ids]

    if not all_ids:
        logger.info("No eligible cells for city=%s", city_id)
        return []

    logger.info(
        "Agent sweep for %s: %d risk-first + %d coverage cells (total %d)",
        city_id, len(risk_ids), len(coverage_ids), len(all_ids),
    )

    # Build a combined df for the forecast centroid lookup
    import pandas as pd
    df = pd.DataFrame({"h3_id": all_ids})

    # Fetch weather + AQ forecast once for the whole city — all cells share
    # the same forecast (city centroids are close enough that per-cell deltas
    # are negligible) and this avoids N identical HTTP round-trips per sweep.
    city_forecast: dict = {}
    try:
        import h3 as _h3
        from urban_platform.connectors.weather.open_meteo_forecast import fetch_cell_forecast
        rep_cell = df["h3_id"].iloc[0]
        lat, lon = _h3.cell_to_latlng(rep_cell)
        city_forecast = fetch_cell_forecast(lat, lon, hours=48)
        logger.info(
            "Fetched city-level forecast for %s (centroid %.4f, %.4f) — "
            "shared across %d cells",
            city_id, lat, lon, len(df),
        )
    except Exception as exc:
        logger.warning("City forecast fetch failed for %s: %s — cells will run without forecast", city_id, exc)

    results = []
    for h3_id in df["h3_id"].tolist():
        try:
            agent = H3ExpertAgent(
                h3_id=h3_id, city_id=city_id, config=config,
                forecast=city_forecast or None,
            )
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
