# AirOS Apps — Agent Interface Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Apps

---

## Purpose [INFORMATIVE]

This document defines the formal contract for LLM-backed agents in AirOS. It specifies the context assembly protocol, the tool set available to agents, the required output shape, and the system prompt requirements that any conformant agent implementation must satisfy.

AirOS ships two built-in agents:

- **H3 Expert Agent** — analyses one H3 cell at a time, reasoning across all environmental domains to produce a cross-domain insight.
- **City Pattern Agent** — synthesises the batch of cell-level insights from a sweep into city-wide thematic patterns.

Third-party agents that implement this interface may substitute for or extend the built-in agents, as long as they comply with the App Contract and the output schema defined in [Insight Schema](INSIGHT_SCHEMA.md).

---

## H3 Expert Agent [NORMATIVE]

### Role

The H3 Expert Agent is a single-cell reasoning agent. For each invocation, it receives:

- The full environmental context for one H3 cell (signals, assessments, history)
- Neighbour context (k-ring risk assessments)
- City-wide statistical context
- A tool set for on-demand signal retrieval and hypothesis validation

It produces exactly one insight per invocation via the `submit_insight` tool.

### Context Assembly [NORMATIVE]

Before the LLM call, the agent implementation MUST assemble the following context sections in this order:

| Section | Content | Required |
|---------|---------|---------|
| Cell identity | H3 index, centroid coordinates, land-use class, area name | YES |
| Recent signals | All domain signals for the past 7 days, with trend indicators (↑ >+10%, → stable, ↓ <−10%) | YES |
| Domain assessments | Current `risk_level` per domain + data staleness flag (hours since last ingest) | YES |
| Recent decision packets | Up to 5 most recent `h3_packets` for this cell, with `outcome_status` | YES |
| Prior agent insights | Previous `h3_expert` insights for this cell, with `outcome_status` (confirmed / refuted / open) | YES |
| 30-day baseline | Statistical summary (mean, 75th, 90th percentile) for each signal over the past 30 days (all-day) | YES |
| Circadian baseline | Statistical summary for the same ±2-hour window of day over the past 30 days | YES |
| 48-hour forecast | Wind speed/direction, precipitation probability, temperature, and available AQ forecast | SHOULD |

**Weather signals MUST always be included** in the recent signals section, even if the cell has no elevated weather risk. Wind speed, wind direction, humidity, pressure, temperature, and precipitation are contextual modifiers for all other domains.

**Trend indicators:** For each signal, the agent context MUST include a directional indicator comparing the most recent value to the 7-day mean: `↑` if >+10%, `↓` if <−10%, `→` otherwise.

**Data staleness:** For each domain, the agent context MUST include a staleness flag indicating how many hours have elapsed since the most recent ingest. A staleness greater than 2× the domain cadence SHOULD be flagged with a visible warning in the context.

### System Prompt Requirements [NORMATIVE]

An H3 Expert Agent implementation MUST instruct the LLM to:

1. **Focus on one cell.** All findings and hypotheses MUST concern the target cell or its immediate neighbourhood (k=1 or k=2 ring). City-wide claims MUST be supported by a `get_city_summary` tool call.
2. **Detect cross-domain interactions.** The agent MUST consider whether signals from multiple domains are co-elevated before producing an insight. A single-domain finding SHOULD include an explicit note that cross-domain context was checked and found non-contributory.
3. **Use testable hypotheses.** Propositions MUST be falsifiable. Causal language ("X caused Y") is prohibited. Permitted framing: "X is consistent with Y", "X is a likely contributor to Y, pending field verification".
4. **Calibrate confidence honestly.** Confidence MUST reflect genuine uncertainty: lower when data is primarily `model_estimate` or `satellite_derived`; lower when fewer than 3 domains are involved; lower when the cell has fewer than 14 days of signal history; lower when prior `refuted` outcomes exist for the same hypothesis type.
5. **Read prior outcomes before writing.** The agent MUST examine prior insight outcomes for this cell before producing a new insight. A prior `refuted` outcome for the same domain-pair hypothesis MUST either lower confidence or be explicitly noted in `uncertainty_notes`.
6. **Validate cross-domain claims with the lift tool.** Before asserting a cross-domain causal link, the agent MUST call `get_domain_cross_correlation` for the relevant domain pair. A lift score ≤ 1.5 SHOULD cause the agent to hedge or drop the cross-domain claim.
7. **Always submit.** The agent MUST call `submit_insight` as its final action. An agent run that ends without calling `submit_insight` is non-conformant. The implementation MUST enforce a maximum tool call budget (default: 12 calls) and force a `submit_insight` call if the budget is exhausted before the agent submits voluntarily.

### Tool Set [NORMATIVE]

The following tools MUST be available to the H3 Expert Agent:

#### `get_signal_history`

```
get_signal_history(domain: str, signal: str, lookback_days: int = 30) → SignalTimeSeries
```

Returns the time series for a specific signal for the target cell over the lookback window. Used to detect trends, spikes, and sustained anomalies beyond the pre-assembled context window.

#### `get_neighbor_context`

```
get_neighbor_context(ring: int = 1) → NeighborSummary
```

Returns the current risk assessments and top signal values for all cells in the k-ring neighbourhood. Used to determine whether a risk is localised to this cell or is part of a broader spatial pattern.

#### `get_city_summary`

```
get_city_summary(lookback_hours: int = 24) → CitySummary
```

Returns the city-wide risk distribution (count of cells per risk level per domain), top-risk cells, and the most recent city-level insights. Used to contextualise this cell's reading against the broader city situation.

#### `get_packets_for_domain`

```
get_packets_for_domain(domain: str, limit: int = 5) → list[DecisionPacket]
```

Returns recent decision packets for this cell and domain, including their `outcome_status`. Used to calibrate the current insight against previous reviewer decisions.

#### `get_domain_cross_correlation`

```
get_domain_cross_correlation(domain_a: str, domain_b: str, risk_threshold: str = "high", lookback_days: int = 30) → CrossCorrelationResult
```

Returns the city-wide lift score for co-elevation of `domain_a` and `domain_b`. A lift score > 1.5 indicates that the two domains are co-elevated more often than chance; this supports cross-domain hypothesis formation.

#### `search_web`

```
search_web(query: str, max_results: int = 3) → list[WebResult]
```

Searches for recent news or reports that may corroborate or contextualise the observed signals (e.g. a known industrial incident, weather event, policy change, or scheduled public event).

**Guardrails [NORMATIVE]:**
- MUST be used at most once per agent run (one call, not one per hypothesis).
- MUST NOT be used for routine signal interpretation — only to check whether a known external event explains an anomaly.
- Results from `search_web` are **contextual leads**, not primary evidence. An insight MUST NOT list a web search result as its primary supporting evidence unless the source is authoritative (government notice, weather service, official press release).
- If a `search_web` result is cited in the hypothesis chain or recommended actions, the `testable_by` field MUST require independent verification through system data or field observation — not sole reliance on the web source.
- `search_web` results MUST be identified as external context in `uncertainty_notes` (e.g. "External news report cited; not verified through system signals").

#### `submit_insight` [MANDATORY]

```
submit_insight(
  finding: str,
  confidence: float,
  domains_involved: list[str],
  hypothesis_chain: list[HypothesisItem],
  recommended_actions: list[RecommendedAction],
  uncertainty_notes: list[UncertaintyNote]
) → InsightWriteResult
```

Writes the structured insight to `h3_insights`. This is the only write operation the H3 Expert Agent may call. It MUST be called exactly once per agent run.

**`finding`:** A complete sentence summarising the cross-domain finding. MUST mention the domains involved. MUST NOT use unqualified causal language.

**`confidence`:** Float in [0.0, 1.0]. Determines `priority_tier` per the App Contract.

**`domains_involved`:** Every domain whose signals informed the finding.

**`hypothesis_chain`:** One or more `HypothesisItem` objects (see [Insight Schema](INSIGHT_SCHEMA.md)). MUST NOT be empty.

**`recommended_actions`:** Zero or more `RecommendedAction` objects. Each action MUST be addressed to a human role (`ward_engineer`, `zonal_officer`, `department`) with an urgency level (`immediate` / `within_4h` / `within_24h` / `this_week` / `plan`).

**`uncertainty_notes`:** One or more `UncertaintyNote` objects — each with a `note` string and an `impact` string (`low` / `medium` / `high`). MUST NOT be empty. See [Insight Schema — UncertaintyNote](INSIGHT_SCHEMA.md#uncertaintynote-schema).

### Tool Budget [NORMATIVE]

An H3 Expert Agent run MUST NOT make more than **12 tool calls** total (including `submit_insight`). The implementation MUST track the call count and force `submit_insight` if the budget is reached without a voluntary submission.

The budget is structured as: up to 11 exploration calls + 1 mandatory `submit_insight`. Implementations SHOULD reserve at least 1 budget slot for `submit_insight` from the start.

---

## City Pattern Agent [NORMATIVE]

### Role

The City Pattern Agent is a sweep-level synthesis agent. It runs once per city after the H3 Expert Agent batch completes. It reads the batch of newly produced cell-level insights and identifies city-wide thematic patterns.

### Input Context [NORMATIVE]

The City Pattern Agent MUST receive:

| Input | Content |
|-------|---------|
| Recent insights | Up to 30 most recent `h3_expert` insights for the city, ordered by confidence descending |
| Domain frequency | Count of insights per domain in this batch |
| Domain co-appearance | Pairs of domains that co-appear in the same insight, with frequency |
| Hotspot cells | H3 cells that appear in ≥ 2 insights in this batch |
| City-wide correlations | Lift scores for the top 5 domain pairs by co-elevation frequency |
| Risk distribution | Count of cells per `priority_tier` (`high` / `medium` / `low`) in this batch |

### Output Requirements [NORMATIVE]

The City Pattern Agent MUST produce a structured JSON output conforming to:

```json
{
  "executive_summary": "string — 2–4 sentence city-wide summary",
  "themes": [
    {
      "title": "string — short theme label",
      "description": "string — what is happening and where",
      "domains": ["domain_a", "domain_b"],
      "n_cells_affected": int,
      "confidence": float,
      "evidence": "string — which cells and signals support this theme",
      "recommended_city_action": "string — city-level (not cell-level) action",
      "priority": "high | medium | low"
    }
  ],
  "emerging_risks": "string — patterns that are nascent but not yet high-confidence",
  "data_quality_note": "string — any significant data gaps or staleness issues observed"
}
```

**Theme count [NORMATIVE]:** The output MUST contain between 1 and 5 themes. A theme MUST be supported by at least 3 affected cells OR at least 2 independent high-confidence insights. The City Pattern Agent MUST NOT fabricate themes from weak evidence.

**Skip condition:** If fewer than 3 new insights were produced in the current sweep, the City Pattern Agent MUST NOT run and MUST NOT write to `city_patterns`. The Scheduler is responsible for enforcing this gate (see [Scheduler](SCHEDULER.md)).

### Persistence [NORMATIVE]

The City Pattern Agent MUST write its output to `city_patterns` via `write_city_pattern()`. The written record MUST include:

| Field | Value |
|-------|-------|
| `pattern_id` | Unique identifier (UUID) |
| `city_id` | City partition key |
| `created_at` | UTC timestamp |
| `lookback_hours` | Time window of insights analysed |
| `n_insights` | Number of insights included in synthesis |
| `theme_count` | Number of themes identified |
| `summary_json` | Full JSON output as defined above |

---

## Agent Identity and Versioning [NORMATIVE]

Every agent run MUST write `agent_type` to the insight or pattern record. Built-in agent type identifiers:

| Agent | `agent_type` |
|-------|-------------|
| H3 Expert Agent | `h3_expert` |
| City Pattern Agent | `city_pattern` |

The `airos.*` namespace is reserved for built-in agents. Third-party agents MUST use a namespaced identifier (e.g. `org.agent_name`).

Agent versions SHOULD be recorded in the App Descriptor and SHOULD be included in insight metadata to enable tracing insights back to the agent version that produced them.

---

## Conformance Requirements Summary [NORMATIVE]

| Requirement | H3 Expert Agent | City Pattern Agent |
|-------------|-----------------|-------------------|
| Context assembly sections | MUST include all 7 REQUIRED sections (48h forecast is SHOULD) | MUST include all 6 input sections |
| Tool budget enforced | MUST cap at 12 tool calls | N/A (single-turn) |
| `submit_insight` always called | MUST — forced if budget exhausted | N/A |
| `uncertainty_notes` non-empty | MUST | N/A |
| `hypothesis_chain` non-empty | MUST (H3 Expert Agent requirement; `hypothesis_chain_json` is OPTIONAL for other App types per Insight Schema) | N/A |
| Prior outcomes read | MUST before producing insight | N/A |
| Cross-domain lift validated | MUST before asserting cross-domain link | N/A |
| Theme count 1–5 | N/A | MUST |
| Theme evidence ≥ 3 cells or ≥ 2 insights | N/A | MUST |
| Skip if < 3 insights | N/A | MUST |
| Write to Knowledge Store only | MUST (via `submit_insight`) | MUST (via `write_city_pattern`) |
| Human review required | MUST (see App Contract) | MUST |
