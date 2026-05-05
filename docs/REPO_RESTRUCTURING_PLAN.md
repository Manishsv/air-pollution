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

- `specifications/` (contracts + manifest + governed descriptors)
- `deployments/`
- `docs/`
- `tests/`
- `review_dashboard/` (until an explicit dashboard move decision)

## Phased migration plan

### Phase 1: documentation and app descriptors

Deliverables:

- product model (`docs/PRODUCT_MODEL.md`)
- governed app descriptors (`specifications/app_descriptors/*`) + schema
- read-only app discovery endpoints (`GET /apps`, `GET /apps/{app_id}`)

Status: done or underway.

### Phase 2: namespace skeleton

Deliverables:

- add empty namespaces under `urban_platform/` for Core/Apps/Adapters/Studio
- no moves; no import changes required
- optional import-only tests to keep skeletons honest

### Phase 3: Core move with compatibility wrappers

Deliverables:

- move domain-neutral modules:
  - `urban_platform/api/`
  - `urban_platform/storage/`
  - `urban_platform/deployments/`
  - `urban_platform/specifications/`
  to:
  - `urban_platform/core/`
- keep backward-compatible import paths via thin wrappers (re-exports)
- keep old uvicorn import paths working until explicitly deprecated
- no behavior change; run conformance + tests after each PR

### Phase 4: Studio/CLI move with tools wrappers

Deliverables:

- move internal CLI/supervisor/deployment-runner implementation toward `urban_platform/studio/`
- keep `tools/airos_cli.py` and existing tool entrypoints as wrappers

### Phase 5: app-by-app migration

Deliverables:

- move apps one at a time:
  - program_reporting first
  - flood_risk second
  - air_quality later
- keep compatibility wrappers under `urban_platform/applications/` during transition

### Phase 6: provider adapter migration

Deliverables:

- move `urban_platform/connectors/` toward `urban_platform/adapters/`
- keep compatibility wrappers

### Phase 7: dashboard boundary

Deliverables:

- decide whether `review_dashboard/` remains top-level product shell or migrates under `urban_platform/dashboard/`
- do not move yet

### Phase 8: SDK stabilization

Deliverables:

- introduce stable SDK-facing imports so app developers do not depend on Core internals

## Migration rules

- no giant move commits
- one product area per migration PR
- maintain backward-compatible imports
- keep old entrypoints working until explicitly deprecated
- tests and conformance after every phase
- no dynamic plugin loading
- app execution remains through safe builder registry
- safety language remains visible
- no production-security claims

## What not to move yet

- do not rename `urban_platform` yet
- do not move all apps at once
- do not move `review_dashboard/` yet
- do not delete compatibility modules until downstream imports are updated
- do not convert app descriptors into executable plugins

## Verification checklist (each phase)

- `python -m pytest -q`
- `python main.py --step conformance`
- `python tools/ai_dev_supervisor/run_review.py --run-conformance`
- relevant CLI smoke
- relevant API smoke
- import compatibility checks

