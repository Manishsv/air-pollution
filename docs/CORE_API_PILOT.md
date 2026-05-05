# AirOS Core API — Program Reporting (pilot-runtime)

## Purpose

This is a **narrow, local-only** HTTP surface for the **Program Reporting** Phase 1 slice: ingest city program submissions, run the **existing** builders (`build_fund_release_review_packet`, `build_program_reporting_state_summary`), persist results in **`FileAirOsStore`**, and expose read paths for packets, state summary, and audit events.

It exists to exercise **pilot-runtime** patterns (store + API) without claiming production readiness.

## Warnings (read first)

- **Not production-secure:** there is **no authentication**, **no RBAC**, and **no hardening** for public internet exposure.
- **No fund release automation:** this service does **not** disburse funds, connect to treasury or finance systems, or authorize releases. Outputs are **review support** only; **authorized human and finance processes outside AirOS** remain required for any financial action.
- **No reference catalog pull/cache** and no participant directory or signed envelopes.

## Configuration

| Variable | Meaning |
|----------|---------|
| `AIROS_STORE_DIR` | Root directory for `FileAirOsStore` (`records.jsonl`, `outputs.jsonl`, `audit_events.jsonl`). Default: `data/store/api` (relative to repo root). |

Paths are created on demand.

## How to run locally

From the repository root (after installing dependencies, including `fastapi`, `httpx`, `uvicorn`):

```bash
AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
```

Open interactive docs at `http://127.0.0.1:8000/docs` if needed.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness / build identity. |
| `POST` | `/program-reporting/submissions` | Validate and store one city program submission (`consumer_city_program_submission`). Optional query: `deployment_id` (default `program_reporting_state_demo`). |
| `POST` | `/program-reporting/run` | Build review packets + state summary from **stored** submissions for a deployment/program/period. Body fields optional (defaults below). |
| `GET` | `/program-reporting/review-packets` | List stored review packet payloads; optional filters: `deployment_id`, `program_id`, `reporting_period`. |
| `GET` | `/program-reporting/state-summary` | Latest stored state summary for optional filters; **404** if none. |
| `GET` | `/audit-events` | List audit events; optional `deployment_id`. |

**`POST /program-reporting/run` default body values** (when omitted):

- `deployment_id`: `program_reporting_state_demo`
- `program_id`: `stormwater_resilience_grant_2026`
- `reporting_period`: `2026_Q1`

Validation uses the same manifest-backed validators as the rest of AirOS (`jsonschema` via `validator_for_schema_file`).

## Example `curl` commands

Assume the server is on `http://127.0.0.1:8000` and `REPO` is your clone root.

**Health**

```bash
curl -sS http://127.0.0.1:8000/health | jq .
```

**Post a city submission** (sample fixture)

```bash
curl -sS -X POST "http://127.0.0.1:8000/program-reporting/submissions" \
  -H "Content-Type: application/json" \
  -d @"$REPO/specifications/examples/program_reporting/city_program_submission.sample.json" | jq .
```

Repeat with `city_program_submission_city_b.sample.json` for a second city.

**Run Program Reporting** (after at least one stored submission for the default program/period)

```bash
curl -sS -X POST "http://127.0.0.1:8000/program-reporting/run" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .
```

**Get review packets**

```bash
curl -sS "http://127.0.0.1:8000/program-reporting/review-packets" | jq .
```

**Get state summary**

```bash
curl -sS "http://127.0.0.1:8000/program-reporting/state-summary" | jq .
```

**Get audit events**

```bash
curl -sS "http://127.0.0.1:8000/audit-events?deployment_id=program_reporting_state_demo" | jq .
```

## Safety note

Program Reporting outputs describe **review readiness** and **blocked uses** (including **no automatic fund release** in contract-shaped payloads). The API adds explicit **pilot-runtime** warnings on ingestion and run completion. **Nothing in this path executes disbursement or replaces authorized finance workflows.**
