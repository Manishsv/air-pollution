# Pilot Runtime Quickstart — Core API → Program Reporting dashboard (API mode)

## Purpose

This quickstart walks the **pilot-runtime path** end-to-end:

**generic records API** → **allowlisted application run API** → **outputs API** → **Streamlit dashboard in API mode**.

It uses **Program Reporting** as the first vertical slice, but the HTTP surface is **generic** (no Program Reporting-specific routes are required).

## What this is and is not

This is:

- **Local pilot-runtime demo** for developers
- **Generic Core API flow** over `FileAirOsStore`
- **Program Reporting** as the **first exercised** application slice
- **Review-support only** (human-gated)

This is not:

- Production-secure (no auth, no RBAC, no Internet hardening)
- Fund release automation
- Finance / treasury integration
- Signed cross-agency messaging / participant directory
- A replacement for the file-based deployment runner demo paths

## Prerequisites

- You are in the **repo root** (`AirPollution/`)
- Python environment is set up and dependencies are installed
- Optional health checks (recommended):

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance
```

## Docker Compose option (recommended for pilot-runtime DX)

If you want the Core API and the dashboard together in one command (shared `./data` volume):

```bash
docker compose --profile pilot-runtime up --build
```

Then use the same `curl` commands below, but you can skip the “start Core API” / “start dashboard” steps.

## 1) Start with a clean store

```bash
rm -rf data/store/api
```

## 2) Start Core API

```bash
AIROS_STORE_DIR=data/store/api \
uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
```

Keep this terminal running.

## 3) Health check

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","service":"airos-core","mode":"pilot-runtime"}
```

## 3b) (Optional) Contract discovery (what shape to POST)

Use this if you want to inspect the JSON schema before posting data:

```bash
curl http://127.0.0.1:8000/contracts/consumer_city_program_submission
curl http://127.0.0.1:8000/contracts/consumer_fund_release_review_packet
```

## 4) Submit Program Reporting records (generic records endpoint)

Run these from the **repo root** (so `--data @specifications/...` paths resolve).

City A:

```bash
curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission.sample.json
```

City B:

```bash
curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission_city_b.sample.json
```

## 5) Run the allowlisted application (generic applications endpoint)

```bash
curl -X POST http://127.0.0.1:8000/applications/program_reporting_review_packet/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"program_reporting_state_demo","program_id":"stormwater_resilience_grant_2026","reporting_period":"2026_Q1"}'
```

Expected:

- `status`: `completed`
- `records_processed`: 2
- `outputs_generated`: 3
- `warnings` reiterate pilot posture and no disbursement automation

## 6) Inspect run metadata (generic runs endpoint)

List:

```bash
curl http://127.0.0.1:8000/runs
```

Filter:

```bash
curl "http://127.0.0.1:8000/runs?deployment_id=program_reporting_state_demo"
curl "http://127.0.0.1:8000/runs?application_id=program_reporting_review_packet"
curl "http://127.0.0.1:8000/runs?status=completed"
```

Inspect one (use `run_id` from the application response or from the list):

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

Runs are **pilot-runtime metadata**: they summarize what ran, when, counts, inputs/outputs, and warnings. For the detailed trail, use `GET /audit-events`.

## 7) Inspect outputs (generic outputs endpoint)

State summary:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=internal_program_reporting_state_summary_demo"
```

Review packets:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet"
```

## 8) Inspect audit events

```bash
curl http://127.0.0.1:8000/audit-events
```

You should see actions such as:

- `record_ingested`
- `application_run_started`
- `output_generated`
- `application_run_completed`

## 9) Start the dashboard in API mode

In a new terminal (repo root):

```bash
AIROS_DASHBOARD_DATA_MODE=api \
AIROS_API_BASE_URL=http://127.0.0.1:8000 \
streamlit run review_dashboard/app.py
```

Open the Streamlit UI and navigate to the **Program Reporting** tab.

## Expected result

- The **Program Reporting** tab loads data from the **Core API** (not from `data/outputs/deployments/...`).
- City Demo A should be **ready for authorized review** if the fixture is in the “healthy” range.
- City Demo B should **need clarification** (progress delay + low utilization in the fixture).
- **No fund release is automated** (review support only; authorized finance processes remain outside AirOS).

## Troubleshooting

- **`curl: (26) Failed to open/read local data from file/application`**:
  - You likely ran `curl --data @specifications/...` from the wrong directory. `cd` to the repo root and retry.
- **Outputs are empty**:
  - Make sure you ran the application call: `POST /applications/program_reporting_review_packet/runs`.
  - Clear the store (`rm -rf data/store/api`) and re-run the flow if you suspect mixed old data.
- **Dashboard in API mode shows empty state**:
  - Confirm Core API is running at `AIROS_API_BASE_URL` and reachable from the machine running Streamlit.
  - Confirm the output-producing steps were completed (record ingestion + application run).
- **Both cities need clarification**:
  - If City A’s fixture is below the progress threshold, it will also be flagged. Check `overall_progress_pct` in `specifications/examples/program_reporting/city_program_submission.sample.json`.

## Relationship to existing demo paths

- **Deployment runner (file mode)** still exists and remains the default: it writes JSON under `data/outputs/deployments/...` and the dashboard can read those files without any API.
- **Docker CLI demos** still exist for packaging/orchestration demos.
- **Pilot runtime** is the **API + store** path: ingest records → run allowlisted application → read outputs/audit → optionally render the dashboard in API mode.

## Optional: Flood through the generic Core API

Flood is the second vertical slice for the generic API and demonstrates **multi-input** runs.

1) POST the three flood provider fixtures (use `?deployment_id=flood_local_demo` if you want to keep the scope separate from Program Reporting):

```bash
curl -X POST "http://127.0.0.1:8000/records/provider_rainfall_observation_feed?deployment_id=flood_local_demo" \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/rainfall_observation.sample.json

curl -X POST "http://127.0.0.1:8000/records/provider_flood_incident_feed?deployment_id=flood_local_demo" \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/flood_incident.sample.json

curl -X POST "http://127.0.0.1:8000/records/provider_drainage_asset_feed?deployment_id=flood_local_demo" \
  -H "Content-Type: application/json" \
  --data @specifications/examples/flood/drainage_asset.sample.json
```

2) Run:

```bash
curl -X POST http://127.0.0.1:8000/applications/flood_risk_dashboard_payload/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"flood_local_demo"}'
```

3) Fetch:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_flood_risk_dashboard"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_flood_decision_packet"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_field_verification_task"
```

Safety note: **review support only**; **no emergency or evacuation orders** are issued; **field verification remains required**.

