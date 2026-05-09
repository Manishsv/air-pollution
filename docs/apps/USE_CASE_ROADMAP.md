# AirOS Use Case Roadmap

This roadmap organizes AirOS city-management capabilities into **phases**. Each phase is designed to be specs-first: required provider contracts, platform objects, domain specs, and consumer contracts must exist and conformance must pass before the phase is considered complete.

**Governance and deployment context:** Indian cities differ in capacity, data maturity, and institutional fragmentation—see [`docs/URBAN_CONTEXT_INDIA.md`](URBAN_CONTEXT_INDIA.md). The AI CoE and forward deployment model that configures AirOS per city is described in [`docs/AI_COE_OPERATING_STRATEGY.md`](AI_COE_OPERATING_STRATEGY.md). Together they explain **open-data-first** slices and **progressive** integration sequencing used throughout this roadmap.

## Phased platform roadmap

### Phase 1. City base layer

- **purpose**: Establish shared city primitives so all domains can reuse boundaries, grids, entities, and identifiers.
- **city actors served**: platform engineers, GIS teams, city data office
- **capabilities**:
  - canonical `city_id`, `area_id` / ward boundaries, and base geospatial reference layers
  - H3 grid generation and boundary selection modes
  - canonical entity identity conventions (assets, wards, stations, parcels)
- **required data sources**:
  - administrative boundaries (wards/city)
  - base map layers (roads/buildings/water bodies as baseline)
- **required specifications**:
  - platform objects: `Entity`, `Boundary`, `Feature` (as applicable)
  - provider contracts for boundary layers if ingested
- **example dashboards**:
  - “City base map + layers catalog”
  - “Boundary/ward explorer”
- **acceptance criteria**:
  - canonical IDs and geometry conventions documented
  - reusable boundary + grid artifacts can be produced for a city

### Phase 2. Data governance and conformance layer

- **purpose**: Make specs-first development enforceable; ensure every provider and consumer surface is contract-driven.
- **city actors served**: platform engineers, city data office, audit/governance reviewers
- **capabilities**:
  - provider contracts, consumer contracts, platform objects, domain specs
  - mandatory conformance + audit reports
  - provenance and source reliability semantics
- **required data sources**:
  - none (governance layer is platform-internal), but must support provider metadata inputs
- **required specifications**:
  - spec policy (`specifications/spec_policy.yaml`)
  - provider contracts + consumer contracts + platform objects
  - domain specs scaffolding for domain variables/thresholds/categories
- **example dashboards**:
  - “Conformance status + contract coverage”
  - “Data provenance and reliability report”
- **acceptance criteria**:
  - conformance step passes on **every change** (run `python main.py --step conformance` locally until automated CI is present; then CI **and** local as needed)
  - examples/fixtures validate against their schemas

### Phase 3. Situational awareness layer

- **purpose**: Provide actor-specific, confidence-rated snapshots of “what is happening now” with clear provenance.
- **city actors served**: city administrators, ward officers, operations centers
- **capabilities**:
  - multi-layer maps (risks, incidents, assets) with warnings
  - summaries by ward/area and time window
  - “review queue” of decision packets requiring attention
- **required data sources**:
  - at least one real-time/batch signal per domain (sensors, incidents, weather, etc.)
- **required specifications**:
  - consumer contracts for situational dashboards
  - domain specs for interpretation categories and safety gates
- **example dashboards**:
  - air quality summary + hotspots (confidence-rated)
  - flood risk summary + incident overlay (verification-first)
- **acceptance criteria**:
  - dashboard payloads conform to consumer contracts
  - visible warnings for synthetic/low-confidence states are required and present

### Phase 4. Service delivery and grievance layer

- **purpose**: Turn signals into accountable service workflows (complaints, tickets, SLAs) with evidence trails.
- **city actors served**: ward officers, call centers, department engineers, citizens (where appropriate)
- **capabilities**:
  - complaint ingestion and clustering (privacy-aware)
  - service-status views and queues
  - audit trail linking complaints ↔ evidence ↔ actions
- **required data sources**:
  - complaint/ticket systems
  - service schedules (where applicable)
- **required specifications**:
  - provider contracts for complaint/ticket feeds
  - consumer contracts for grievance dashboards and task payloads
  - domain specs for service-level semantics (what “resolved” means)
- **example dashboards**:
  - “Ward grievance queue + clusters”
  - “Department SLA and backlog”
- **acceptance criteria**:
  - task/queue payloads are contract-defined
  - privacy and sensitivity constraints are enforced by consumer contracts

### Phase 5. Risk and resilience layer

- **purpose**: Provide early-warning and risk posture views (not automatic orders) for hazards and system stress.
- **city actors served**: disaster management, utilities, operations centers, planners
- **capabilities**:
  - risk scoring/category outputs with uncertainty
  - safety gates that block operational use when provenance/reliability is insufficient
  - scenario-based “what could happen next” summaries
- **required data sources**:
  - hazard drivers (weather/rainfall/heat), incidents, exposure layers, assets
- **required specifications**:
  - domain specs for thresholds/categories and blocked uses
  - decision packet consumer contracts (domain profiles)
- **example dashboards**:
  - “Flood risk level by ward + vulnerable assets”
  - “Heat risk exposure by neighborhood”
- **acceptance criteria**:
  - high-risk outputs include explicit blocked uses + field verification requirements
  - recommendations are downgraded to “verify” when gates fail

### Phase 6. Field operations layer

- **purpose**: Make decision support operationally actionable via verified tasks and structured outcomes.
- **city actors served**: field inspectors, ward engineers, emergency responders (under protocol)
- **capabilities**:
  - field verification task generation and assignment
  - checklists, evidence capture, and outcomes that feed back into models/playbooks
  - linking tasks ↔ decision packets ↔ assets/incidents
- **required data sources**:
  - workforce/task systems (or a minimal task registry)
  - mobile evidence capture metadata (photos/notes)
- **required specifications**:
  - consumer contract for field verification tasks
  - decision packet profiles referencing field verification requirements
- **example dashboards**:
  - “Field task list + map”
  - “Verification outcomes and follow-ups”
- **acceptance criteria**:
  - field tasks conform to a consumer contract
  - operational actions require verification unless separately authorized by protocol

### Phase 7. Domain modules

- **purpose**: Deliver domain-specific modules as contract packages: provider contracts + domain spec + consumer contracts.
- **city actors served**: domain departments (environment, stormwater, water utility, traffic, sanitation, assets)
- **capabilities**:
  - domain-specific normalization, features, models/rules, and decision packets
  - domain dashboards built strictly from consumer contracts
- **required data sources**:
  - domain-specific authoritative sources (plus open data where appropriate)
- **required specifications**:
  - provider contracts per source
  - domain specs (variables/units/thresholds/safety gates)
  - consumer contracts (dashboards, decision packets, tasks)
- **example dashboards**:
  - “Flood risk + drainage assets module”
  - “Property/building mismatch review module”
- **acceptance criteria**:
  - no domain-specific fields exist outside domain specs
  - providers/consumers pass conformance with examples and fixtures

### Phase 8. Planning and simulation layer

- **purpose**: Support policy and infrastructure planning (what-if) distinct from operations (nowcasting).
- **city actors served**: urban planners, finance, city administrators, researchers
- **capabilities**:
  - scenario parameters and simulation outputs with uncertainty
  - long-horizon forecasts and interventions comparison
  - impact evaluation (before/after, counterfactual-style)
- **required data sources**:
  - historical time series, network models, land use/zoning, demographic proxies (as allowed)
- **required specifications**:
  - consumer contracts for scenario outputs and simulation dashboards
  - domain specs defining safe interpretation (planning vs operations)
- **example dashboards**:
  - “Stormwater capacity upgrade scenarios”
  - “Traffic demand and corridor redesign what-if”
- **acceptance criteria**:
  - simulation outputs are clearly labeled “planning”
  - operational safeguards prevent planning outputs from being misused as real-time truth

### Phase 9. Public transparency and ecosystem layer

- **purpose**: Provide trust-building public views and enable third-party ecosystem integrations safely.
- **city actors served**: citizens, civil society, researchers, private ecosystem participants
- **capabilities**:
  - public dashboards and open-data exports (non-sensitive)
  - ecosystem APIs/SDKs with stable consumer contracts
  - transparency about provenance, confidence, and limitations
- **required data sources**:
  - curated outputs from domain modules with privacy controls
- **required specifications**:
  - public-facing consumer contracts with privacy constraints
  - blocked uses and warnings required by domain specs
- **example dashboards**:
  - “Public flood alerts (advisory) + caveats”
  - “Public air quality map (confidence-rated)”
- **acceptance criteria**:
  - no sensitive identifiers leak via public payloads
  - all public outputs include provenance/confidence cues

### Phase 10. Cross-domain city command view

- **purpose**: Provide a unified, cross-domain operational picture and prioritization across departments.
- **city actors served**: city command center, city administrators, department heads
- **capabilities**:
  - cross-domain risk posture and queues
  - shared prioritization and escalation workflows
  - cross-domain decision packets and dependencies (e.g., flood ↔ traffic ↔ emergency response)
- **required data sources**:
  - harmonized domain dashboards/decision packets
  - shared incident/task registries
- **required specifications**:
  - cross-domain consumer contracts (command view payload)
  - consistent provenance and reliability semantics across domains
- **example dashboards**:
  - “City command: top risks + queues across domains”
  - “Escalations and blockers”
- **acceptance criteria**:
  - command view is purely contract-driven (no ad-hoc merges)
  - explicit blocked uses for high-risk recommendations

## Recommended Domain Sequence

1. Air quality
2. Flood and stormwater
3. Property and buildings
4. Water operations
5. Traffic and mobility
6. Sanitation and solid waste
7. Public assets and maintenance
8. Heat and public health risk
9. Emergency response
10. Planning and simulation

## Use case maturity stages

Each use case should move through these stages:

1. Concept

2. Actor and decision definition

3. Data-source discovery

4. Domain specification

5. Provider contracts

6. Platform object mapping

7. Consumer contracts

8. Examples and fixtures

9. Conformance checks

10. Connector implementation

11. Normalization to canonical platform objects

12. Feature generation

13. Model/rule logic where applicable

14. Dashboard/API/SDK implementation

15. Decision packet

16. Review workflow

17. Field validation / outcome feedback

AirOS is **specs-first**. Stages 4–9 are not optional: connectors, dashboards, APIs, SDK methods, reports, and decision packets must be backed by specifications and must pass conformance before implementation is considered complete.

## Current implemented use cases

### Air Quality
Status: Reference application implemented.
Current capabilities:
- H3 grid
- OSM static features
- OpenAQ PM2.5 connector with fallback
- Open-Meteo weather connector
- Optional NASA FIRMS fire connector
- Feature store
- Baseline forecast model
- Decision packets
- Review dashboard
- Conformance audit

### Crowd
Status: Early example.
Current capabilities:
- Camera people-count provider contract
- Edge publisher
- JSONL ingestion
- Observation store integration
- Dashboard tab

## Near-term target use cases

### Flood Risk
Target actors:
- Disaster management cell
- Stormwater department
- Ward officers
- Emergency responders

Operational questions:
- Which areas are at risk of flooding in the next few hours?
- Which drains, lakes, underpasses, and low-lying roads need inspection?
- Where should field teams be deployed?
- Which alerts should be issued?

Likely data sources:
- Rainfall forecasts
- IMD or open weather feeds
- Open-Meteo precipitation
- DEM/elevation data
- OSM drains, water bodies, roads
- Historical flood points
- Citizen reports
- Sensor feeds if available

Initial dashboard:
- Flood risk map
- Rainfall intensity
- Low-lying areas
- Drainage assets
- Field verification queue
- Ward-level risk summary

### Traffic and Mobility
Target actors:
- Traffic police
- Transport department
- City operations center
- Urban planners

Operational questions:
- Where is congestion building up?
- Which corridors need intervention?
- Which junctions are high-risk or overloaded?
- How do events, weather, and road works affect mobility?

Likely data sources:
- OSM road network
- GTFS public transit feeds where available
- TomTom/HERE/Mapbox APIs where licensed
- Public traffic camera counts
- Event data
- Road closure data
- Weather data

Initial dashboard:
- Congestion corridors
- Junction hotspots
- Travel-time reliability
- Incident/event overlay
- Recommended interventions

### Property and Buildings — phased delivery (open data first)

**Safety (all phases):** Open-data and EO outputs are **change candidates and review prompts** only. They must not be read as legal property records, permit violations, tax liabilities, ownership facts, or enforcement evidence. Privacy, provenance, blocked-use, and human-review safeguards are **not** relaxed when later-stage feeds are added.

#### Phase 1 — Open-data built-environment change detection

**Product framing:** *Built Environment Change Detection* using open or externally obtainable data (OSM, licensed open footprints, satellite / Sentinel–Landsat-style change signals, wards, roads, settlement context). Demonstrate value **before** assuming access to municipal registry, permit, tax, or cadastral systems.

Target actors:
- Ward engineers and field inspection teams (non-enforcement context gathering)
- Town planning / urban analytics (spatial prioritization only)
- Disaster management (exposure change awareness where relevant)
- Urban analysts building public-good indicators

Primary operational question:
- **Where does the built environment appear to have changed recently, and which areas may need field review?**

Supported questions (Phase 1):
- Which wards show **built-up area growth** over the **last 6 months or 1 year** (subject to configured time windows and data availability)?
- Where are **new building / construction candidates** visible from **open data only**?
- Which areas need **field verification** given stacked signals and uncertainty?
- Where is open data **coverage weak or stale**, or **license-constrained**?
- Which locations should be **prioritized later** for municipal data integration (readiness signal—not a system demand)?

Explicitly **not** supported in Phase 1:
- Under-assessment or revenue-gap claims
- Tax demand or reassessment generation from open signals
- Permit violation or non-compliance verdicts from remote sensing alone
- Demolition, penalty, or enforcement recommendations from EO/footprints
- Owner-level analysis or ownership facts as default outputs
- Automated non-compliance detection without authoritative municipal process

Phase 1 data sources (see `specifications/domain_specs/property_buildings.v1.yaml` → `open_data_inputs`):
- OSM building footprints
- Open building footprint datasets where license permits derivatives
- Satellite-derived change detection and **Sentinel/Landsat-style** indices or external derived products
- Ward / administrative base layers
- Roads and settlement context (e.g. **`provider_road_network_feed`**)
- **Manually uploaded field verification results** when available under a dedicated provider contract and privacy review

Initial dashboard / consumer direction (Phase 1):
- Built-up **change candidates** and **new construction candidate areas**
- **Footprint growth** / delta summaries with uncertainty
- **High-change wards** (or other spatial units) for triage
- **Field verification queue** with provenance and confidence warnings

#### Phase 2 — Field verification loop

Close the loop between open-signal triage and **structured field outcomes** (tasks, visit notes, photo metadata, tickets) under provider contracts and `field_verification_task` consumer shape. Outputs remain **review evidence**, not legal or tax determinations.

#### Phase 3 — Authorized municipal integration *readiness*

Identify which wards or workflows are **candidates for deeper municipal pipes** (access agreements, DPIA / privacy review, operational owners). AirOS documents readiness; it does **not** auto-onboard government systems.

#### Phase 4 — Registry / permit / tax comparison (authorized officials only)

Where cities authorize feeds, support **human-in-the-loop** comparison and reconciliation for **designated roles** (e.g. planning, revenue)—still gated by `blocked_uses`, provenance, and field verification. No automatic non-compliance or reassessment from AirOS alone.

#### Phase 5 — Official workflow integration (outside automatic AirOS enforcement)

Integrate with municipal case systems or revenue workflows **only** through explicit product and legal design. **Automatic enforcement, tax demands, or permit guilt from AirOS are out of scope** for the platform’s default posture; official decisions remain with the authority.

#### Municipal contracts (later-stage; not Phase 1 defaults)

**Contracts remain** (`property_registry_feed`, `building_permit_feed`, future cadastre): they are **valid later-stage, authorized-integration** specifications—not removed, not required for Phase 1, and not positioned as default public narratives.

Later-stage inputs (examples):
- Municipal property registry
- Building permit system
- Property tax assessment data
- Cadastral / parcel system
- Land-use / zoning **authority** datasets (distinct from **public** open zoning layers used in Phase 1)

Later-stage decisions must still satisfy privacy, provenance, `blocked_uses`, `required_human_review`, and `field_verification_requirements` in the domain spec—**no** weakening of safeguards and **no** enforcement/tax automation added by specification fiat.

### Water
Target actors:
- Water utility
- Ward engineers
- Operations teams
- City administrators

Operational questions:
- Which areas are under-served?
- Where are complaints clustering?
- Which assets are likely failing?
- Where are supply interruptions likely?
- Which valves, tanks, and pipes need inspection?

Likely data sources:
- Water network assets
- Tank levels
- Flow meters
- Pressure sensors
- Complaint systems
- Supply schedules
- Road cutting permissions
- Weather and demand proxies

Initial dashboard:
- Supply risk map
- Complaint clusters
- Asset reliability
- Pressure/flow anomalies
- Field task queue

## Development sequence (required for any new use case)

When starting a new use case, the minimum acceptable sequence is:

1. **Define** the actor and the decision to support.
2. **Discover data sources** and document access method, license, coverage, update frequency, and reliability risks.
3. **Define or update the domain specification**: variables, units, thresholds, categories, safety gates, blocked uses, and review prompts.
4. **Specify provider contracts** for each required data source.
5. **Map provider data to canonical platform objects** such as Entity, Observation, Feature, Event, Asset, SourceReliability, DecisionPacket, or FieldTask.
6. **Define consumer contracts** for dashboard payloads, decision packets, API/SDK responses, reports, and field tasks.
7. **Add examples and fixtures** for provider inputs and consumer outputs.
8. **Register specifications** in the specifications manifest.
9. **Implement or extend conformance checks**.
10. **Only then implement** connectors, pipelines, models/rules, dashboards, APIs, or SDK methods.
11. **Run conformance** and attach evidence to the PR.
12. **Add human review and field verification loops** where the output may influence operational action, enforcement, emergency response, or citizen-facing service delivery.

This keeps AirOS interoperable across domains and prevents ad-hoc payloads from becoming de facto contracts.

## Why this domain sequence?

The recommended order optimizes for:

- **reuse of shared primitives** (boundaries/H3/OSM, provenance, reliability, conformance, decision packets)
- **operational safety** (high-risk domains early, with verification-first patterns baked in)
- **data availability** (weather/open sources first, then heavier enterprise/registry integrations)

Air quality is first as the reference implementation. Flood/stormwater comes next because it reuses weather + spatial primitives and benefits from verification-first workflows. **Property/buildings** is reframed as **open-data built-environment intelligence** (footprints, EO change, wards, public land use, roads)—field-review triage without assuming municipal registry or permit integration. Water operations remain asset-centric where utilities expose data. Traffic, sanitation, public assets, heat, emergency response, and planning/simulation then build on the same platform layers with increasing cross-domain coupling.