# AirOS developer guide

**New to AirOS? Start with [`docs/BEGINNER_DEVELOPER_GUIDE.md`](BEGINNER_DEVELOPER_GUIDE.md).**

If you want a guided “scaffold → validate → package → inspect” walkthrough, see [`docs/BUILD_YOUR_FIRST_AIR_OS_APP.md`](BUILD_YOUR_FIRST_AIR_OS_APP.md).

For evidence export/inspection/verification (pilot runtime governance posture), see [`docs/EVIDENCE_BUNDLES.md`](EVIDENCE_BUNDLES.md).

For a single repo-wide “what’s done vs pilot vs future” summary, see [`docs/PROJECT_STATUS.md`](PROJECT_STATUS.md).

For how the pilot runtime store should evolve (backup/export/import/compaction/retention), see [`docs/PILOT_STORE_LIFECYCLE.md`](PILOT_STORE_LIFECYCLE.md).

For how contracts, deployments, catalogs, and future federation fit together, see [`docs/INTEROPERABILITY_MODEL.md`](INTEROPERABILITY_MODEL.md).

For the conceptual product boundaries (Core vs Apps vs Adapters vs SDK/Studio/Catalog/Identity/Network), see [`docs/PRODUCT_MODEL.md`](PRODUCT_MODEL.md).

For the safe, phased repository restructuring plan (namespaces first, no breaking moves), see [`docs/REPO_RESTRUCTURING_PLAN.md`](REPO_RESTRUCTURING_PLAN.md).

This guide is for developers extending the AirOS repository safely and consistently.

## What AirOS is (and what it is not)

**AirOS is specs-first.** New capabilities start with contracts under `specifications/`, then conformance, then implementation.

- **AirOS Core**: the governance and validation layer (specs, conformance, review console, CLI helpers).
- **Provider Adapters**: connectors and ingest adapters that normalize external inputs into canonical platform objects (future and/or fixture-based in demos).
- **AirOS Apps**: domain/application builders that turn normalized data into contract-shaped outputs (dashboards, decision packets, review packets, tasks).
- **App descriptors**: governed metadata describing an app’s decision logic, contracts, dashboards, deployment examples, and safety posture (see `specifications/app_descriptors/`).
- **Provider adapter descriptors**: governed metadata describing provider adapters (what they emit, what configuration they need, and safety notes) under `specifications/provider_adapters/`. Not executable plugins.
- **SDK**: developer framework for building apps/adapters (early-stage; see “AirOS SDK, early skeleton” below).
- **Studio/CLI**: developer/operator tooling (today: `tools/`).
- **App Catalog**: discovery/installation surface (future-facing; direction captured in `docs/PRODUCT_MODEL.md`).
- **Identity & Trust**: participants/users/roles/keys/policies (production hardening work).
- **Network Layer**: cross-node communication, envelopes, routing, receipts (future-facing).
- **Deployments**: runnable, declarative workspaces that enable specific providers/applications with a profile + registries.

AirOS demo outputs are **review support only**. The platform must not imply automated enforcement, disbursement, penalties, or public disclosure.

## Repository layout (where to put code)

- **Specifications (mandatory first)**: `specifications/`
  - Provider contracts: `specifications/provider_contracts/`
  - Consumer contracts: `specifications/consumer_contracts/`
  - Platform objects: `specifications/platform_objects/`
  - Domain specs (semantics/safety): `specifications/domain_specs/`
  - Registries: `specifications/registry_contracts/`
  - Manifest wiring: `specifications/manifest.json`
  - Examples (fixtures): `specifications/examples/`
- **Canonical implementation**: `urban_platform/`
  - Connectors, processing, applications, conformance utilities.
- **Review console (Streamlit UI)**: `review_dashboard/`
- **Deployment examples**: `deployments/examples/`
- **Tools/CLI**: `tools/`

**Rule of thumb:** New domains and shared logic go in `urban_platform/` and must be contract-driven. Avoid adding new domain semantics inside `review_dashboard/`.

## Specs-first workflow (required)

1. **Define the use case**: who reviews what, what decision is supported, and what must be blocked.
2. **Specify contracts**:
   - provider contract(s) (if accepting external feeds)
   - platform object mapping (canonical objects)
   - domain spec for semantics/safety gates
   - consumer contract(s) for outputs
3. **Register** artifacts in `specifications/manifest.json`.
4. **Conformance**: ensure examples validate and conformance passes.
5. **Implement** connectors/builders under `urban_platform/`.
6. **Present** outputs in `review_dashboard/` (presentation-only).

## Manifest keys and registries

AirOS uses a central manifest `specifications/manifest.json` to register schemas and examples.

- **Manifest artifact keys** are referenced by registries and tooling (e.g., deployment validation).
- **Deployment registries** point to enabled providers/applications, not dynamic plugins:
  - Provider registry: `provider_registry.yaml`
  - Application registry: `application_registry.yaml`
  - Deployment profile: `deployment_profile.yaml`

AirOS does **not** support dynamic module execution from registries in this repo’s Phase 1 demos. Demos use explicit allowlists.

## AirOS SDK, early skeleton

The AirOS SDK is currently an **internal Python module** under `urban_platform/sdk/`. It provides **stable helper imports** for app and adapter developers.

- It does **not** replace the Core API.
- It does **not** enable dynamic plugins or execute app descriptors.
- It helps validate payloads/fixtures by `contract_key`, inspect contracts, inspect app descriptors (metadata), and compute deterministic payload hashes.

Example:

```python
from urban_platform.sdk import assert_fixture_valid, get_app_descriptor

assert_fixture_valid(
    "consumer_city_program_submission",
    "specifications/examples/program_reporting/city_program_submission.sample.json",
)

app = get_app_descriptor("program_reporting_review")
```

## Developer inspection commands

These are read-only commands for inspecting contracts, validating fixtures, and inspecting app descriptors. They do **not** execute builders.

```bash
python tools/airos_cli.py contracts list
python tools/airos_cli.py contracts show consumer_city_program_submission
python tools/airos_cli.py fixtures validate consumer_city_program_submission specifications/examples/program_reporting/city_program_submission.sample.json
python tools/airos_cli.py apps list
python tools/airos_cli.py apps show program_reporting_review
python tools/airos_cli.py apps explain program_reporting_review
python tools/airos_cli.py apps explain flood_risk_review
```

## Provider adapter discovery commands

Provider Adapter Descriptors are governed metadata under `specifications/provider_adapters/`. They are not executable plugins.

```bash
python tools/airos_cli.py adapters list
python tools/airos_cli.py adapters show openaq_air_quality_adapter
python tools/airos_cli.py adapters show open_meteo_weather_adapter
python tools/airos_cli.py adapters show osm_geospatial_adapter
```

## Reference catalog discovery commands

Reference catalogs are **local example fixtures** under `specifications/examples/reference_data/`. They provide shared codes for administrative units, programs, reporting periods, and other reference data.

This is **read-only local discovery only**: no pull/cache/TTL, publication workflows, trust/signatures, or federation are implemented here.

```bash
python tools/airos_cli.py catalogs list
python tools/airos_cli.py catalogs show administrative_units_demo_in
python tools/airos_cli.py catalogs show program_catalog_demo_in
python tools/airos_cli.py catalogs show reporting_periods_demo_in
```

## Deployment discovery commands (read-only)

Deployment examples live under `deployments/examples/` as declarative profiles + registries.

These commands are discovery-only: they do not validate or run deployments.

```bash
python tools/airos_cli.py examples list
python tools/airos_cli.py examples describe flood_local_demo
python tools/airos_cli.py deployments list
python tools/airos_cli.py deployments show flood_local_demo
```

## Platform inventory (read-only)

Use this when you want a quick overview of what’s available in the repo (contracts, apps, adapters, catalogs, deployments) and optionally local pilot-runtime store counts.

```bash
python tools/airos_cli.py inventory
python tools/airos_cli.py inventory --include-runtime
```

## Core API health checks (liveness vs readiness)

- `GET /health` and `GET /health/live` indicate the Core API process is alive.
- `GET /health/ready` indicates Core can load governed metadata and access the local runtime store. Health checks are **read-only**: they do not execute apps, adapters, or deployments.

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready

python tools/airos_cli.py health
python tools/airos_cli.py health --api-base-url http://127.0.0.1:8000
```

### Runtime list pagination (optional)

Runtime list endpoints return raw arrays by default (backward-compatible). Add `paginated=true` to receive an envelope with `items`, `total`, `limit`, and `offset`.

```bash
curl "http://127.0.0.1:8000/runs?paginated=true&limit=10&offset=0"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet&paginated=true&limit=10&offset=0"
curl "http://127.0.0.1:8000/audit-events?action=output_generated&paginated=true&limit=20&offset=0"
```

## Pilot store backup (read-only)

Create a zip backup of the pilot `FileAirOsStore` JSONL files with a `store_manifest.json` (file hashes + line counts). This is operational support only: it is **not** restore/import, not an evidence bundle, and not a digital signature.

```bash
python tools/airos_cli.py store backup \
  --store-dir data/store/api \
  --output-dir data/backups
```

Inspect a backup zip offline (read-only, no restore/import):

```bash
python tools/airos_cli.py store inspect-backup data/backups/<backup>.zip
```

Verify a backup zip offline (hashes + internal consistency; no restore/import):

```bash
python tools/airos_cli.py store verify-backup data/backups/<backup>.zip
```

Dry-run restore checks (no writes):

```bash
python tools/airos_cli.py store restore-dry-run data/backups/<backup>.zip --target-dir /tmp/airos_restore_candidate
```

Actual restore is not implemented yet. See [`docs/PILOT_STORE_RESTORE_DESIGN.md`](PILOT_STORE_RESTORE_DESIGN.md).

## Evidence bundle export (pilot runtime, read-only)

Export a portable zip with runs, records, outputs, validation receipts, and audit events for review/debug/audit support.

This does **not** rerun applications, execute builders, or imply approval.

Exported bundles include `hash_manifest.json` (SHA-256 hashes for bundle members) to support offline file-integrity checks. This is **not** a digital signature and does not prove signer identity.

```bash
python tools/airos_cli.py evidence export \
  --run-id <run_id> \
  --store-dir data/store/api \
  --output-dir data/outputs/evidence
```

Inspect an exported bundle offline (read-only):

```bash
python tools/airos_cli.py evidence inspect data/outputs/evidence/<bundle>.zip
```

Verify internal consistency (offline, read-only):

```bash
python tools/airos_cli.py evidence verify data/outputs/evidence/<bundle>.zip
```

Create a redacted sharing copy (read-only):

```bash
python tools/airos_cli.py evidence redact data/outputs/evidence/<bundle>.zip \
  --profile public_demo \
  --output-dir data/outputs/evidence
```

## App scaffolding (safe, non-executable)

Create a local starter folder for a new AirOS App. This is scaffolding only: it does **not** modify the manifest, does **not** register anything, and does **not** make the app executable.

```bash
python tools/airos_cli.py apps scaffold heat_risk_review --domain-id heat_risk
python tools/airos_cli.py apps validate apps/heat_risk_review
python tools/airos_cli.py apps package apps/heat_risk_review --output-dir dist/apps
python tools/airos_cli.py apps inspect-package dist/apps/heat_risk_review-v1.zip
python tools/airos_cli.py catalog add-package dist/apps/heat_risk_review-v1.zip
python tools/airos_cli.py catalog list
python tools/airos_cli.py catalog show heat_risk_review
```

## Reference catalogs (Phase 1 pattern)

For state-to-city reporting, AirOS uses **reference catalogs** (Phase 1 demo):

- Contract: `specifications/platform_objects/reference_catalog.v1.schema.json`
- Fixtures: `specifications/examples/reference_data/`
- Submissions/packets include `reference_data_versions` so reviewers know which catalog version was assumed.

Phase 1 is **declarative** only: no pull/cache/TTL/signing in this repository demo.

## Storage abstraction (pilot building block)

AirOS demos write review outputs under `data/outputs/…`. For pilot-oriented runtime hardening, the repository also includes a small **file-backed JSONL store** under `urban_platform/storage/` (`FileAirOsStore`) to persist:

- ingested records (`StoredRecord`)
- generated outputs (`StoredOutput`)
- audit events (`AuditEvent`)
- run metadata (`StoredRun`)
- validation receipts (`StoredValidationReceipt`)

This is **additive** scaffolding for future APIs/audit; it does not replace the current demo output path.

For the optional **generic pilot Core API** (`/records`, `/applications/{id}/runs`, `/runs`, `/validation-receipts`, `/outputs`, …), see [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md). For the full pilot-runtime flow into the dashboard, see [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md).

For contract discovery (schema inspection) before POSTing records, use:

- `GET /contracts/{contract_key}` (example: `consumer_city_program_submission`)

Example deployment runner store (fixture JSON unchanged; separate from Core API unless you point `AIROS_STORE_DIR` similarly):

```bash
python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo --store-dir data/store/program_reporting_state_demo
```

## How to add a provider (connector)

1. **Add a provider contract** under `specifications/provider_contracts/` describing what a provider can send.
2. **Map to platform objects** (or introduce a new platform object via `specifications/platform_objects/` if needed).
3. **Implement connector** under `urban_platform/connectors/<domain>/...`:
   - parse provider payload
   - validate against provider contract
   - normalize to platform objects
4. **Add fixtures** under `specifications/examples/<domain>/` (synthetic, no secrets).
5. **Register** schemas/examples in `specifications/manifest.json`.
6. **Conformance** must pass.

Do not add provider-specific fields into consumer payloads directly; go through canonical objects.

## How to add an application (consumer output)

1. **Add/extend a consumer contract** under `specifications/consumer_contracts/`.
2. **Implement the builder** under `urban_platform/applications/<domain>/...`:
   - input: canonical objects / feature rows
   - output: contract-shaped JSON
   - include provenance, warnings, blocked uses, and human-review gates
3. **Add tests** validating output conforms to schema.
4. **Add deployment example wiring** (see below) if you want a runnable demo.

Keep domain rules in domain specs + application builders, not in Streamlit.

## How to add a dashboard panel (Streamlit)

Panels live under `review_dashboard/components/` and must be **presentation-only**:

- read existing outputs under `data/outputs/deployments/<deployment_id>/...`
- render business-review UI: status, needs attention, next human step, blocked uses
- keep technical payloads in collapsed expanders

Do not:
- reimplement domain decision rules in Streamlit
- add actions implying enforcement, penalties, or fund release authorization

## How to add a deployment example

Deployment examples live under `deployments/examples/<name>/` and should be:

- **declarative** (YAML profiles + registries)
- **fixture-based** where possible
- **safe** (no secrets, no real PII, no restricted datasets)

Minimum files:
- `deployment_profile.yaml`
- `provider_registry.yaml`
- `application_registry.yaml`
- `README.md` (what it is + how to validate/run + what outputs appear)

## Running conformance and tests

From repo root:

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance
```

## Docker usage (running examples)

The public Docker image supports the same high-level flows:

- Run conformance inside Docker (governance gate).
- Run example deployments (fixture-based) and then open the review dashboard against outputs.

See `docs/DOCKER_DEPLOYMENT.md` for the concrete commands used in demos.

## Current runnable examples

Examples are discoverable via:

```bash
python tools/airos_cli.py examples list
python tools/airos_cli.py examples describe flood_local_demo
```

Included Phase 1 examples:
- **`flood_local_demo`**: flood vertical slice with fixture providers → features → dashboard payload + packets + tasks.
- **`program_reporting_state_demo`**: two synthetic city submissions → review packets + state summary + Streamlit review tab.

