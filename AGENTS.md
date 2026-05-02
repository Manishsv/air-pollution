## AirOS coding-agent rules (specs-first, mandatory conformance)

AirOS is a **specs-first** multi-domain urban intelligence platform.

**All development must start from specifications** under `specifications/`. Provider inputs, canonical platform objects, domain semantics, and consumer outputs **must conform** to those specifications.

If the relevant spec does not exist yet, **stop implementation and add/update the spec first**.

### Non-negotiable rules

- **Do not implement a connector without a provider contract.**
- **Do not implement a dashboard payload without a consumer contract.**
- **Do not add domain-specific fields without a domain specification.**
- **Do not bypass canonical platform objects.**
- **Do not weaken provenance, reliability, conformance, or human-review safeguards.**
- **Do not treat synthetic or low-confidence data as operational truth.**
- **Run conformance before considering the task complete.**

### Specs to check before writing code

AirOS uses four spec families. Every new capability must map to these:

- **Provider contracts** (`specifications/provider_contracts/`): what external providers are allowed to send.
- **Platform objects** (`specifications/platform_objects/`): canonical internal objects shared across domains (e.g., `Observation`, `Entity`, `Feature`, `Event`, `Asset`, `DecisionPacket`).
- **Domain specifications** (`specifications/domain_specs/`): domain semantics (variables, units, thresholds, categories, safety gates, review prompts).
- **Consumer contracts** (`specifications/consumer_contracts/`): what dashboards/APIs/SDKs/reports/decision packets are allowed to consume.

### Required development sequence (for any new use case)

1. **Define**: use case → actor → decision to support.
2. **Specify**: provider contract(s) → platform object mapping → domain spec/profile → consumer contract(s).
3. **Register**: add/update spec entries in the manifest.
4. **Conformance**: implement or update conformance checks for the new/changed specs.
5. **Implement**: connectors, normalization, processing, models, decision packets.
6. **Deliver**: dashboards based on consumer contracts (not ad-hoc payloads).
7. **Verify**: run the conformance step and attach evidence to the PR.

### PR acceptance criteria (minimum)

A PR that changes behavior is not acceptable unless it includes:

- **Spec changes first** (when introducing a new provider/platform/domain/consumer surface)
- **No bypass of canonical objects** (normalization remains mandatory)
- **No weakening of safeguards** (provenance/reliability/human-review/conformance)
- **Conformance evidence**: `python main.py --step conformance` passes

### Code layout: `src/` (legacy AQ) vs `urban_platform/` (platform)

- **`main.py`** calls **`urban_platform.applications.air_pollution.pipeline`**, which **delegates** to **`src.pipeline`** for the reference AQ run. **`src/`** is the **legacy MVP** air-quality pipeline (orchestration, features, model, recommendations, etc.).
- **`urban_platform/`** is the **canonical** package for **new** connectors, processing, applications, SDK/API, and conformance **code**; contracts remain under root **`specifications/`** (see `specifications/ARCHITECTURE_NOTE.md` — *Repository code layout*).
- **Do not** add **new domains** or **shared cross-domain** logic under **`src/`**. New vertical slices follow **`urban_platform/`** (e.g. flood, property_buildings). AQ migration out of `src/` is **incremental** and must keep **tests and conformance** green.
- **Dashboards** consume **SDK + application-layer** contract payloads, not new domain rules in Streamlit.

### Domain sequencing and access constraints

- **Start with the lowest-friction, lowest-risk data** that can demonstrate public value (open APIs, open licenses, fixtures, and clearly bounded demos).
- **Do not assume government system integrations are available at Phase 1.** Registries, permits, tax rolls, and cadastral systems often require procurement, legal basis, and operational agreements.
- **For sensitive domains**, begin with **open-data observability** and **field-review candidates**—not automated enforcement, tax, or ownership conclusions.
- **Municipal and departmental data integrations are later-stage** and must be **explicitly authorized** (contracts, access controls, consumer profiles, and governance)—see domain specs (e.g. `authorized_municipal_inputs` for `property_buildings`).
- **Property & Buildings:** Phase 1 is **open-data built-environment change detection** (footprints, EO change, wards, roads, settlement context), **not** property-tax optimization or permit enforcement. Use `docs/USE_CASE_ROADMAP.md`, `specifications/domain_specs/property_buildings.v1.yaml`, and `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md` before designing work.

### Forward deployment city profiles

- **Do not hard-code** city-specific assumptions (priorities, data availability, stakeholder names, boundary quirks) into shared AirOS modules; keep those in a **deployment-scoped city profile**, not sprinkled through `urban_platform/` or `src/` as literals.
- **Use** `deployments/templates/city_profile/` (see **`docs/CITY_PROFILE_TEMPLATE.md`**) so local deployment context stays **explicit, versionable in private repos, and specs-first-aligned**.
- **Do not commit** real sensitive city data—credentials, restricted datasets, unpublished MoUs, or personal stakeholder contact details—to the **public** AirOS repository. Use **templates and examples** here; operational profiles belong in **private deployment** workspaces unless the maintainer explicitly authorizes otherwise.
- A filled city profile is **not** a substitute for **provider/domain/consumer specs**—it informs **prioritization and access reality**, while contracts remain canonical.

### Federation and the AirOS Network Layer

- Treat AirOS as **node-first** and **federation-ready**: **do not** assume a single monolithic municipal deployment covers all agencies (`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`, `docs/AGENCY_NODE_MODEL.md`).
- The **AirOS Network Layer** (coordination intent: `docs/CROSS_AGENCY_COORDINATION_LAYER.md`) is **domain-agnostic**, **contract-aware**, and **policy-enforcing**—a protocol/policy plane—not a domain reasoning layer. **Do not** embed PM2.5 thresholds, flood levels, enforcement logic, or other domain semantics in network/coordination implementations; keep meaning in **domain specs** and **applications**.
- **Email** is a plausible **Phase 1 transport adapter** only; it is **not** the Network Layer. The same **logical message envelope** should port to APIs, buses, queues, etc.
- **Do not implement** cross-agency networking adapters **without specs** (`specifications/`); federation docs enumerate **future** schema filenames—implement only after contracts exist.

### Urban governance & AI CoE context (read before sequencing or major implementation)

Before changing **domain sequencing**, **integration assumptions**, or **cross-agency consumer shapes**, read:

- **`docs/URBAN_CONTEXT_INDIA.md`** — why Indian urban governance is fragmented, capacity-variable, and open-data-first by necessity.
- **`docs/AI_COE_OPERATING_STRATEGY.md`** — how the AI CoE, core platform team, and forward deployment engineers iterate safely with cities.

These documents explain **why** open-data-first phases and **specs as coordination instruments** are default AirOS posture—not optional narrative.

### Further reading

- **Urban governance context (India)**: `docs/URBAN_CONTEXT_INDIA.md`
- **AI CoE operating strategy**: `docs/AI_COE_OPERATING_STRATEGY.md`
- **Specs-first development**: `docs/SPECS_FIRST_DEVELOPMENT.md`
- **Vision**: `docs/AIR_OS_VISION.md`
- **Actor model**: `docs/ACTOR_MODEL.md`
- **Use-case roadmap**: `docs/USE_CASE_ROADMAP.md`
- **Data-source discovery**: `docs/DATA_SOURCE_CATALOG.md`
- **Domain development playbook (Cursor / agents)**: `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`
- **City profile template (forward deployment)**: `docs/CITY_PROFILE_TEMPLATE.md` · `deployments/templates/city_profile/`
- **Federated deployment & network layer**: `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md` · `docs/AGENCY_NODE_MODEL.md` · `docs/CROSS_AGENCY_COORDINATION_LAYER.md`
- **Contract architecture + `src/` vs `urban_platform/` layout**: `specifications/ARCHITECTURE_NOTE.md`
- **Machine-readable policy**: `specifications/spec_policy.yaml` (and `specifications/specs_policy.yaml`)

