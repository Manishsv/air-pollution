# Docker Compose — Pilot runtime stack (Core API + dashboard)

This document describes the **pilot-runtime Docker Compose path** for developers:

- `airos-core-api` (generic Core API, pilot-runtime only)
- `review-dashboard-api` (Streamlit dashboard in API mode)
- shared `./data` volume (store + outputs)

**This is packaging/orchestration only.** It is **not** production deployment guidance.

Related:

- Single-image Docker (Level 1): [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)
- Pilot runtime walkthrough (curl + dashboard): [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md)
- Target container topology (architecture): [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)

---

## Services (pilot-runtime profile)

Defined in `docker-compose.yml`:

- **`airos-core-api`**
  - **Purpose**: Core API (pilot-runtime only)
  - **Port**: `8000:8000`
- **`review-dashboard-api`**
  - **Purpose**: Streamlit dashboard in **API mode**
  - **Port**: `8501:8501`
  - **Connects to**: `http://airos-core-api:8000` inside Compose

Shared host mounts:

- `./data:/app/data`
- `./deployments:/app/deployments`

---

## Commands

Validate config:

```bash
docker compose --profile pilot-runtime config
```

Start stack:

```bash
docker compose --profile pilot-runtime up --build
```

Health:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Program Reporting smoke (API + dashboard)

Run these from the **repo root** (so `--data @specifications/...` paths resolve on the host).

Submit records:

```bash
curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission.sample.json

curl -X POST http://127.0.0.1:8000/records/consumer_city_program_submission \
  -H "Content-Type: application/json" \
  --data @specifications/examples/program_reporting/city_program_submission_city_b.sample.json
```

Run allowlisted application:

```bash
curl -X POST http://127.0.0.1:8000/applications/program_reporting_review_packet/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"program_reporting_state_demo","program_id":"stormwater_resilience_grant_2026","reporting_period":"2026_Q1"}'
```

Inspect:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_fund_release_review_packet"
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_program_reporting_state_summary"
```

Open dashboard:

- `http://127.0.0.1:8501`

## Optional Flood smoke (API)

Submit fixtures:

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

Run:

```bash
curl -X POST http://127.0.0.1:8000/applications/flood_risk_dashboard_payload/runs \
  -H "Content-Type: application/json" \
  -d '{"deployment_id":"flood_local_demo"}'
```

Inspect:

```bash
curl "http://127.0.0.1:8000/outputs?contract_key=consumer_flood_risk_dashboard"
```

Open dashboard (API mode):

- `http://127.0.0.1:8501`  
  The Flood panel will read Core API outputs when `AIROS_DASHBOARD_DATA_MODE=api` (as configured in the Compose service).

Tear down:

```bash
docker compose down
```

---

## Safety note

This Compose path is **pilot-runtime only**. It is **not production-secure** and does **not** automate fund release, enforcement, emergency orders, or final government decisions.

