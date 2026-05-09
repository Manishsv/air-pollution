# AirOS interoperability model

**Canonical references (current):**

- **Product model**: [`docs/PRODUCT_MODEL.md`](PRODUCT_MODEL.md)
- **Repo migration plan**: [`docs/REPO_RESTRUCTURING_PLAN.md`](REPO_RESTRUCTURING_PLAN.md)

This document is retained for background/design context.

This document explains how AirOS enables **interoperability** across data providers, domain applications, deployments, and (in future) separate agency nodes—using **shared contracts**, **registries**, **reference catalogs**, and **conformance**. It complements [`docs/BEGINNER_DEVELOPER_GUIDE.md`](BEGINNER_DEVELOPER_GUIDE.md) and [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md).

---

## 1) Purpose

**AirOS interoperability** means that different data sources, applications, agencies, and deployment workspaces can work together because they share **known shapes** for inputs and outputs, **canonical platform concepts**, **versionable reference codes**, and **automated validation**—instead of ad-hoc CSV columns and one-off APIs.

Nothing here replaces legal authority, procurement, or operational governance; AirOS supplies **technical contracts** and **review support**.

---

## 2) Core idea (simple model)

Use this mental model everywhere:

1. **Provider data** enters through **provider contracts** (allowed incoming shape).
2. AirOS **normalizes** shared concepts through **platform objects** (canonical records and fields).
3. **Applications** produce **consumer contract** outputs (review-ready payloads for humans and UIs).
4. **Deployments** **enable** which providers and applications are active via **registries** + `deployment_profile.yaml`.
5. **Reference catalogs** keep **codes** (cities, programs, periods) aligned across cities and state.
6. **Network contracts** (plus policy and future transport) support **cross-agency exchange**—without embedding domain semantics in the network plane.

---

## 3) Interoperability layers

For each layer: **what it is**, **who uses it**, **where it lives**, **example artifact**.

### Provider contracts

| | |
|--|--|
| **What** | JSON Schema (and docs) defining what an external **provider feed** is allowed to send into AirOS normalization. |
| **Who** | Connector authors, data integrators, program offices publishing intake rules. |
| **Where** | `specifications/provider_contracts/` |
| **Example** | Flood provider fixtures and contracts used with `deployments/examples/flood_local_demo/` (e.g. rainfall / incident / drainage feeds under `specifications/examples/flood/`). |

### Platform objects

| | |
|--|--|
| **What** | Canonical **shared record types** (observations, entities, features, events, assets, …) used across domains. |
| **Who** | Application authors, processing authors, reviewers relying on comparable fields. |
| **Where** | `specifications/platform_objects/` |
| **Example** | `reference_catalog.v1.schema.json` (catalog “container” shape); other platform objects as registered in [`specifications/manifest.json`](../specifications/manifest.json). |

### Reference catalogs

| | |
|--|--|
| **What** | Published **code lists** (administrative units, programs, reporting periods) so submissions use the same identifiers. |
| **Who** | State publishers; city integrators declaring `reference_data_versions` on submissions. |
| **Where** | Schema: `specifications/platform_objects/reference_catalog.v1.schema.json`; demo fixtures: `specifications/examples/reference_data/*.sample.json`. |
| **Example** | `administrative_units.sample.json`, `program_catalog.sample.json`, `reporting_periods.sample.json`. |

### Domain specs

| | |
|--|--|
| **What** | Domain **semantics**: variables, units, thresholds, safety language, blocked uses—**not** raw JSON shapes alone. |
| **Who** | Domain owners, conformance authors, application builders enforcing review posture. |
| **Where** | `specifications/domain_specs/` |
| **Example** | `program_reporting.v1.yaml`, domain README under same folder. |

### Consumer contracts

| | |
|--|--|
| **What** | JSON Schema for **outputs** reviewers and dashboards consume (dashboard payloads, decision packets, review packets, tasks). |
| **Who** | Application developers, dashboard developers (as consumers of payloads). |
| **Where** | `specifications/consumer_contracts/` |
| **Example** | `property_building_dashboard.v1.schema.json`, `fund_release_review_packet.v1.schema.json`, flood consumer payloads referenced by flood demos. |

### Deployment registries

| | |
|--|--|
| **What** | YAML that **declares** which providers/applications/network adapters are in scope for a deployment (enablement + wiring to manifest artifact keys). |
| **Who** | Deployment engineers, forward deployment teams. |
| **Where** | Example deployments: `deployments/examples/<name>/` (`deployment_profile.yaml`, `provider_registry.yaml`, `application_registry.yaml`, optional `network_adapter_registry.yaml`, optional policy stubs). |
| **Example** | `deployments/examples/flood_local_demo/deployment_profile.yaml`. |

### Application “plugins” (domain applications)

| | |
|--|--|
| **What** | In-repo **domain applications**: builders that map normalized data → **consumer-shaped** outputs. This repository uses **explicit allowlists** for runnable POC paths—**not** unrestricted dynamic plugin loading at runtime. |
| **Who** | Application developers. |
| **Where** | `urban_platform/applications/<domain>/` |
| **Example** | `urban_platform/applications/program_reporting/review_packets.py`, flood dashboard/packet builders under `urban_platform/applications/flood/`. |

### Dashboard panels

| | |
|--|--|
| **What** | Streamlit (or other) **presentation** of contract-shaped payloads—**no new domain rules** in UI. |
| **Who** | UI engineers, demo owners. |
| **Where** | `review_dashboard/components/` (`app.py` wires tabs). |
| **Example** | `program_reporting_panel.py`, `flood_panel.py`, `property_buildings_panel.py`. |

### Network contracts

| | |
|--|--|
| **What** | Schemas for **message envelopes** and coordination—**policy/transport plane**, not domain reasoning. |
| **Who** | Integrators planning federation; must align with [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md). |
| **Where** | `specifications/network_contracts/` |
| **Example** | Network contract files as registered in the manifest (implement and adopt only when your deployment needs them). |

### Future: participant directory / data-sharing policy

| | |
|--|--|
| **What** | **Future** cross-agency discovery and policy artifacts (who participates, what may be shared, under which roles). **Not** a fully implemented production trust layer in this repository’s Phase 1 demos. |
| **Who** | State/city program offices, legal/security stakeholders. |
| **Where** | Documented in federation and coordination docs; concrete filenames evolve with specs. |
| **Example** | See [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md), [`docs/AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md). |

---

## 4) Developer perspective (roles)

### Data provider developer

Builds against:

- Provider **contract** (schema) + **examples** under `specifications/examples/`
- **Registry** entry in `provider_registry.yaml` for the deployment
- Optional **connector** under `urban_platform/connectors/…` normalizing to platform objects

### Application developer

Builds against:

- **Consumer contract** + validated **examples**
- **Builder** under `urban_platform/applications/<domain>/`
- **Tests** asserting schema conformance

### Dashboard developer

- Consumes **consumer-shaped** payloads only
- Implements `review_dashboard/components/…` (labels, safety, expanders)
- **Does not** embed domain decision logic in Streamlit

### Deployment engineer

- `deployment_profile.yaml`
- `provider_registry.yaml`, `application_registry.yaml`
- Optional `network_adapter_registry.yaml`, `data_sharing_policy.yaml` (when present for a workspace—often placeholder in examples)

### State / agency integrator

- **Reference catalogs** and **program specs** (`specifications/program_specs/…`)
- **Future** participant directory and network policy—plan in federation docs; do not assume runtime features exist until contracts and operations are in place

---

## 5) Current examples (mapped to layers)

### Flood (`flood_local_demo`)

| Layer | How it shows up |
|-------|-----------------|
| Provider contracts + fixtures | Rainfall, flood incident, drainage feeds under `specifications/examples/flood/` |
| Consumer outputs | Flood dashboard payload, decision packets, field tasks (schemas under `specifications/consumer_contracts/`) |
| Deployment | `deployments/examples/flood_local_demo/` |
| Dashboard | Flood tab + related review UI |

### Program reporting (`program_reporting_state_demo`)

| Layer | How it shows up |
|-------|-----------------|
| Reference catalogs | Demo catalogs under `specifications/examples/reference_data/` |
| Program spec | `specifications/program_specs/stormwater_resilience_grant_2026/program_spec.yaml` |
| Consumer contracts | `city_program_submission`, `fund_release_review_packet` |
| Application | `urban_platform/applications/program_reporting/` |
| Deployment | `deployments/examples/program_reporting_state_demo/` |
| Dashboard | Program Reporting tab (read-only outputs) |

### Property & buildings (review dashboard)

| Layer | How it shows up |
|-------|-----------------|
| Provider contracts + fixtures | Property registry, footprints, permits, land use under `specifications/examples/property_buildings/` |
| Consumer outputs | Property/buildings dashboard + review packet contracts |
| Application | `urban_platform/applications/property_buildings/` |
| Dashboard | Property & Buildings panel (`review_dashboard/components/property_buildings_panel.py`) |

---

## 6) Stable vs evolving surfaces

### Relatively stable (treat as integration anchors)

- **`specifications/manifest.json` artifact keys** and example wiring
- **Provider / consumer JSON Schema** pattern and example validation
- **`python main.py --step conformance`** and CI/supervisor governance
- **`tools/airos_cli.py deployment validate`** (config-only checks)
- **Docker image entrypoints** for doctor / conformance / deployment demos (see [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md))

### Evolving (capabilities may exist as docs or partial hooks)

- **Full runtime plugin loading** from arbitrary registries
- **Dynamic provider execution** for all providers without allowlists
- **Network adapters** beyond demo declarations
- **Participant directory** and production-grade **trust/identity**
- **Reference catalog** pull/cache/TTL/signing
- **Program spec** distribution/adoption automation at scale

When in doubt, trust **contracts + conformance + explicit demo allowlists** over assumed runtime behavior.

---

## 7) What belongs in Core vs domains

### Core (platform spine)

- Specifications, **manifest**, **conformance**, audit posture
- **Platform objects**, registry contract files, deployment validation tooling
- **CLI** (`tools/airos_cli.py`), **Docker** packaging
- Review dashboard **shell** and shared helpers (`review_dashboard/ui_shell.py`, design-system CSS, etc.)

### Domains / “plugins” (vertical slices)

- Provider-specific mapping and connectors
- Domain rules and application **builders**
- Dashboard **panels** (presentation)
- **Deployment examples** that demonstrate a slice end-to-end

---

## 8) Interoperability rules (practical)

- **Do not bypass contracts.** Normalize into platform objects; emit consumer-shaped outputs.
- **Do not invent private payload shapes** without schemas and examples.
- **Register** new artifacts in **`specifications/manifest.json`** when introducing schemas/examples.
- **Always add examples** (synthetic) for new contracts.
- **Use reference catalogs** for shared codes where the domain requires alignment (e.g. program reporting Phase 1).
- **Keep domain meaning out of the Network Layer**—network contracts carry envelopes and policy hooks, not PM thresholds or finance rules.
- **Keep domain logic out of dashboard UI**—UI renders payloads and safety text.
- **Keep raw technical details** behind expanders for officials.
- **Never encode automatic government action** unless legally authorized and explicitly governed outside this repo’s demos—demos are **review support**.

---

## 9) Future cross-agency model (high level)

**State AirOS (illustrative)** may publish:

- Program specifications and **reference catalogs**
- **Participant directory** and **data-sharing policies** (once specified and operationally adopted)

**City AirOS** may adopt/pull:

- The same program specs and catalog versions (mechanism: future distribution story—**not** claimed as fully automated here)

**City AirOS** may submit:

- **Contract-shaped** reports (consumer payloads)
- A **message envelope** per **network contracts** (when enabled)
- Expect **delivery receipts** and audit trails in a mature deployment

This repository today demonstrates **contracts, conformance, and fixture demos**—not a complete national federation rollout.

---

## 10) Relationship to other guides

| Doc | Role |
|-----|------|
| [`docs/BEGINNER_DEVELOPER_GUIDE.md`](BEGINNER_DEVELOPER_GUIDE.md) | Web-dev–friendly mental model + templates |
| [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) | Specs-first repo layout and extension sequence |
| [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md) | Registry mental model and boundaries |
| [`docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md`](PROGRAM_REPORTING_AND_FUND_RELEASE.md) | Program reporting Phase 1 design + demo |
| [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md) | Target multi-container posture |
| `docs/PRODUCTION_READINESS_CHECKLIST.md` | *Not present in this repository at time of writing. If the project adds it, link it here and in [`README.md`](../README.md).* |
