# Domain development playbook (AirOS, specs-first)

Use this playbook in **Cursor or any coding agent** so new domains and phases progress **without ad-hoc external guidance**. AirOS is **specs-first**: contracts and domain semantics lead implementation.

### City profile (forward deployment)

Forward deployment engineers should **create a city profile** before starting **city-specific** sequencing, stakeholder alignment, or data-access assumptions—or before steering multi-domain priorities for a municipality. Copy `deployments/templates/city_profile/` and follow **`docs/CITY_PROFILE_TEMPLATE.md`**. Keep **real jurisdictional or sensitive operational data** out of the public platform repository; maintain live profiles in a **private deployment** repo or secure workspace aligned with institutional policy.

**Multi-agency / federation:** AirOS is **node-first**; a city profile alone is **not** enough when several agencies run separate deployments or need **cross-node** coordination. Read **`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`**, **`docs/AGENCY_NODE_MODEL.md`**, and **`docs/CROSS_AGENCY_COORDINATION_LAYER.md`** before designing inter-agency flows—the **Network Layer** routes **contract-shaped** traffic and enforces **policy**; it does **not** embody domain semantics or override agency authority.

## Before writing code

1. **Read** `docs/URBAN_CONTEXT_INDIA.md` and `docs/AI_COE_OPERATING_STRATEGY.md` so sequencing and integration choices match **Indian urban governance reality** and the **AI CoE + forward deployment** model.
2. **Read** `docs/USE_CASE_ROADMAP.md` for where the domain sits in the product sequence and phased delivery (e.g. Property & Buildings Phases 1–5).
3. **Read** `AGENTS.md` (especially **Domain sequencing and access constraints** and **Urban governance & AI CoE context**) and `docs/SPECS_FIRST_DEVELOPMENT.md`.
4. **Read** `specifications/spec_policy.yaml` / `specifications/specs_policy.yaml` if you are changing contract families or manifests.
5. **Read** the **domain spec** under `specifications/domain_specs/<domain>.v1.yaml` — note `open_data_inputs` vs `authorized_municipal_inputs`, `blocked_uses`, `required_human_review`, and `field_verification_requirements` where present.
6. **Read** `docs/DATA_SOURCE_CATALOG.md` for candidate sources, licenses, and access risks.

For a **repo-specific** architecture snapshot (layout, conformance, gaps, supervisor tooling), see **`docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`** before large refactors or new domains.

## Repository layout (use the right layer)

**Authoritative detail:** `specifications/ARCHITECTURE_NOTE.md` → section **“Repository code layout: `src/` vs `urban_platform/`”** (current state, **ownership table**, migration principles, and **suggested AQ migration sequence**).

Summary:

- **`main.py`** → **`urban_platform.applications.air_pollution.pipeline`** → today still **delegates** to **`src.pipeline.run_pipeline`** for the AQ reference run. **`src/`** is **legacy AQ MVP** only—not where new domains or shared platform logic should land.
- **`urban_platform/`** — **Canonical** home for **connectors**, **fabric**, **processing**, **applications** (contract-shaped payloads), **SDK/API**, and **conformance Python** (`urban_platform/specifications/*.py`), which **reads** root **`specifications/`** only.
- **`review_dashboard/`** — **Presentation** only via **`urban_platform/sdk`**; build payloads under **`urban_platform/applications/<domain>/`**.
- **`specifications/examples/`** — versioned fixtures; **`data/`** — local runtime outputs, not source of truth.

### Migration rule of thumb

- **New work:** `urban_platform/` (+ specs). **Do not** add new domain stacks under `src/`.
- **AQ edits:** choose **`src/`** vs **`urban_platform/`** deliberately, or do a **bounded migration PR** with tests + conformance.

## Reference vertical slice (copy this shape)

The **flood** (`flood_risk`) and **property/buildings** (`property_buildings`) slices follow the same ladder:

1. `specifications/domain_specs/<domain>.v1.yaml`
2. Provider + consumer JSON Schemas + registration in `specifications/manifest.json`
3. Examples under `specifications/examples/<domain>/`
4. `urban_platform/processing/<domain>/` (features; property also uses `open_data_features.py` for Phase 1)
5. `urban_platform/applications/<domain>/` (`dashboard_payload.py`, decision/review packets, `field_tasks.py`)
6. `tests/test_<domain>_*.py`
7. `review_dashboard/components/<domain>_panel.py` (+ panel demo test)

**Domain maturity** checks load **YAML checklists** from `tools/ai_dev_supervisor/domain_checklists/` (e.g. `flood_risk`, `property_buildings`). Add `{domain}.yaml` there when you add a vertical slice—not hard-coded maturity in Python.

## Domain spec vs runtime (semantic discipline)

Conformance **`audit_domain_specs`** validates **required top-level keys** in domain YAML, not that every `safety_gates` / `blocked_uses` line is enforced in Python. Treat the domain spec as **durable intent**; align **code and tests** with it—do not rely on structure checks alone.

## Check data access constraints

- Prefer **open or externally obtainable** data for **Phase 1** value demos.
- **Do not assume** municipal registry, permit, tax, or cadastral APIs are available without an explicit **later-stage, authorized-integration** plan.
- Record **license**, **provenance**, **PII risk**, and **blocked uses** before proposing connectors or dashboards.

## Start with open / low-friction data

- Define the **smallest** end-to-end slice: fixtures → normalization (if any) → features → **one** consumer payload shape → conformance → read-only UI (if applicable).
- For **Property & Buildings Phase 1**, prioritize footprints, EO change signals, wards, roads, and settlement context — **not** tax or enforcement narratives.

## Specify (no implementation without contracts)

1. **Create or update** the **domain spec** (`specifications/domain_specs/`).
2. **Create or update** **provider contracts** for each ingestion surface you will use in the slice.
3. **Create or update** **consumer contracts** for each payload the app will emit.
4. **Register** artifacts and examples in `specifications/manifest.json`.
5. **Add examples** under `specifications/examples/<domain>/`.

## Conformance

- Run `python main.py --step conformance` and fix schema / example issues before expanding scope.
- Run `python -m pytest -q` on behavior-affecting changes.
- Optional: `python tools/ai_dev_supervisor/run_review.py --run-conformance --domain <domain_key>` for governance + maturity snapshot (and optional dashboard URL probe).
- **CI:** When the repository adds automated workflows, conformance + tests should run there too; until then, treat **local** runs as the merge gate (`docs/USE_CASE_ROADMAP.md` Phase 2).

## Implement one bounded layer at a time

Suggested order for a new vertical slice:

1. Processing / features (pure functions, DataFrames or canonical objects).  
2. Application-layer payload builders (dashboard, decision/review packet, field tasks).  
3. Tests pinned to contracts.  
4. Read-only dashboard tab or API surface **only** if consumer contracts and examples already exist.

Avoid: connectors without provider contracts, ad-hoc JSON for dashboards, weakening provenance or human-review gates.

## Stop and summarize

After each bounded PR or task:

- Summarize **what spec artifacts changed**, **what code paths exist**, and the **next single bounded task** (e.g. “add EO ingest stub + example only”).
- Attach or reference **conformance evidence** for any behavior-affecting change.

## Property & Buildings reminder

Phase 1 = **open-data built-environment change detection** and **field-review candidates**. Municipal registry / permit / tax integrations are **later-stage** and **authorized**—see `specifications/domain_specs/property_buildings.v1.yaml` and `docs/USE_CASE_ROADMAP.md`.
