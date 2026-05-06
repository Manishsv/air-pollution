# AirOS Core API — generic pilot-runtime

## Purpose

The **generic Core API** is a thin, local-first HTTP surface over:

- `specifications/manifest.json` (contract keys ↔ schemas),
- **`FileAirOsStore`** (`StoredRecord`, `StoredOutput`, `AuditEvent`),
- **`urban_platform/deployments/builder_registry.py`** (allowlisted builders only).

It is intentionally **domain-agnostic at the route level**. New pilots add **validators + store usage + small application adapters** behind the same `/records`, `/applications/...`, and `/outputs` paths instead of carving new URLs per vertical.

For a copy-pasteable end-to-end walkthrough (API → outputs → dashboard API mode), see [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md).

For the lifecycle model of the pilot store (backup/export/import/compaction/retention; design-only), see [`docs/PILOT_STORE_LIFECYCLE.md`](PILOT_STORE_LIFECYCLE.md).

## What this is not

- **Not production-secure:** no authentication, no RBAC, no hardening for the public Internet.
- **Not domain-exclusive:** routes are generic; Program Reporting is the **first exercised vertical**.
- **Not fund-release automation:** no disbursement, treasury, finance integration, or enforcement. Outputs are **review support** only; appropriately authorized humans and finance processes remain **outside** AirOS.
- No reference-catalog pull/cache, participant directory, or signed envelopes.

## Configuration

| Variable | Meaning |
|----------|---------|
| `AIROS_STORE_DIR` | Root for `records.jsonl`, `outputs.jsonl`, `audit_events.jsonl`. Default: `data/store/api` under the repo root. |

## Run locally

```bash
AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
```

Interactive schema browser: `http://127.0.0.1:8000/docs`

## Run with Docker Compose (pilot-runtime profile)

If you want to run the Core API and dashboard together with a shared `./data` volume:

```bash
docker compose --profile pilot-runtime up --build
```

Then:

- Core API: `http://127.0.0.1:8000`
- Dashboard: `http://127.0.0.1:8501`

## How to use this document

- If you want an end-to-end “do these commands in order” guide, use [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md).
- This document is the **API reference**: endpoints, filters, and response shapes, plus safety posture.

## Endpoints (summary)

| Method | Path | Role |
|--------|------|------|
| `GET` | `/health` | Liveness |
| `GET` | `/health/live` | Liveness (process alive; lightweight) |
| `GET` | `/health/ready` | Readiness (Core can load metadata + access local store; read-only) |
| `GET` | `/manifest` | Lightweight manifest summary (`artifact_count`, sorted `contract_keys`) |
| `GET` | `/contracts` | Contract keys grouped by `contract_type` (developer discovery) |
| `GET` | `/contracts/{contract_key}` | Manifest-backed contract discovery: returns schema metadata + JSON schema |
| `GET` | `/apps` | Read-only app discovery from governed app descriptors |
| `GET` | `/apps/{app_id}` | One app descriptor (read-only metadata; not a plugin loader) |
| `GET` | `/adapters` | Read-only provider adapter discovery from governed adapter descriptors |
| `GET` | `/adapters/{adapter_id}` | One provider adapter descriptor (read-only metadata; not a plugin loader) |
| `GET` | `/catalogs` | Read-only reference catalog discovery from local reference-data examples |
| `GET` | `/catalogs/{catalog_id}` | One reference catalog (read-only local fixture; not live-synced) |
| `GET` | `/deployments` | Read-only deployment example discovery from `deployments/examples/` |
| `GET` | `/deployments/{deployment_id}` | One deployment example profile (read-only metadata; not executed) |
| `GET` | `/inventory` | Read-only platform inventory (static discovery + optional runtime store counts) |
| `POST` | `/records/{contract_key}` | Validate against manifest schema, persist `StoredRecord`; audits `record_ingested` / `record_rejected` |
| `GET` | `/records` | List stored records (optional `deployment_id`, `contract_key`) |
| `POST` | `/applications/{application_id}/runs` | Run an **allowlisted** builder with optional Core adapters (today: `program_reporting_review_packet`) |
| `GET` | `/runs` | List run metadata (filters: `deployment_id`, `application_id`, `status`) |
| `GET` | `/runs/{run_id}` | One run metadata record |
| `GET` | `/validation-receipts` | List schema validation receipts (filters: `deployment_id`, `contract_key`, `status`, `validation_target_type`) |
| `GET` | `/validation-receipts/{receipt_id}` | One validation receipt |
| `GET` | `/outputs` | List outputs (filters: `deployment_id`, `contract_key`, optional metadata: `application_id`, `program_id`, `reporting_period`) |
| `GET` | `/outputs/{output_id}` | One `StoredOutput` |
| `GET` | `/audit-events` | List audit events (`deployment_id` optional) |

Unknown `application_id` (not in the builder registry) → **404** fail-closed. Known builder without a Core executor → **400** fail-closed.

## Curl examples (reference)

**Health**

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

**Manifest summary**

```bash
curl http://127.0.0.1:8000/manifest
```

**App discovery (read-only metadata)**

```bash
curl http://127.0.0.1:8000/apps
curl http://127.0.0.1:8000/apps/program_reporting_review
curl http://127.0.0.1:8000/apps/flood_risk_review
```

Notes:

- `/apps` is read-only app metadata sourced from governed descriptors under `specifications/app_descriptors/`.
- App descriptors are not dynamic plugins and do not execute code.
- Application execution still goes through `POST /applications/{application_id}/runs` and the safe builder registry.

**Provider adapter discovery (read-only metadata)**

```bash
curl http://127.0.0.1:8000/adapters
curl http://127.0.0.1:8000/adapters/openaq_air_quality_adapter
curl http://127.0.0.1:8000/adapters/open_meteo_weather_adapter
curl http://127.0.0.1:8000/adapters/osm_geospatial_adapter
```

Notes:

- `/adapters` is read-only adapter metadata sourced from governed descriptors under `specifications/provider_adapters/`.
- Adapter descriptors are not dynamic plugins and do not execute connector code.

**Reference catalog discovery (read-only local fixtures)**

```bash
curl http://127.0.0.1:8000/catalogs
curl http://127.0.0.1:8000/catalogs/administrative_units_demo_in
curl http://127.0.0.1:8000/catalogs/program_catalog_demo_in
curl http://127.0.0.1:8000/catalogs/reporting_periods_demo_in
```

Notes:

- `/catalogs` is read-only discovery over local fixture examples under `specifications/examples/reference_data/`.
- No pull/cache/TTL, publication workflows, trust/signatures, or federation are implemented here.

**Deployment example discovery (read-only metadata)**

```bash
curl http://127.0.0.1:8000/deployments
curl http://127.0.0.1:8000/deployments/flood_local_demo
curl http://127.0.0.1:8000/deployments/program_reporting_state_demo
```

Notes:

- `/deployments` is read-only metadata sourced from `deployments/examples/`.
- It does not validate or run deployments, and it does not execute builders.
- Deployment execution remains a CLI workflow (`python tools/airos_cli.py deployment run <path>`) or allowlisted application runs (`POST /applications/{application_id}/runs`).

**Platform inventory (read-only)**

```bash
curl http://127.0.0.1:8000/inventory
curl "http://127.0.0.1:8000/inventory?include_runtime=true"
```

Notes:

- Inventory is discovery-only. It does not validate, run, install, publish, allowlist, or execute anything.
- `include_runtime=true` reports local store counts from `FileAirOsStore` (pilot runtime).

**Contract discovery (schema)**

```bash
curl http://127.0.0.1:8000/contracts/consumer_city_program_submission
curl http://127.0.0.1:8000/contracts/consumer_fund_release_review_packet
```

**Ingest Program Reporting submissions** (requires manifest key `consumer_city_program_submission`; optional query `deployment_id`, default aligns with demos)

```bash
curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission.sample.json

curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission_city_b.sample.json
```

**Run allowlisted application** (`program_reporting_review_packet`)

```bash
curl -X POST http://127.0.0.1:8000/applications/program_reporting_review_packet/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"program_reporting_state_demo","program_id":"stormwater_resilience_grant_2026","reporting_period":"2026_Q1"}'
```

**List runs**

```bash
curl http://127.0.0.1:8000/runs
curl "http://127.0.0.1:8000/runs?deployment_id=program_reporting_state_demo"
curl "http://127.0.0.1:8000/runs?application_id=program_reporting_review_packet"
curl "http://127.0.0.1:8000/runs?status=completed"
```

**Get one run**

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

**List validation receipts**

```bash
curl http://127.0.0.1:8000/validation-receipts
curl "http://127.0.0.1:8000/validation-receipts?status=invalid"
curl "http://127.0.0.1:8000/validation-receipts?contract_key=consumer_city_program_submission"
curl "http://127.0.0.1:8000/validation-receipts?validation_target_type=output"
curl "http://127.0.0.1:8000/validation-receipts?paginated=true&limit=10&offset=0"
```

**Get one validation receipt**

```bash
curl http://127.0.0.1:8000/validation-receipts/<receipt_id>
```

**List outputs**

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_program_reporting_state_summary"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet&paginated=true&limit=10&offset=0"
```

**Audit trail**

```bash
curl http://127.0.0.1:8000/audit-events
curl "http://127.0.0.1:8000/audit-events?action=output_generated&paginated=true&limit=20&offset=0"
```

### Pagination (runtime list endpoints)

Runtime list endpoints (`/records`, `/runs`, `/outputs`, `/validation-receipts`, `/audit-events`) support optional pagination.

- Default behavior remains **backward-compatible**: raw JSON arrays.
- Add `paginated=true` to receive an envelope:

```json
{
  "items": [],
  "count": 0,
  "total": 0,
  "limit": 100,
  "offset": 0,
  "next_offset": 0,
  "has_more": false
}
```

Pagination is read-only and does not execute apps, adapters, or deployments.

## End-to-end pilot runtime walkthroughs

To keep this document reference-only, end-to-end walkthroughs live in:

- [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md) (Program Reporting + Flood, copy/paste)

## Review dashboard (optional API mode)

By default, Streamlit panels read local fixture/demo outputs (file mode). You can bind panels to Core API outputs instead (**additive**), using the same generic `GET /outputs?contract_key=...` surface.

**File mode (default)**

```bash
streamlit run review_dashboard/app.py
```

**API mode**

```bash
AIROS_DASHBOARD_DATA_MODE=api \
AIROS_API_BASE_URL=http://127.0.0.1:8000 \
streamlit run review_dashboard/app.py
```

**Required sequence** before opening the dashboard in API mode (Program Reporting and/or Flood):

1. Start Core API:  
   `AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000`
2. Generate outputs via the Core API for the panel you want:
   - Program Reporting:
     - POST city fixtures to `{base}/records/consumer_city_program_submission`
     - POST `{base}/applications/program_reporting_review_packet/runs` with `deployment_id` / `program_id` / `reporting_period`
   - Flood:
     - POST fixtures to:
       - `{base}/records/provider_rainfall_observation_feed?deployment_id=flood_local_demo`
       - `{base}/records/provider_flood_incident_feed?deployment_id=flood_local_demo`
       - `{base}/records/provider_drainage_asset_feed?deployment_id=flood_local_demo`
     - POST `{base}/applications/flood_risk_dashboard_payload/runs` with `{"deployment_id":"flood_local_demo"}`
3. Start Streamlit as above (`AIROS_API_BASE_URL` must match where uvicorn listens)

The dashboard uses generic **`GET /outputs?contract_key=...`** responses only; failures surface as **guided empty/error states**, not crashes.

Docker users can pass the same environment variables through `docker run -e`.

## Runtime Trace tab (API mode)

When the dashboard runs in API mode, the **Runtime Trace** tab provides a simple view of:

- recent runs (`GET /runs`)
- validation receipts (`GET /validation-receipts`)
- audit events (`GET /audit-events`)

It is **traceability evidence**, not approval evidence.

## Evidence bundle export (CLI, read-only)

For a portable “what happened in this run?” bundle, use the CLI evidence export command. It packages runs, records, outputs, validation receipts, and audit events into a zip file for review/debug/audit support.

See [`docs/EVIDENCE_BUNDLES.md`](EVIDENCE_BUNDLES.md) for the evidence workflow and governance posture (verification is internal consistency only, not signatures/certification/approval).

Example:

```bash
python tools/airos_cli.py evidence export \
  --run-id <run_id> \
  --store-dir data/store/api \
  --output-dir data/outputs/evidence
```

This is export-only: it does not execute builders, rerun applications, or imply approval.

Inspect an exported bundle offline (read-only):

```bash
python tools/airos_cli.py evidence inspect data/outputs/evidence/<bundle>.zip
```

Verify internal consistency (offline, read-only):

```bash
python tools/airos_cli.py evidence verify data/outputs/evidence/<bundle>.zip
```

## Safety note

All responses that include service-level `warnings` reiterate **pilot posture** and that **disbursement and enforcement are not automated** by this service. Contract payloads may still enumerate **blocked uses** (e.g. `automatic_fund_release`)—that is schema-level caution, **not** an authorization to automate the opposite.
