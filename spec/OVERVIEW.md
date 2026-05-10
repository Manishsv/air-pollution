# AirOS — Platform Overview

**Version:** 1.0.0-draft  
**Status:** Draft

---

## What AirOS Is

AirOS is a city decision-support platform specification. It defines a four-component stack for ingesting environmental and infrastructure signals, detecting anomalies and risk patterns, assembling evidence-backed hypotheses, and surfacing them to human officers for review before any action is taken.

AirOS does not determine what is wrong. It detects patterns, packages evidence, proposes hypotheses, and supports accountable human decision-making.

AirOS is defined by three invariants that any compliant implementation must honour:

**1. Spatial-first.**  
All signals, assessments, and insights are anchored to a hexagonal spatial grid (see [Core / Spatial Model](core/SPATIAL_MODEL.md)). Raw observations — sensor readings, satellite pixels, crowd counts, road segments — are translated to per-cell signals before analysis. The city is always addressed as a grid, never as a flat list of records.

**2. Contracts before code.**  
Every component boundary is governed by a machine-readable contract. No Driver ships without a signal schema. No App ships without declaring what it reads and writes. Conformance is checkable without running the full stack (see [Drivers / Conformance](drivers/CONFORMANCE.md)).

**3. Human review is mandatory.**  
AirOS does not issue government decisions. It produces structured evidence — confidence scores, hypothesis chains, safety gates, and "when not to act" guidance — that a human officer reviews before any action is taken. This constraint is architectural, not advisory (see [Apps / Safety Posture](apps/APP_CONTRACT.md#safety-posture)).

---

## The Four Components

### Core

The Core is the operating layer. It owns:

- **Knowledge Store** — the authoritative spatial-temporal database. All signals, assessments, insights, and decision packets live here. Drivers write to it. Apps read from it.
- **Spatial Model** — the H3 hexagonal grid that all components share as a common address space.
- **Rules Registry** — centralised, operator-editable thresholds for all domain risk classifications.
- **Scheduler** — orchestrates Driver fetch cadences and Agent sweep cadences against a city's cell inventory.

The Core defines the contracts that Drivers and Apps must honour. It does not know which Drivers are installed or which Apps are running.

### Drivers

Drivers are the data source layer. A Driver:

- Fetches raw data from one upstream source (API, satellite, sensor, OSM, camera feed, …)
- Maps it to H3 cells (using one of the four canonical assignment methods)
- Writes signals to the Knowledge Store via the Core write interface
- Optionally writes risk assessments for risk-producing domains

Drivers are independently versioned and deployable. A compliant Driver need not know anything about other Drivers or about Apps. It needs only the Core write interface and its own upstream data source.

The **14** canonical AirOS domains (air, fire, heat, flood, water, waste, construction, green, noise, weather, buildings, roads, drains, crowd) are defined in the [Domain Catalogue](drivers/DOMAIN_CATALOGUE.md). This count is an invariant — adding or removing a canonical domain requires a spec version bump and an update to the Domain Catalogue. New non-canonical domains may be added by any implementer by implementing the Driver Interface and declaring a domain spec.

### Apps

Apps are the decision support layer. An App:

- Reads signals and assessments from the Knowledge Store (read-only access to Driver outputs)
- Runs reasoning — statistical, LLM-backed, rule-based, or hybrid
- Writes structured insights, decision packets, and city-pattern summaries to the Knowledge Store
- Surfaces outputs to human reviewers — never to automated action pipelines

The AirOS reference implementation ships two built-in agents:
- **H3 Expert Agent** — cell-level cross-domain reasoning, one cell at a time
- **City Pattern Agent** — sweep-level synthesis across all recently-analysed cells

Third-party Apps may implement any reasoning approach as long as they comply with the App Contract.

### Network

The Network layer enables two or more AirOS instances to coordinate across jurisdictional boundaries — sharing signals, risk assessments, insights, and advisory candidates between independently-operated nodes. Common use cases: a city AirOS node sharing upstream flood readings with a downstream district node; a state-level node receiving air quality summaries from multiple city nodes; two adjacent municipal corporations sharing crowd event alerts.

Each node remains sovereign — it operates its own Knowledge Store, applies its own Rules Registry, and makes its own review decisions. The Network layer carries data between nodes; it never centralises control.

The Network layer is:

- **Optional** — a single-node deployment operates fully without it
- **Domain-agnostic** — the Network layer routes contract-shaped envelopes; it never interprets domain semantics
- **Policy-aware** — each node declares which message types it accepts from which counterparties

The Network specification is minimal by design. Domain logic stays in Drivers and Apps. The Network layer only needs to know: sender, receiver, payload reference, message type, and delivery acknowledgement.

---

## Component Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                       Apps                                   │
│  Agents, dashboards, reporting tools, third-party apps       │
│  READ: signals, assessments, insights, city patterns         │
│  WRITE: h3_insights, h3_packets, city_patterns               │
└──────────────────────┬──────────────────────────────────────┘
                       │  read / write insights, packets, city patterns
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                       Core                                   │
│  Knowledge Store · Spatial Model · Rules Registry · Scheduler│
│  The only persistent state in the system                     │
└──────────────────────┬──────────────────────────────────────┘
                       │  write signals + assessments
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Drivers                                 │
│  14 canonical domains + extensible third-party domains       │
│  WRITE: h3_signals, h3_assessments                           │
│  READ: upstream data sources only (never the Knowledge Store)│
└─────────────────────────────────────────────────────────────┘

      ┌────────────────────────────────────────────────┐
      │                   Network (optional)            │
      │  Routes contract-shaped messages between nodes  │
      │  Does not interpret domain semantics            │
      └────────────────────────────────────────────────┘
```

**Direction rules [NORMATIVE]:**

1. Drivers MUST read only from `h3_ingest_log` (their own ingest watermark) during a fetch cycle. Drivers MUST NOT read from any other Knowledge Store table during a fetch, with one exception: structural context Drivers (buildings, roads, drains, weather) MAY read their own prior signals from `h3_signals` for change detection. All other Drivers MUST NOT read `h3_signals` or `h3_assessments`. Reading the ingest watermark is a standard, required part of the fetch flow — not an exception to the isolation rule.
2. Apps MUST NOT write to `h3_signals` or `h3_assessments`. Apps MUST write only to `h3_insights`, `h3_packets`, and `city_patterns`.
3. Core MUST NOT import from Drivers or Apps at module load time.
4. The Network layer MUST NOT call Driver or App code directly. It communicates exclusively via the Knowledge Store and the message envelope contract.

---

## The Evidence Ladder [INFORMATIVE]

AirOS produces four distinct types of output, each with different semantics and different accountability implications:

| Level | Name | What it is | Who produces it | Example |
|-------|------|------------|-----------------|---------|
| 1 | **Signal** | A measured or derived value for a cell at a point in time | Driver | PM2.5 = 87 µg/m³ at cell 005, 9am |
| 2 | **Assessment** | A rule-based risk classification derived from signals | Driver | Cell 005 air quality: POOR |
| 3 | **Insight** | A cross-domain hypothesis with evidence and verification path | Agent App | Construction dust may be contributing to elevated PM2.5; inspect site |
| 4 | **Action** | A human-authorised response to a confirmed finding | Officer | Site inspection ordered |

These levels are not interchangeable. An assessment is not a finding. An insight is not a determination. An action requires human authorisation at every step. No component in AirOS may skip a level or collapse two levels into one.

---

## Non-Goals [NORMATIVE]

AirOS is not:

- **An automated decision-making system.** Every output requiring human action must pass through a human review step. See [Apps / Safety Posture](apps/APP_CONTRACT.md#safety-posture).
- **A determination system.** AirOS detects patterns and proposes hypotheses. It does not determine causes, assign blame, or establish facts. Every insight is a testable proposition, not a finding of fact.
- **A surveillance system.** AirOS does not identify individuals. Crowd data is aggregated to cell level before entering the Knowledge Store. Raw camera or sensor feeds are not stored by AirOS.
- **A source of legal proof.** AirOS outputs are decision support, not evidence for enforcement proceedings. Domain spec YAML files define blocked uses per domain; automated enforcement is a blocked use for all risk domains.
- **A real-time streaming platform.** AirOS operates on scheduled fetch cadences, not streaming event pipelines. Sub-minute event processing is outside scope.
- **A data warehouse.** The Knowledge Store is a purpose-built operational store optimised for spatial-temporal querying and agent context assembly. It is not a general analytics database.
- **A single-vendor platform.** The specification is designed so that any component can be replaced by a conformant alternative implementation.
- **A black-box AI.** Every insight carries a full hypothesis chain, confidence score, uncertainty notes, and source provenance. An officer must be able to understand and contest any finding.

---

## Known Limitations [INFORMATIVE]

AirOS implementations should acknowledge and design controls around these inherent limitations:

**Data quality limits:**
- Sparse sensor networks produce interpolated estimates, not measurements, for most cells. `DATA_CONFIDENCE` communicates this but does not eliminate it.
- Satellite imagery may be unavailable due to cloud cover, revisit gaps, or vendor outages.
- Administrative records (permits, OSM) may be stale; their age is not always known.
- Sensor vendors may change API schemas without notice; driver conformance checks catch schema changes but not semantic drift.

**Spatial model limits:**
- H3 cell boundaries are geometric, not ecological or administrative. A real-world event (flood, fire, construction site) may span cell boundaries and appear as multiple separate signals.
- Centroid-based polygon assignment may misplace large features (industrial sites, campuses, lakes) that span many cells.

**Agent limits:**
- LLM-backed agents may over-interpret correlations. The lift validation gate and testable-hypothesis requirement reduce but do not eliminate this risk.
- An agent's confidence score reflects its training and context, not objective probability. Officers should treat confidence as a relative ranking, not an absolute measure.
- Prior `refuted` outcomes reduce future confidence for similar hypotheses in the same cell, but do not prevent the agent from repeating a false positive if signals genuinely recur.

**Structural limits:**
- The conformance gate validates schema and structure, not truth. A sensor reporting plausible values that are physically wrong will pass conformance.
- Rules Registry thresholds encode operational policy choices. Thresholds that are poorly calibrated for a city's context will produce systematically mis-classified assessments.
- Communities with fewer sensors or poorer OSM mapping will have lower `DATA_CONFIDENCE` across more signals, potentially receiving less agent attention than better-instrumented areas.

---

## Design Principles

**Cells, not records.** Analysis always starts from a spatial cell. Records are intermediate representations, not the primary abstraction.

**Provenance at every row.** Every signal row carries `data_quality` (real_station / satellite_derived / model_estimate / unknown) and `DATA_CONFIDENCE` (0–1). Reasoning that ignores provenance is non-compliant.

**Confidence, not certainty.** Every agent output carries a `confidence` score. The confidence determines the `priority_tier` (high / medium / low). Outputs without confidence scores MUST NOT be surfaced to reviewers as actionable.

**Testable hypotheses, not causal claims.** Agent insights MUST be framed as testable propositions with a `testable_by` field stating what evidence would confirm or refute them. Causal language ("X caused Y") is prohibited.

**Separation of read and write paths.** The Scheduler drives writes (Drivers → Core). Apps drive reads and insight writes. These paths never cross within a component boundary.

**Source provenance is never discarded.** Downstream analysis operates at the cell level, but every cell-level signal retains its `source`, `data_quality`, `observed_at`, and assignment method so any value can be traced back to its origin. Raw source geometry and identifiers are preserved by Drivers. Aggregation is a view, not a deletion.

**Rules are policy, not configuration.** Thresholds in the Rules Registry determine which communities are classified as high-risk and which sites get inspected. They MUST be versioned, auditable, and explainable. Changing a threshold is an operational policy decision, not a software deployment.

**Hypotheses, not determinations.** AirOS generates testable propositions. Officers make determinations. No component may present an insight as a finding of fact, and no insight may be used as the sole basis for an enforcement action.
