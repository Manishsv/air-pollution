# AirOS Core API — generic pilot-runtime

## Purpose

The **generic Core API** is a thin, local-first HTTP surface over:

- `specifications/manifest.json` (contract keys ↔ schemas),
- **`FileAirOsStore`** (`StoredRecord`, `StoredOutput`, `AuditEvent`),
- **`urban_platform/deployments/builder_registry.py`** (allowlisted builders only).

It is intentionally **domain-agnostic at the route level**. New pilots add **validators + store usage + small application adapters** behind the same `/records`, `/applications/...`, and `/outputs` paths instead of carving new URLs per vertical.

For a copy-pasteable end-to-end walkthrough (API → outputs → dashboard API mode), see [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md).

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

## Endpoints (summary)

| Method | Path | Role |
|--------|------|------|
| `GET` | `/health` | Liveness |
| `GET` | `/manifest` | Lightweight manifest summary (`artifact_count`, sorted `contract_keys`) |
| `GET` | `/contracts` | Contract keys grouped by `contract_type` (developer discovery) |
| `GET` | `/contracts/{contract_key}` | Manifest-backed contract discovery: returns schema metadata + JSON schema |
| `POST` | `/records/{contract_key}` | Validate against manifest schema, persist `StoredRecord`; audits `record_ingested` / `record_rejected` |
| `GET` | `/records` | List stored records (optional `deployment_id`, `contract_key`) |
| `POST` | `/applications/{application_id}/runs` | Run an **allowlisted** builder with optional Core adapters (today: `program_reporting_review_packet`) |
| `GET` | `/runs` | List run metadata (filters: `deployment_id`, `application_id`, `status`) |
| `GET` | `/runs/{run_id}` | One run metadata record |
| `GET` | `/outputs` | List outputs (filters: `deployment_id`, `contract_key`, optional metadata: `application_id`, `program_id`, `reporting_period`) |
| `GET` | `/outputs/{output_id}` | One `StoredOutput` |
| `GET` | `/audit-events` | List audit events (`deployment_id` optional) |

Unknown `application_id` (not in the builder registry) → **404** fail-closed. Known builder without a Core executor → **400** fail-closed.

## Curl examples (`REPO_ROOT` / port 8000)

**Health**

```bash
curl http://127.0.0.1:8000/health
```

**Manifest summary**

```bash
curl http://127.0.0.1:8000/manifest
```

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

**List outputs**

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet"
curl "http://127.0.0.1:8000/outputs?contract_key=internal_program_reporting_state_summary_demo"
```

**Audit trail**

```bash
curl http://127.0.0.1:8000/audit-events
```

## Program Reporting slice (today)

Workflow through **generic endpoints** only:

1. `POST /records/consumer_city_program_submission` (one or many cities).
2. `POST /applications/program_reporting_review_packet/runs` with matching `deployment_id` / `program_id` / `reporting_period`.
3. Inspect `GET /runs` (summary), plus `GET /outputs?...` and `GET /audit-events` (details).

Builders and summaries come from **`urban_platform/applications/program_reporting/`**; the Core API wires storage and conformance only.

## Optional: Flood through the generic Core API

This demonstrates a multi-input vertical (three provider feeds → three consumer surfaces) through the **same generic endpoints**.

Start Core API:

```bash
AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
```

Submit records (from repo root):

```bash
curl -X POST http://127.0.0.1:8000/records/provider_rainfall_observation_feed \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/rainfall_observation.sample.json

curl -X POST http://127.0.0.1:8000/records/provider_flood_incident_feed \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/flood_incident.sample.json

curl -X POST http://127.0.0.1:8000/records/provider_drainage_asset_feed \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/drainage_asset.sample.json
```

Run (allowlisted):

```bash
curl -X POST http://127.0.0.1:8000/applications/flood_risk_dashboard_payload/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"flood_local_demo"}'
```

Fetch:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_flood_risk_dashboard"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_flood_decision_packet"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_field_verification_task"
```

Safety posture: **review support only**; **no emergency orders**; **field verification remains required**.

## Review dashboard (optional API mode)

By default the **Program Reporting** Streamlit panel reads **`data/outputs/deployments/program_reporting_state_demo/`**. To bind it to Core API payloads instead (**additive**):

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

**Required sequence** before opening the dashboard in API mode:

1. Start Core API:  
   `AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000`
2. POST both city fixtures to `{base}/records/consumer_city_program_submission`
3. POST `{base}/applications/program_reporting_review_packet/runs` with `deployment_id` / `program_id` / `reporting_period` JSON
4. Start Streamlit as above (`AIROS_API_BASE_URL` must match where uvicorn listens)

The dashboard uses generic **`GET /outputs?contract_key=...`** responses only; failures surface as **guided empty/error states**, not crashes.

Docker users can pass the same environment variables through `docker run -e`.

## Safety note

All responses that include service-level `warnings` reiterate **pilot posture** and that **disbursement and enforcement are not automated** by this service. Contract payloads may still enumerate **blocked uses** (e.g. `automatic_fund_release`)—that is schema-level caution, **not** an authorization to automate the opposite.
