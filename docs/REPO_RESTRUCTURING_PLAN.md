# AirOS repository restructuring plan (safe, phased)

## Why restructure

AirOS is moving from a single mixed repository toward clearer product boundaries:

- Core runtime
- Apps
- Provider Adapters
- SDK
- Studio/CLI
- Dashboard
- Catalog/spec foundations

This is a **Decision Support Operating System for urban governance**. The product model separates Core, Apps, Provider Adapters, SDK, Studio/CLI, App Catalog, Identity & Trust, Network Layer, and Audit/Receipts/Runs.

For a single table mapping **product areas → current repo paths → future targets → status**, see [`docs/PRODUCT_MODEL.md#product-model-to-repository-map`](PRODUCT_MODEL.md#product-model-to-repository-map).

The repository currently contains these product areas, but they are not yet physically grouped into distinct top-level packages. A gradual restructuring improves:

- contributor comprehension (where to put code, what not to mix)
- governance clarity (what is domain-neutral vs domain-specific decision logic)
- long-term packaging and distribution (Core vs SDK vs Studio/CLI vs apps/adapters)
- reduction of accidental coupling and unsafe “plugin” designs

## Product-model target structure

- **AirOS Core**: domain-neutral runtime for records, validation, runs, outputs, receipts, and audit
- **AirOS Apps**: package domain-specific decision logic + review experiences (contracts, panels, templates, safety)
- **Provider Adapters**: normalize external data sources into contract-shaped AirOS records
- **AirOS SDK**: developer framework for building apps/adapters without deep Core internals
- **AirOS Studio / CLI**: scaffolding, validation, packaging, deployment, inspection tools
- **AirOS App Catalog**: governed discovery/install of apps/adapters/panels/templates/contract packs (future)
- **Identity & Trust**: participants/users/orgs/roles/keys/policies (future hardening)
- **Network Layer**: envelopes/routing/receipts across nodes (future hardening)

## Current repo mapping (today)

This mapping is descriptive only; it does not imply immediate folder movement.

- **Core today**:
  - `urban_platform/api/`
  - `urban_platform/storage/`
  - `urban_platform/deployments/`
  - `urban_platform/specifications/`
  - `specifications/`
- **Apps today**:
  - `urban_platform/applications/`
  - `specifications/app_descriptors/`
- **Provider adapters today**:
  - `urban_platform/connectors/`
- **Studio/CLI today**:
  - `tools/airos_cli.py`
  - `tools/deployment_runner/`
  - `tools/ai_dev_supervisor/`
- **Dashboard today**:
  - `review_dashboard/`
- **Catalog/spec foundations today**:
  - `specifications/manifest.json`
  - `specifications/app_descriptors/`
  - `deployments/examples/`

## Target package layout (eventual)

Proposed eventual package structure (directional; not immediate):

```text
urban_platform/
  core/
    api/
    storage/
    deployments/
    specifications/
    runtime/
  apps/
    program_reporting/
    flood_risk/
    air_quality/
  adapters/
    air_quality/
    weather/
    geospatial/
    satellite/
    files/
  sdk/
    contracts/
    builders/
    validation/
    testing/
    packaging/
  studio/
    cli/
    deployment_runner/
    supervisor/
  dashboard/
    shell/
    components/
```

Keep top-level during transition:

- `specifications/` (contracts, manifest, examples, governed descriptors)—**stable by default**; governed artifacts live here on purpose (see Migration rules).
- `deployments/` (examples and templates evolve with governance, but moves are deliberate)
- `docs/`
- `tests/`
- `review_dashboard/` (until an explicit dashboard boundary decision)

## Phased migration plan

Ordering below is intentional: stabilize **discovery and developer-facing imports (SDK)** before large internal relocations under Core, while **namespace placeholders** clarify direction without breaking imports today.

### Phase 1: Product model, descriptors, and discovery

**Pilot status (in place today, subject to iterative hardening—not “complete productization”).**

Deliverables in progress or available in-repo:

- product model (`docs/PRODUCT_MODEL.md`, including [`product model ↔ repository map`](PRODUCT_MODEL.md#product-model-to-repository-map))
- governed **app descriptors** (`specifications/app_descriptors/*`) and validation schema
- governed **provider adapter descriptors** (`specifications/provider_adapters/*`)—metadata only; not executable plugins
- **Core API pilot** discovery surfaces for apps, adapters, catalogs, deployments, and inventory-style reads where implemented (contracts and behavior remain bounded by manifests and allowlists)
- **SDK / CLI discovery helpers** (e.g. read-only inspection under `urban_platform/sdk/` and `tools/airos_cli.py`) aligned with manifests and descriptors

This phase does **not** imply restructuring is complete; paths below remain authoritative until later phases migrate code behind wrappers.

### Phase 2: Namespace skeleton

**Pilot status.**

Deliverables:

- placeholder packages under `urban_platform/` for Core, Apps, Adapters, Studio (and related layout per target diagram), without requiring consumers to rely on those paths yet
- optional import-only or smoke checks so skeleton namespaces remain valid as the tree evolves

Critical constraint:

- **No implementation has moved into these skeleton namespaces yet** in a way that changes behavior or canonical imports.
- **Legacy import paths** (`urban_platform/api/`, `urban_platform/storage/`, `urban_platform/deployments/`, `urban_platform/applications/`, `urban_platform/connectors/`, existing `tools/*` entrypoints) remain **canonical for runtime and tests** until an explicit migration PR series adds compatibility shims.

### Phase 3: SDK stabilization

Deliverables:

- stabilize **developer-facing imports** via `urban_platform/sdk/` so app, adapter, and tooling authors prefer SDK surfaces instead of reaching into shifting Core internals
- document SDK modules as the supported extension point alongside contracts and manifests

Rationale:

- SDK gives developers **stable imports** while Core modules can later relocate behind **SDK and API compatibility wrappers**, reducing breakage during storage/API/deployment-runtime moves.

### Phase 4: Core storage migration

Deliverables:

- migrate `urban_platform/storage/` toward `urban_platform/core/storage/` (or equivalent under `urban_platform/core/`) **incrementally**, with thin re-export modules at old paths until deprecated
- no behavior changes; conformance + tests after each PR slice

Separation principle:

- **Top-level `specifications/`** (YAML/JSON artifacts: contracts, manifest, examples, descriptors) **stays stable**—this phase targets **runtime storage code**, not governed contract files.

### Phase 5: Core API migration

Deliverables:

- migrate `urban_platform/api/` toward `urban_platform/core/api/` incrementally with backward-compatible import paths for ASGI/app factories and dependents
- keep existing production-like and pilot entrypoints working until deprecation is explicit

Migrating Core API **must not** drag repo-root **`specifications/`** (contracts, manifest, descriptors, examples) along for tidy layout alone; artifact locations change only via explicit governance decisions.

### Phase 6: Core deployment-runtime migration

**Includes an explicit decision** on relocating vs retaining Python helper modules under `urban_platform/specifications/` (distinct from governed artifacts at repo-root `specifications/`).

Deliverables:

- migrate deployment-runtime concerns currently under `urban_platform/deployments/` (and closely related bootstrap) toward `urban_platform/core/deployments/` (or agreed subpackage names) behind wrappers
- make an explicit decision on **`urban_platform/specifications/`**: these are **Python helper modules** (conformance/engine/runtime validation) distinct from governed artifacts under repo-root **`specifications/`**. Plan whether they relocate under `urban_platform/core/specifications_helpers/` (name TBD), merge under `urban_platform/core/`, or remain in place—with compatibility shims either way—**without** implying any move of YAML contracts or descriptors at repo root.

Clarifier:

- **Governed artifact root** **`specifications/`** holds manifests, contracts, examples, app descriptors, and provider adapter descriptors; it should remain the stable editorial home unless a future **governance-signed** relocation is approved—not for casual package tidy-up.

### Phase 7: Studio/CLI internal migration

Deliverables:

- use **compatibility wrappers** while moving implementation

- move internal implementation for CLI, supervisor, deployment runner, and related tooling toward `urban_platform/studio/` as appropriate
- keep **`tools/airos_cli.py`**, **`tools/deployment_runner/`**, **`tools/ai_dev_supervisor/`** (and similar) as **stable thin entrypoints** wrapping studio modules

### Phase 8: App-by-app migration

Deliverables:

- migrate pilots one application at a time (e.g. program reporting first, flood second, others later), each PR small and reversible
- keep **`urban_platform/applications/`** compatibility re-exports for as long as external or test code depends on them

### Phase 9: Provider adapter migration

Deliverables:

- migrate `urban_platform/connectors/` toward `urban_platform/adapters/` incrementally per adapter cluster or subdirectory
- keep compatibility wrappers; **no dynamic plugin loading**—adapter descriptors remain governance metadata tied to reviewed connector code and deployment configuration

### Phase 10: Dashboard boundary decision

Deliverables:

- decide whether `review_dashboard/` remains a **top-level product shell** or eventually moves under **`urban_platform/dashboard/`** (or another agreed layout)

Constraint:

- decision-first; actual moves only after rationale, risk review, and the same incremental wrapper discipline as Core.

## Migration rules

- Do **not** move contracts, app descriptors, provider adapter descriptors, reference catalog examples, or deployment examples **merely for package symmetry**. These are **governed artifacts** (and deployment exemplars bound to conformance) and should stay stable unless a **specific governance-backed migration decision** relocates them with provenance preserved.
- no giant move commits
- one product area (or slice of Core) per migration PR
- maintain backward-compatible imports
- keep old entrypoints working until explicitly deprecated
- tests and conformance after every phase (and preferably after each small PR slice)
- no dynamic plugin loading
- app execution remains through the **safe builder registry** and allowlisted application paths—not descriptor-driven executable plugins
- safety language remains visible
- no production-security claims

## What not to move yet

- do not rename `urban_platform` yet
- do not move all apps at once
- do not move `review_dashboard/` until Phase 10 decisions and follow-up migrations
- do not delete compatibility modules until downstream imports are updated
- do not convert app descriptors into executable plugins
- do not shuffle repo-root `specifications/` (contracts, manifest, examples, descriptors) for tidy layout alone—governed migrations only

## Verification checklist (each phase)

- `python -m pytest -q`
- `python main.py --step conformance`
- `python tools/ai_dev_supervisor/run_review.py --run-conformance`
- relevant CLI smoke
- relevant API smoke
- import compatibility checks

