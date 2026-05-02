## Specs-first rule

AirOS follows a specs-first architecture.

All development must start from specifications. Code must conform to platform specs and domain specs.

Before implementing any connector, pipeline, model output, dashboard, API, SDK method, or decision-support workflow, the agent must check whether the required specification exists under `specifications/`.

If the required specification does not exist, the agent must first propose or add the specification before writing application code.

## Repository architecture (brief)

- **Contracts + code layout (`src/` vs `urban_platform/`)**: [`../specifications/ARCHITECTURE_NOTE.md`](../specifications/ARCHITECTURE_NOTE.md) — section *Repository code layout* (ownership table, delegation chain, migration principles, suggested AQ migration sequence).
- Consolidated review (layout, conformance, forward deployment, tooling): [`docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`](reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md).
- **`main.py`** → **`urban_platform.applications.air_pollution.pipeline`** → delegates to **`src.pipeline`** today. **`src/`** = **legacy AQ MVP** only. **New domains and shared logic** → **`urban_platform/`** only (see root **`AGENTS.md`** *Code layout*).
- **Dashboards** must use **`urban_platform/sdk`**; consumer payloads live under **`urban_platform/applications/<domain>/`**, not ad hoc in Streamlit.
- **Deployment & federation (node-first, not one monolithic city instance):** [`FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md), [`AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md), [`CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md) — Network Layer is **contract-aware** and **domain-agnostic**; domain meaning stays in specs/applications. Root **`AGENTS.md`** has agent rules for federation.

## Mandatory conformance

Conformance is mandatory for both:

1. Data providers
   - external feeds
   - file uploads
   - sensors
   - edge devices
   - government systems
   - public/open data sources

2. Data consumers
   - dashboards
   - SDK responses
   - APIs
   - decision packets
   - analytics outputs
   - downstream applications

No provider or consumer should be considered complete unless it passes conformance validation.

## Specification families

Every use case should consider four specification families:

1. Provider contracts
   Define the raw or source-specific payloads accepted from external providers.

2. Platform object contracts
   Define normalized internal objects used across domains, such as Entity, Observation, Feature, Event, Asset, SourceReliability, DecisionPacket, and Action.

3. Domain specifications
   Define domain-specific extensions, profiles, variables, thresholds, interpretation rules, and decision semantics.

4. Consumer contracts
   Define what dashboards, APIs, SDKs, reports, decision packets, and downstream apps are allowed to consume.

## Required development sequence

When adding or changing a capability, follow this order:

1. Identify the use case, actor, and decision.
2. Identify required provider, platform, domain, and consumer specs.
3. Add or update specs under `specifications/`.
4. Register specs in the specification manifest.
5. Add or update conformance checks.
6. Implement connector or processing code.
7. Normalize data to platform objects.
8. Validate provider inputs and consumer outputs.
9. Update dashboard/API/SDK only after specs exist.
10. Run conformance audit.
11. Attach conformance evidence to the PR.

## Non-negotiable rules

- Do not implement a new data source without a provider contract.
- Do not create a new dashboard payload without a consumer contract.
- Do not add a domain-specific field without defining it in a domain spec or profile.
- Do not bypass platform object normalization.
- Do not treat synthetic or low-confidence data as operational truth.
- Do not merge a change if conformance fails.

## Urban governance & AI CoE context

Before **domain sequencing**, **integration assumptions**, or **substantial implementation**, read (in addition to this file and `AGENTS.md` at repo root if present):

- [`URBAN_CONTEXT_INDIA.md`](URBAN_CONTEXT_INDIA.md) — Indian urban fragmentation, uneven data maturity, short institutional memory, and why **open-data-first** and **progressive adoption** matter.
- [`AI_COE_OPERATING_STRATEGY.md`](AI_COE_OPERATING_STRATEGY.md) — AI CoE role, core vs forward deployment, safe agentic development, and how field learnings feed the platform.
- [`USE_CASE_ROADMAP.md`](USE_CASE_ROADMAP.md) — phased capabilities and city-specific prioritization.
- [`../specifications/spec_policy.yaml`](../specifications/spec_policy.yaml) — machine-readable policy hooks.

**Working assumptions:** agencies are fragmented; data access is uneven; privileged municipal integrations may arrive **late**; cities vary in size and capacity; public leadership rotates; **specs and conformance** preserve continuity; forward deployment **configures** AirOS locally without forking safety rules.