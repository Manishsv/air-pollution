# AirOS Apps — Insight Schema Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Apps

---

## Purpose [INFORMATIVE]

An insight is the atomic output unit of an AirOS agent. It represents a cross-domain finding for a single H3 cell, produced after the agent has read temporal context, called validation tools, and formed testable hypotheses. This document defines the schema every insight MUST conform to.

---

## Insight Row [NORMATIVE]

```
Insight {
  insight_id:               string   REQUIRED  — globally unique identifier (UUID v4 recommended)
  h3_id:                    string   REQUIRED  — H3 resolution-8 cell this insight concerns
  city_id:                  string   REQUIRED  — city partition key
  agent_type:               string   REQUIRED  — identifier of the producing agent (e.g. "h3_expert")
  finding:                  string   REQUIRED  — human-readable summary (see constraints below)
  confidence:               float    REQUIRED  — agent confidence in [0.0, 1.0]
  priority_tier:            string   REQUIRED  — "high" | "medium" | "low" (derived from confidence)
  domains_involved:         string   REQUIRED  — comma-separated list of domain names
  hypothesis_chain_json:    string   OPTIONAL  — JSON array of HypothesisItem (see below)
  recommended_actions_json: string   OPTIONAL  — JSON array of RecommendedAction (see below)
  uncertainty_notes_json:   string   REQUIRED  — JSON array of UncertaintyNote (see below); MUST contain at least one entry
  outcome_status:           string   REQUIRED  — "open" | "confirmed" | "refuted" | "unverifiable"
  closed_by:                string   OPTIONAL  — reviewer identifier
  closed_at:                string   OPTIONAL  — ISO-8601 close timestamp
  created_at:               string   REQUIRED  — ISO-8601 creation timestamp (UTC)
}
```

---

## Field Constraints [NORMATIVE]

### `finding`

- MUST be a complete sentence or short paragraph in plain language.
- MUST mention the specific domains involved.
- MUST NOT make unqualified causal claims ("X caused Y"). Frame as "X is associated with Y" or "X is a likely contributor to Y, pending field verification".
- [INFORMATIVE: The reference dashboard renders `finding` in a summary card. Findings over approximately 500 characters may be truncated in some display contexts. Longer findings SHOULD be split into `finding` (summary) and `hypothesis_chain_json` (detail).]

### `confidence`

- MUST be in [0.0, 1.0].
- MUST reflect the agent's genuine uncertainty — not inflated to appear more authoritative.
- SHOULD be lower when: data is primarily `model_estimate` or `satellite_derived`; fewer than 3 domains are involved; the cell has fewer than 14 days of historical signals; prior similar insights were `refuted`.

### `priority_tier`

- MUST be derived deterministically from `confidence` using closed/half-open intervals:
  - `confidence ≥ 0.75` → `"high"`
  - `0.45 ≤ confidence < 0.75` → `"medium"`
  - `confidence < 0.45` → `"low"`
  - At the boundary `confidence = 0.45` → `"medium"` (inclusive lower bound)
- MUST NOT be manually overridden by the agent or the calling code.

### `domains_involved`

- MUST list every domain whose signals informed the finding.
- MUST be comma-separated, no spaces (e.g. `"air,construction,weather"`).
- Single-domain insights are permitted but SHOULD carry a note that cross-domain context was checked and found non-contributory.

---

## `HypothesisItem` Schema [NORMATIVE]

Each element of `hypothesis_chain_json` MUST conform to:

```json
{
  "proposition": "string — a specific, testable claim about this cell",
  "testable_by": "string — what evidence would confirm or refute this proposition",
  "confidence":  float    — confidence in this specific proposition (0.0–1.0)
}
```

**`proposition` constraints:**
- MUST be specific enough to be falsifiable
- MUST refer to this cell or its immediate neighbourhood
- MUST NOT be a tautology ("air quality is bad because AQI is high")

**`testable_by` constraints:**
- MUST describe a concrete verification action (field inspection, cross-check with dataset, lab test, permit check)
- MUST be actionable by a ward officer or engineer without specialist equipment
- SHOULD indicate the data source or authority that would provide the confirming evidence

**Example:**
```json
[
  {
    "proposition": "The PM2.5 spike in cell 8860145b4bfffff between 06:00–09:00 UTC is driven by construction activity at the active permit site 300m east",
    "testable_by": "Field inspection of construction site at lat 12.97, lon 77.59; cross-check active permit records for this cell; compare PM2.5 readings on days when the site is inactive",
    "confidence": 0.71
  },
  {
    "proposition": "Low wind speed this morning (1.2 m/s) prevented dispersion and amplified local concentration",
    "testable_by": "Compare PM2.5 readings on days with wind speed > 4 m/s at same construction activity level; check OpenMeteo historical wind data",
    "confidence": 0.85
  }
]
```

---

## `RecommendedAction` Schema [NORMATIVE]

Each element of `recommended_actions_json` MUST conform to:

```json
{
  "action":      "string — specific, human-executable action",
  "actor":       "string — role or department responsible (e.g. 'Ward Officer', 'BBMP Engineering')",
  "urgency":     "string — 'immediate' | 'within_4h' | 'within_24h' | 'this_week' | 'plan'",
  "condition":   "string — the condition under which this action is warranted",
  "blocked_if":  "string — OPTIONAL: condition under which this action MUST NOT be taken"
}
```

**Constraints:**
- `action` MUST be phrased as an instruction to a human ("Dispatch inspector to…", "Issue advisory…", "Review permit…")
- `actor` MUST refer to a role, not to AirOS itself — AirOS does not take actions
- `condition` MUST state what evidence warrants this action (not just "if risk is high")
- `blocked_if` SHOULD note data quality conditions that make the action premature (e.g. "blocked if DATA_CONFIDENCE < 0.5 for the primary signal")

---

## `UncertaintyNote` Schema [NORMATIVE]

Each element of `uncertainty_notes_json` MUST conform to:

```json
{
  "note":   "string — specific uncertainty or limitation",
  "impact": "string — 'low' | 'medium' | 'high' — impact on the reliability of this insight"
}
```

Every insight MUST include at least one `UncertaintyNote`. An insight with no declared uncertainty is non-conformant.

**Required uncertainty categories to consider:**

| Category | Example note |
|----------|-------------|
| Data source limitations | "PM2.5 data is IDW-interpolated from 2 sensors; nearest sensor is 4.2 km away (DATA_CONFIDENCE = 0.48)" |
| Temporal gaps | "No signals for this cell in the past 6 days — baseline comparison uses older data" |
| Missing cross-domain data | "Construction permit data is 8 days old; active sites may have changed" |
| Model limitations | "HEAT_RISK_SCORE uses Sentinel-2 LST which is a land surface proxy, not air temperature" |
| Insufficient history | "Cell has only 9 days of signal history — percentile comparisons are less reliable" |

---

## Outcome Lifecycle [NORMATIVE]

An insight begins in `outcome_status = "open"`. It transitions to a terminal status when a human reviewer closes it:

```
open → confirmed      Officer verified the finding in the field
open → refuted        Officer found the finding to be inaccurate
open → unverifiable   Officer could not gather sufficient evidence to confirm or refute
```

Once in a terminal status, an insight MUST NOT be re-opened. If the situation changes, a new insight MUST be written.

The closing officer's identifier MUST be recorded in `closed_by`. The timestamp MUST be recorded in `closed_at`.

**Outcome use in subsequent reasoning:** Agent Apps MUST read prior outcomes for a cell before generating a new insight. An agent that finds recent `refuted` outcomes for the same domain-pair hypothesis SHOULD lower its confidence in the same hypothesis or explicitly note the prior refutation.

---

## Agent Identity [NORMATIVE]

The `agent_type` field MUST be a stable identifier that uniquely identifies the agent implementation:

| Built-in agent | `agent_type` value |
|---------------|-------------------|
| H3 Expert Agent (cell-level) | `h3_expert` |
| City Pattern Agent (sweep-level) | `city_pattern` |

Third-party agents MUST register their `agent_type` in the App Descriptor and MUST use a namespaced identifier (e.g. `org_name.agent_name`) to avoid collisions with built-in agent types.

**Namespace reservation [NORMATIVE]:** The `airos.*` namespace is reserved for built-in AirOS agents. Third-party `agent_type` values MUST NOT begin with `airos.`. Agents using a reserved namespace prefix MUST be rejected by the App Descriptor validator.
