# AirOS Core API — generic pilot-runtime

## Purpose

The **generic Core API** is a thin, local-first HTTP surface over:

- `specifications/manifest.json` (contract keys ↔ schemas),
- **`FileAirOsStore`** (`StoredRecord`, `StoredOutput`, `AuditEvent`),
- **`urban_platform/deployments/builder_registry.py`** (allowlisted builders only).

It is intentionally **domain-agnostic at the route level**. New pilots add **validators + store usage + small application adapters** behind the same `/records`, `/applications/...`, and `/outputs` paths instead of carving new URLs per vertical.

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

## Endpoints (summary)

| Method | Path | Role |
|--------|------|------|
| `GET` | `/health` | Liveness |
| `GET` | `/manifest` | Lightweight manifest summary (`artifact_count`, sorted `contract_keys`) |
| `POST` | `/records/{contract_key}` | Validate against manifest schema, persist `StoredRecord`; audits `record_ingested` / `record_rejected` |
| `GET` | `/records` | List stored records (optional `deployment_id`, `contract_key`) |
| `POST` | `/applications/{application_id}/runs` | Run an **allowlisted** builder with optional Core adapters (today: `program_reporting_review_packet`) |
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
3. Inspect `GET /outputs?...` and `GET /audit-events`.

Builders and summaries come from **`urban_platform/applications/program_reporting/`**; the Core API wires storage and conformance only.

## Safety note

All responses that include service-level `warnings` reiterate **pilot posture** and that **disbursement and enforcement are not automated** by this service. Contract payloads may still enumerate **blocked uses** (e.g. `automatic_fund_release`)—that is schema-level caution, **not** an authorization to automate the opposite.
