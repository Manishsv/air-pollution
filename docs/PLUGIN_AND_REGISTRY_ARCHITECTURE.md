# Plugin and registry architecture (AirOS)

AirOS should be deployable as **AirOS Core** without hard-wiring specific data providers or specific applications/consumers into the core runtime. Providers, applications, and network transports should **plug in** through **specifications**, **contracts**, **registries**, and **conformance** so new integrations can be added without modifying core modules.

This is a **design / documentation** note. It defines **plugin declarations** and proposes registry files **without implementing them**.

## 0) Design principles

- **Specs-first**: contracts are the handshake. New providers/applications must start with contracts and examples under `specifications/` and `specifications/manifest.json`.
- **Core is stable; plugins are replaceable**: avoid hard-coded assumptions in core about particular providers (OpenAQ/Open-Meteo/OSM/FIRMS) or particular consumers (one dashboard).
- **Domain semantics live outside core**: domain specs + domain applications + agency workflows (and human review) own meaning; core provides shared scaffolding.
- **Discoverability**: dashboards and application surfaces should be discoverable by registry/metadata, not by manual wiring for every new domain.
- **Conformance as a deploy gate**: conformance validates that a plugin’s contracts + examples are consistent before a deployment enables it.
- **Federation contracts are protocol-like**: network contracts (envelopes/receipts) stay domain-agnostic; transport adapters are swappable.

---

## 1) AirOS Core (what should be deployable independently)

AirOS Core is the reusable platform surface. It includes:

- **Specifications + manifest**: `specifications/` and `specifications/manifest.json`
- **Conformance engine**: `python main.py --step conformance` (schema validity + manifest hygiene + example validation + runtime artifact checks where applicable)
- **Canonical platform objects**: normalized Observation/Entity/Feature/Event + provenance/reliability patterns
- **Data stores / artifacts**: deployment-scoped stores (local or service-backed); `data/` contains generated artifacts (not source of truth)
- **Provider connector framework**: connector interface conventions and loading (contract-driven ingestion)
- **Processing / feature framework**: reusable feature builders and processing patterns (`urban_platform/processing/...`)
- **Application payload framework**: conventions for contract-shaped payload builders (`urban_platform/applications/...`)
- **SDK/API**: contract-shaped outputs exposed to consumers (runtime surfaces are validated against consumer contracts where applicable)
- **Network contracts**: `specifications/network_contracts/` (e.g. `message_envelope.v1`, `delivery_receipt.v1`)
- **AI supervisor tooling**: `tools/ai_dev_supervisor/` (local governance + conformance evidence + maturity checklists)
- **Dashboard shell (optional)**: a presentation shell that discovers registered panels; the UI must not embed domain logic

Core **must not** embed municipal/city-specific assumptions; deployment context belongs in **profiles** (e.g. city profile template) and registries.

---

## 2) Provider plugins (data providers)

A **provider plugin** integrates an external data source into AirOS in a replaceable way. It should declare:

- **`provider_id`**: stable identifier (e.g. `openaq_v3`, `open_meteo`, `osmnx_osm_extract`, `nasa_firms`)
- **`domain_id`**: which domain(s) the feed is relevant to (e.g. `air_quality`, `flood_risk`)
- **`provider_contract`**: manifest artifact key for the provider contract (e.g. `provider_air_quality_observation_feed`)
- **`connector_module`**: import path to connector implementation (e.g. `urban_platform.connectors.air_quality.openaq_v3_ingest`)
- **`input_method`**: `api | file | email | event | manual_upload`
- **`output_platform_object_types`**: which canonical objects are produced (Observation/Event/Feature/Asset)
- **`provenance_behavior`**: how provenance fields are populated (source attribution, synthetic flags, interpolation markers)
- **`quality_flags`**: expected quality flag vocabulary and mapping strategy (pass-through vs normalized)
- **`examples_fixtures`**: example JSON under `specifications/examples/...` tied to the provider contract
- **`conformance_requirements`**: required checks (schema validity + example validation; connector tests where implemented)

**Rule of thumb:** if a provider changes, the platform should be able to swap plugins while preserving canonical object shapes and downstream consumer contracts.

---

## 3) Application / data consumer plugins

An **application plugin** produces contract-shaped outputs (dashboards, packets, tasks, API responses) for a domain. It should declare:

- **`application_id`**: stable identifier (e.g. `air_quality_review_console`, `flood_risk_dashboard_payload`)
- **`domain_id`**
- **`consumer_contracts`**: list of manifest keys for consumer contracts it emits/relies on
- **`payload_builders`**: import paths for payload builder modules/functions (e.g. `urban_platform.applications.<domain>.dashboard_payload`)
- **`dashboard_component`** (optional): panel module for the review dashboard shell (presentation only)
- **`sdk_api_outputs_consumed`**: which SDK/API outputs the UI or downstream uses (contract-shaped)
- **`packet_types`**: decision/review packet contract names (or profiles) emitted
- **`field_task_types`**: field task consumer contracts emitted/consumed
- **`safety_gates_and_blocked_uses`**: references to domain spec sections; application must surface safety gates + review prompts
- **`examples_fixtures`**: examples under `specifications/examples/<domain>/...` for emitted payloads
- **`conformance_requirements`**: contract validation gates for emitted payloads and examples

**Constraint:** domain semantics and “what it means” live in **domain specs** and **domain application code**, not in dashboards and not in a network plane.

---

## 4) Network adapter plugins (transport adapters)

A **network adapter plugin** carries **network contracts** over a transport. It should declare:

- **`adapter_id`**
- **`supported_transport`**: `email | api | webhook | sftp | event_bus`
- **`supported_network_contracts`**: e.g. `network_message_envelope_v1`, `network_delivery_receipt_v1`
- **`delivery_receipt_support`**: which receipt types/statuses are supported end-to-end
- **`authentication_method`**: e.g. signed envelope, shared secret reference, OAuth reference, manual MoU gate (no inline secrets)
- **`audit_behavior`**: how message ids map to audit logs; retention posture
- **`retry_behavior`**: backoff, dead-letter handling, idempotency strategy

**Email adapter (Phase 1):** low-frequency coordination carrier; not suitable for high-frequency streams or sensitive PII without stronger controls. Email is not “the network layer”; it is a carrier for the same envelope/receipt shapes.

---

## 5) Registries needed (proposed; do not implement here)

To make Core deployable independently, propose registry files (deployment-scoped and/or core-shipped defaults):

- `provider_registry.yaml`
- `application_registry.yaml`
- `network_adapter_registry.yaml`
- `domain_registry.yaml`
- `deployment_profile.yaml`

These registries should reference **manifest artifact keys** (not raw schema file paths) and **module import paths** (for implementations) without forcing core to hard-wire lists.

### Clarification: core vs deployment-scoped registries

Registries can be **core/default registries** shipped with AirOS Core and/or **deployment-scoped registries** maintained by forward deployment teams.

- A deployment may enable only the **subset** of providers, applications, domains, and network adapters relevant to that **city/agency/state**.
- Deployment registries may reference **private/internal providers** (and private endpoints or credentials references) without committing sensitive details into the **public** AirOS repository.

---

## 6) Lifecycle (how plugins are added)

### Add a new provider

Provider contract → example fixture → connector implementation → registry entry → conformance → tests

Minimum gates:

- Provider schema exists and is registered in `specifications/manifest.json`
- Example JSON validates against the provider schema
- Connector has at least a smoke test or fixture-based ingestion test where appropriate
- Conformance passes

### Add a new application/consumer

Domain spec → consumer contract → payload builder → dashboard/API consumer → registry entry → conformance → tests

Minimum gates:

- Domain spec exists (`specifications/domain_specs/<domain>.v1.yaml`)
- Consumer schemas exist and are registered
- Examples validate
- Payload builder tests pass
- Conformance passes

---

## 7) Relationship to the current repo (mapping)

This repository already contains several “proto-plugins,” but they are not yet declared via registries.

### Domains / applications

- **Air quality (reference app)**: `main.py` delegates into legacy `src/` pipeline; consumer contracts and decision packet profiles exist; migration debt remains (`src/` → `urban_platform/`).
- **Flood (read-only vertical slice)**: provider + consumer contracts, examples, `urban_platform` processing + applications + dashboard panel + tests; maturity checklist YAML exists.
- **Property/buildings (open-data-first)**: open-data oriented contracts/examples + processing/app payloads + panel + tests; maturity checklist YAML exists.

### Providers

- **OpenAQ / CPCB-like** (air quality), **Open-Meteo** (weather), **OSM** (static features), **FIRMS** (fires) exist as provider surfaces in code/specs today; they should become provider plugins declared by registry.

### Consumers / UI

- `review_dashboard/` is a presentation surface; panels should be discoverable/registered and must not contain domain risk logic.

### Federation / network

- Network contracts now exist under `specifications/network_contracts/`:
  - `network_message_envelope_v1` (message envelope)
  - `network_delivery_receipt_v1` (delivery/ack receipt)
  These are protocol-like and transport-agnostic. Adapters (email/api/bus) are future plugins.

---

## 8) Suggested next bounded implementation tasks (incremental path)

1. **Define registries as specs-like documents** (YAML schemas + examples) and add conformance checks for registry hygiene (no runtime loading yet).  
2. **Add a minimal provider registry** for one existing provider (e.g. OpenAQ) and one existing domain (air quality) and wire the supervisor to report registry completeness (still no runtime loading).  
3. **Add a minimal application registry** for one existing application payload (e.g. flood dashboard payload) and ensure dashboard panels can be enumerated from metadata (still manual wiring allowed as fallback).  
4. **Introduce a dashboard shell discovery mechanism** (registry-driven panel list) while keeping current panels working; no domain logic moves into UI.  
5. **Add a placeholder network adapter registry** and ensure envelope/receipt artifacts remain transport-agnostic and validated by conformance before any adapter code is written.

---

## Cross-links

- Specs-first and conformance: `AGENTS.md`, `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`, `specifications/README.md`
- Federation and Network Layer: `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`, `docs/AGENCY_NODE_MODEL.md`, `docs/CROSS_AGENCY_COORDINATION_LAYER.md`
- Architecture diagrams: `docs/AIR_OS_ARCHITECTURE_OVERVIEW.md`
