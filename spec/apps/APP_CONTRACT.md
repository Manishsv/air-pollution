# AirOS Apps — Application Contract Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Apps

---

## Purpose [INFORMATIVE]

This document defines what an AirOS App is allowed to read, what it is allowed to write, and the safety posture it must maintain. These constraints are architectural — they exist to guarantee that the platform never automates government decisions, and that every output surfaced to an officer is traceable to evidence.

---

## What an App Is [INFORMATIVE]

An AirOS App is any component that reads from the Knowledge Store, performs reasoning, and produces structured outputs for human review. Apps include:

- LLM-backed agents (H3 Expert Agent, City Pattern Agent)
- Statistical risk synthesisers
- Decision support dashboards
- Program reporting tools
- Third-party analytical applications

An App does NOT include:

- Data acquisition components (those are Drivers)
- The Knowledge Store itself (that is Core)
- Components that automate administrative decisions (those are prohibited)

---

## Read Contract [NORMATIVE]

An App MUST read from the Knowledge Store exclusively through the Core read interface. An App MUST NOT:

- Query `h3_signals` or `h3_assessments` using raw SQL that bypasses the read interface
- Read directly from Driver source data (APIs, satellite imagery, sensor feeds)
- Read from another App's private state — all shared state lives in the Knowledge Store

**Permitted read operations (minimum set):**

| Operation | Returns |
|-----------|---------|
| `get_h3_context(h3_id, city_id)` | All signals and assessments for a cell |
| `get_signals_history(h3_id, city_id, domain, signal, days)` | Time series |
| `get_neighbors_summary(h3_id, city_id, k)` | k-ring neighbour assessments |
| `get_city_summary(city_id)` | City-wide risk distribution |
| `get_domain_cross_correlation(city_id, domain_a, domain_b)` | Domain lift score |
| `get_packets_for_domain(h3_id, city_id, domain, limit)` | Recent decision packets for a cell and domain, with outcome status |
| `get_store_stats(city_id)` | Row counts, last ingest timestamps, per-domain coverage metrics |

An App MAY implement additional read operations on top of these, as long as they query only the Knowledge Store tables defined in the Core specification.

---

## Write Contract [NORMATIVE]

An App MUST write only to these Knowledge Store tables:

| Table | Write operation | When |
|-------|----------------|------|
| `h3_insights` | `write_insight(...)` | After agent reasoning produces a finding |
| `h3_packets` | `write_packet(...)` | When packaging evidence for a reviewer |
| `h3_insights.outcome_status` | `close_insight(insight_id, outcome, closed_by)` | When a reviewer records their decision |
| `city_patterns` | `write_city_pattern(...)` | After a sweep-level synthesis agent runs |

An App MUST NOT write to:

- `h3_signals` — only Drivers write signals
- `h3_assessments` — only Drivers write assessments
- `h3_ingest_log` — only the Scheduler and Drivers write watermarks
- `h3_metadata` — only Drivers write cell registration

Violation of the write contract is a conformance failure. Implementations MAY enforce this at the database layer (separate write credentials for Drivers and Apps) or at the API layer.

---

## Temporal Context Contract [NORMATIVE]

When an agent App reasons about a cell, it MUST assemble and consider at least two temporal horizons:

**1. Baseline (all-day, 30 days)**  
Statistical summary (mean, 75th percentile, 90th percentile) of all signals for the cell over the past 30 days. This characterises what is "normal" for this cell overall.

**2. Circadian baseline (same-hour-of-day, 30 days)**  
Statistical summary of signals for the same ±2-hour window of day over the past 30 days. This removes the diurnal cycle so that a reading at 2am is judged against other 2am readings, not the all-day average.

An App SHOULD also assemble:

**3. 48-hour forecast**  
Wind speed and direction, precipitation, temperature, and (where available) AQ forecast for the next 48 hours. This enables the agent to reason about whether current conditions are likely to worsen or improve.

**Rationale:** An agent that does not consider the circadian baseline will over-flag readings that are normal for their time of day (e.g. peak-hour AQ spikes) and under-flag anomalies that occur outside business hours.

---

## Insight Quality Requirements [NORMATIVE]

Every insight written to `h3_insights` MUST satisfy the following:

### Confidence score required

Every insight MUST carry a `confidence` value in [0.0, 1.0]. An insight without a confidence score MUST NOT be written to the store.

### Priority tier derived from confidence

The `priority_tier` field MUST be derived from confidence as follows:

| confidence | priority_tier |
|------------|--------------|
| confidence ≥ 0.75 | `high` |
| 0.45 ≤ confidence < 0.75 | `medium` |
| confidence < 0.45 | `low` |

An App MUST NOT override this derivation. The mapping is fixed by this specification.

### Testable hypotheses, not causal claims

Insights MUST be framed as testable propositions. The `hypothesis_chain_json` field MUST be an array of objects of the form:

```json
{
  "proposition": "Construction activity in cell 88XXX is the primary source of elevated PM2.5",
  "testable_by": "Field inspection of active construction sites; cross-check with permit records",
  "confidence": 0.72
}
```

The `testable_by` field MUST describe what evidence would confirm or refute the proposition. Causal language that is not testable ("X caused Y definitively") is non-conformant.

### Cross-domain claims require prior validation

Before an insight asserts a cross-domain causal link (e.g. "construction activity is causing the AQ spike"), the agent MUST have called `get_domain_cross_correlation` for the relevant domain pair and received a lift score above a reasonable threshold (reference threshold: lift > 1.5). If the lift score is below threshold, the agent SHOULD hedge the claim or not make it.

---

## Safety Posture [NORMATIVE]

### Human review is mandatory

An AirOS App MUST NOT take or trigger any administrative action directly. Every App output that requires action MUST pass through a human review step.

Prohibited automated actions include (non-exhaustive):
- Issuing a notice of violation or enforcement action
- Authorising or initiating fund release
- Publishing a public advisory without officer approval
- Dispatching a field officer or vehicle without human authorisation
- Updating any external government system

### Confidence and uncertainty MUST be disclosed

Every insight, decision packet, and advisory candidate MUST carry:
- The `confidence` score that drove it
- The `priority_tier` derived from confidence
- At least one "when not to act" condition in `uncertainty_notes_json`

An App that surfaces outputs without confidence disclosure is non-conformant.

### Safety gates MUST be checked

Domain-specific safety gates are defined in the domain spec YAML (e.g. `specifications/domain_specs/air_quality.v1.yaml`). An App generating decision packets for a domain MUST check and record the applicable safety gates.

The `h3_packets.safety_gates_json` field MUST list each gate, its check result (pass / fail / not_applicable), and the evidence used to evaluate it.

### Blocked uses MUST be declared

Every decision packet MUST include a `blocked_uses_json` field listing what the packet MUST NOT be used for. The domain spec YAML defines the mandatory blocked uses. The App MAY add deployment-specific blocked uses.

Example blocked uses for air quality:
- Do not use as grounds for automated enforcement action
- Do not label as full AQI if only PM2.5 is measured
- Do not use synthetic or interpolated data for formal public advisories without human review

---

## App Descriptor [NORMATIVE]

Every App MUST be declared by an App Descriptor. The App Descriptor is a machine-readable manifest that declares the App's identity, contracts, and safety posture. The normative schema is `air_os_app_descriptor.v1.schema.json` (in `specifications/platform_objects/`).

**Required App Descriptor fields [NORMATIVE]:**

| Field | Type | Description |
|-------|------|-------------|
| `app_id` | string | Unique identifier for this App (namespaced, e.g. `org.app_name`) |
| `app_version` | string | SemVer version string |
| `input_contracts` | list | Knowledge Store tables this App reads from, with consumer contract references |
| `output_contracts` | list | Schemas for insights, packets, and/or city patterns this App writes |
| `safety.review_support_only` | boolean | MUST be `true` — Apps MUST declare they are review support tools |
| `safety.human_review_required` | boolean | MUST be `true` — Apps MUST declare human review is required before action |
| `safety.blocked_uses` | list of strings | Uses this App's outputs must never be put to |
| `agent_type` | string | For agent Apps: the `agent_type` identifier written to insights (MUST be namespaced for third-party agents) |

An App that does not have a conformant App Descriptor MUST NOT be surfaced in production deployments.

---

## Outcome Tracking [NORMATIVE]

Every insight written by an agent App MUST be closeable by a human reviewer. The close operation MUST accept one of:

| outcome_status | Meaning |
|----------------|---------|
| `confirmed` | The officer investigated and the finding was accurate |
| `refuted` | The officer investigated and the finding was inaccurate |
| `unverifiable` | The officer could not verify or refute the finding with available evidence |

The App MUST make prior outcomes available to the agent on subsequent reasoning runs. An agent that repeatedly produces findings for the same cell in the same domain without reading prior outcomes is non-conformant.

**Automated closure is prohibited [NORMATIVE]:** An App MUST NOT call `close_insight` automatically. The `close_insight` operation MUST be invoked only in response to an explicit human action (an officer clicking a close control in a review dashboard or equivalent). Any system that automatically transitions `outcome_status` from `open` without human input is non-conformant, regardless of the confidence level of the underlying insight.
