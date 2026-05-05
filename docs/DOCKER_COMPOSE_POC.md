# Docker Compose POC — Level 2 AirOS multi-container node

This document describes a **minimal Docker Compose proof-of-concept** that demonstrates the **future Level 2 topology** of an AirOS node using the **current repo runtime** (CLI + registries + flood demo).

**This is packaging/orchestration only.** It is **not** production deployment guidance.

Related:

- Single-image Docker usage (Level 1), including **GHCR quickstart**, **`--from-example`** init, and **dashboard via `--entrypoint streamlit`**: [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)
- Target multi-container architecture (Levels 0–4): [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)

**Note:** If you only need a quick demo on a laptop, start with the single-image flow in [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md). This Compose file is for proving **service topology** and shared volumes.

---

## 1) Purpose

This Compose stack demonstrates a small slice of the Level 2 topology:

- AirOS Core can be packaged as a service.
- A domain/application workload can run as a separate service.
- Both share the same **deployment registries** and a shared **data/output** volume.

It does **not** introduce:

- plugin loading
- external provider services
- email / network transport adapters
- secrets, credentials, or real deployment profiles

---

## 2) Services

Defined in `docker-compose.yml`:

- **`airos-core`**
  - **Purpose**: Core health/conformance/supervisor layer (represented as short-running CLI commands in this POC).
  - **Default command**: `doctor` (image `ENTRYPOINT` is the AirOS CLI)
- **`airos-core-api`** (pilot-runtime profile)
  - **Purpose**: Long-running **generic Core API** (pilot-runtime only).
  - **Enabled**: only when using the `pilot-runtime` profile.
  - **Port**: `8000:8000`
- **`flood-demo-app`**
  - **Purpose**: A domain/application workload consuming AirOS-compatible deployment configuration.
  - **Default command**: `deployment run deployments/examples/flood_local_demo` (via CLI `ENTRYPOINT`)
- **`review-dashboard`** (optional)
  - **Purpose**: Streamlit review UI reading the shared outputs.
  - **Enabled**: only when using the `dashboard` profile.
  - **Port**: `8501:8501`
- **`review-dashboard-api`** (pilot-runtime profile)
  - **Purpose**: Streamlit review UI in **API data mode** (reads outputs from `airos-core-api`).
  - **Enabled**: only when using the `pilot-runtime` profile.
  - **Port**: `8501:8501`

---

## 3) Shared volumes

Both `airos-core` and `flood-demo-app` mount the same host directories:

- **Deployment configuration**: `./deployments:/app/deployments`
- **Shared data + outputs**: `./data:/app/data`

This ensures artifacts written under `/app/data/outputs/...` persist to your host filesystem.

---

## 4) Commands

### Validate Compose config

```bash
docker compose config
```

### Build and run all (default commands)

```bash
docker compose up --build
```

### Run only AirOS Core doctor

```bash
docker compose run --rm airos-core doctor
```

### Run conformance

```bash
docker compose run --rm airos-core conformance
```

### Run supervisor

```bash
docker compose run --rm airos-core review --run-conformance
```

### Run flood demo

```bash
docker compose run --rm flood-demo-app
```

### Optional dashboard

The `review-dashboard` service runs **Streamlit as the container command** (not via the CLI entrypoint), so no `--entrypoint` override is needed here. For **`docker run`** on the GHCR image, see [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md) (**Run the dashboard from Docker**).

```bash
docker compose --profile dashboard up --build review-dashboard
```

### Pilot runtime (Core API + dashboard in API mode)

This profile runs:

- `airos-core-api` (FastAPI via Uvicorn) on **port 8000**
- `review-dashboard-api` (Streamlit in API mode) on **port 8501**

Start:

```bash
docker compose --profile pilot-runtime up --build
```

Health:

```bash
curl http://127.0.0.1:8000/health
```

For the end-to-end record ingestion + application run + dashboard flow (Program Reporting + Flood), see [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md).

---

## 5) Expected outputs

After a flood demo run, these files should be written under:

`data/outputs/deployments/flood_local_demo/`

- `flood_risk_dashboard_payload.json`
- `flood_decision_packets.json`
- `flood_field_verification_tasks.json`
- `deployment_run_summary.json`

Inspect:

```bash
find data/outputs/deployments/flood_local_demo -maxdepth 1 -type f | sort
```

---

## 6) Tear down

```bash
docker compose down
```

---

## 7) What this proves

- AirOS Core can be packaged as a service (via CLI entrypoints today).
- A domain/application workload can run as a separate service container.
- Both containers can share deployment registries and output volumes.
- The deployment registry model works in a multi-container topology without changing domain semantics.

---

## 8) What this does not prove yet

- independent provider service runtime
- dynamic plugin loading
- cross-node federation
- email/network adapter runtime
- production secrets/security
- Kubernetes readiness

---

## 9) Future path (incremental)

- Promote `airos-core` from “CLI command runner” into a long-running API service.
- Add a minimal fixture/file provider service that validates provider contracts and writes canonical objects via Core ingestion.
- Split a flood application service that reads from Core APIs rather than running in-process.
- Add dashboard service wiring and contract-shaped APIs.
- Add a network adapter service (envelopes/receipts only).
- Introduce production-grade secrets and config management and later a Kubernetes/Helm projection.

---

## 10) Testing expectations (repo-level)

Always run on the host:

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance
```

If Docker is available:

```bash
docker compose config
docker compose run --rm airos-core doctor
docker compose run --rm airos-core conformance
docker compose run --rm flood-demo-app
```

