# Docker deployment (AirOS Core)

This document describes a **Docker-based alternative** to installing Python and dependencies on the host. It is **packaging only**: the same CLI, conformance, supervisor, and registry-driven flood demo you would run from a git clone.

**Agency / leadership demo:** for a scripted 10–15 minute walkthrough with talking points, see [`docs/AGENCY_DEMO_SCRIPT.md`](AGENCY_DEMO_SCRIPT.md).

**Maturity note:** this path corresponds to **Level 1** in [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)—a **single image** carrying Core plus reference stacks for quickstart. Agency-grade deployments target **Level 2+** (Core, providers, applications, and adapters as **separate services**); that document explains the target topology without requiring any change to how you build or run this image today.

If you want a minimal multi-container demonstration of the Level 2 topology (Core service + app service + shared deployment/data volumes), see [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md).

## 5-minute Docker quickstart (GHCR)

You only need Docker (no local Python). Create a host folder for outputs, pull the image, run health checks, run the built-in flood demo, and list the JSON artifacts.

```bash
mkdir -p airos-data

docker pull ghcr.io/manishsv/air-os:latest

docker run --rm ghcr.io/manishsv/air-os:latest doctor

docker run --rm ghcr.io/manishsv/air-os:latest conformance

docker run --rm \
  -v "$(pwd)/airos-data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment run deployments/examples/flood_local_demo

find airos-data/outputs/deployments/flood_local_demo -maxdepth 1 -type f | sort
```

**Mounts:** the flood demo writes under `/app/data` in the container. Mount a host directory to `airos-data` (or any path you choose) so outputs survive after the container exits. Deployment YAML for the built-in example lives inside the image under `/app/deployments/examples/…`; you do not need to mount it for this quick path.

## What you should see

- **`doctor`:** prints Python/platform, detected repo root (`/app`), and checks that key specification and deployment example folders are present.
- **`conformance`:** runs the full specification conformance step (`main.py --step conformance`); on success it writes `conformance_report.json` under the mounted data volume (e.g. `airos-data/outputs/conformance_report.json`).
- **Flood demo (`deployment run deployments/examples/flood_local_demo`):** writes fixture-driven, contract-shaped outputs under `airos-data/outputs/deployments/flood_local_demo/`:
  - `flood_risk_dashboard_payload.json`
  - `flood_decision_packets.json`
  - `flood_field_verification_tasks.json`
  - `deployment_run_summary.json`
- **Program Reporting demo (optional):** after running `deployment run deployments/examples/program_reporting_state_demo` (either from source or in Docker), the dashboard will show a **Program Reporting** tab that renders:
  - `fund_release_review_packets.json`
  - `state_program_summary.json`
  - `deployment_run_summary.json`
- **Dashboard (next section):** after you have run the demo (or any pipeline that writes artifacts), open **http://localhost:8501** while the Streamlit container is running.

## Run the dashboard from Docker

The published image uses an **AirOS CLI entrypoint** (`python tools/airos_cli.py`). To run Streamlit, **override the entrypoint** so Docker invokes `streamlit` directly.

```bash
docker run --rm \
  -p 8501:8501 \
  -v "$(pwd)/airos-data:/app/data" \
  --entrypoint streamlit \
  ghcr.io/manishsv/air-os:latest \
  run review_dashboard/app.py --server.address=0.0.0.0 --server.port=8501
```

Then open **http://localhost:8501** in a browser.

- **Optional — Program Reporting tab via generic Core API instead of baked-in `data/outputs/deployments/program_reporting_state_demo/` files:** expose the API (separate terminal or Compose service), then launch Streamlit with  
  `-e AIROS_DASHBOARD_DATA_MODE=api -e AIROS_API_BASE_URL=http://host.docker.internal:8000` (or another reachable Core API URL). Prerequisites and curl flow are documented in [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md).

- **Keep the terminal running** while you use the dashboard; stopping the container stops the UI.
- Use **`docker ps`** to confirm the container is up and that port **8501** is published (`0.0.0.0:8501->8501/tcp`).
- **`--entrypoint streamlit` is required** with the default image; without it, Docker would pass `run review_dashboard/...` to the CLI instead of to Streamlit.

Mount the same **`airos-data`** (or your chosen host folder) to **`/app/data`** so the dashboard can read persisted outputs (e.g. GeoJSON, parquet, decision packets) written by earlier runs.

## Initialize your own flood deployment from the runnable example

To work with a **copy** of the runnable example under a mounted host tree (validate/edit/run without touching the in-image example), use `deployment init --from-example`. Outputs use your **`deployment_id`** (here: `demo_city_flood`).

```bash
rm -rf airos-runtime
mkdir -p airos-runtime/deployments airos-runtime/data

docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment init \
    --from-example flood_local_demo \
    --deployment-id demo_city_flood \
    --deployment-name "Demo City Flood" \
    --output-dir deployments/local/demo_city_flood \
    --force

docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment validate deployments/local/demo_city_flood

docker run --rm \
  -v "$(pwd)/airos-runtime/deployments:/app/deployments/local" \
  -v "$(pwd)/airos-runtime/data:/app/data" \
  ghcr.io/manishsv/air-os:latest \
  deployment run deployments/local/demo_city_flood

find airos-runtime/data/outputs/deployments/demo_city_flood -maxdepth 1 -type f | sort
```

**Why two mounts:** `deployments/local/…` holds your copied registry YAML; `data` holds runtime and conformance outputs. Do not put secrets in either tree for public demos.

## Troubleshooting

- **Dashboard site cannot be reached**
  - Confirm the **`docker run`** that starts Streamlit is **still running** (foreground terminal).
  - Include **`-p 8501:8501`** so the host can reach the server.
  - Include **`--entrypoint streamlit`** as shown above.
  - Run **`docker ps`** and look for a mapping like `0.0.0.0:8501->8501/tcp`.

- **`deployment init: error: unrecognized arguments: --from-example`** (or flag not found)
  - Your image may be old; **`docker pull ghcr.io/manishsv/air-os:latest`** again.
  - If needed: `docker image rm ghcr.io/manishsv/air-os:latest` then pull again.

- **`no matching manifest for linux/arm64/v8`** (Apple Silicon)
  - The published image is **multi-arch** (`linux/amd64` and `linux/arm64`); **`docker pull`** again to refresh manifests.

- **Flood outputs missing on the host**
  - Pass **`-v "$(pwd)/<folder>:/app/data"`** so writes under `/app/data/outputs/...` land on your machine.

- **Permission errors on mounted folders**
  - **`mkdir -p`** the host directories **before** `docker run` so Docker creates the mount with predictable ownership.

## Why this matters for developers

- You can **see AirOS running without installing Python** or geo stack packages on the host.
- You can run a **governed, registry-driven** flood demo with **fixture-only** data and inspect **contract-shaped** JSON outputs.
- From there you can decide whether to **clone the repo** for deeper work, or **mount source** into a container for iterative development—without treating the Docker image as a substitute for specs and conformance on your branch.

## When to use Docker

- You want a **reproducible environment** (Python 3.11 + geo/OpenCV system libs) without managing a local venv.
- You are **evaluating or CI-prototyping** AirOS Core on a clean machine.
- You prefer **isolated runs** (`docker run --rm`) for doctor, conformance, review, or the flood fixture demo.

**Not covered here:** hardened production images, multi-service orchestration, secrets management, or Kubernetes manifests. Those belong in a deployment-specific repo or platform layer built on top of this image pattern.

## What the image contains

- **Base:** `python:3.11-slim-bookworm`
- **System packages:** GDAL/GEOS/PROJ and related libraries (aligned with CI) so `geopandas` / `osmnx` / wheels that need native deps can install reliably.
- **Python:** `requirements-docker.txt` (same Core stack as `requirements.txt` but **without** `opencv-python` / `ultralytics`, which pull a very large PyTorch + CUDA dependency tree) plus **pytest** (pytest is not listed in `requirements.txt`; it is installed in the image for parity with CI and local test runs inside the container). The image still copies `requirements.txt` first for transparency and layer-cache alignment.

**Optional / not in this image:** camera publisher flows that need OpenCV + Ultralytics YOLO. Use a full local `pip install -r requirements.txt` or extend the Dockerfile for those paths.

**Not baked in:** API keys, mailbox passwords, private deployment YAML, or city-specific operational data. Mount those at runtime only if you have a private workspace; never commit secrets into the image build context.

## Build

From the repository root:

```bash
docker build -t air-os:local .
```

Or with Compose:

```bash
docker compose build
```

## Health check (doctor)

```bash
docker run --rm air-os:local doctor
```

With conformance as part of the supervisor step:

```bash
docker run --rm air-os:local doctor --run-conformance
```

## Conformance

```bash
docker run --rm air-os:local conformance
```

## AI supervisor review

```bash
docker run --rm air-os:local review --run-conformance
```

## Registry-driven flood demo (fixtures only)

```bash
docker run --rm air-os:local deployment run deployments/examples/flood_local_demo
```

### Persist outputs on the host

By default, generated artifacts go under `data/` inside the container filesystem and are discarded when the container exits unless you mount a volume:

```bash
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  air-os:local \
  deployment run deployments/examples/flood_local_demo
```

Conformance reports and other outputs written under `/app/data/outputs` will then appear in your host `./data/outputs`.

## Mount a private deployment workspace

If you maintain deployment registries outside the public repo, mount them read-only and point the CLI at the mounted path (relative to `/app` if you mount under `/app`, or use absolute paths inside the container):

```bash
docker run --rm \
  -v "$(pwd)/my_private_deployments:/deployments:ro" \
  air-os:local \
  python tools/deployment_runner/validate_deployment.py --deployment /deployments/demo_city
```

Adjust paths to match how you organize private configs.

## Optional Streamlit dashboard (local image / Compose)

For the **default CLI entrypoint** image (including `ghcr.io/manishsv/air-os:latest`), use the **Run the dashboard from Docker** section above (`--entrypoint streamlit`).

If you built **`air-os:local`** from this repo with the same Dockerfile, the same override applies:

```bash
docker run --rm -p 8501:8501 \
  -v "$(pwd)/airos-data:/app/data" \
  --entrypoint streamlit \
  air-os:local \
  run review_dashboard/app.py --server.address=0.0.0.0 --server.port=8501
```

With Compose (profile `dashboard`; the service runs Streamlit directly—no entrypoint override needed in that YAML):

```bash
docker compose --profile dashboard up --build review-dashboard
```

## Avoiding secrets in images and build context

- Do **not** copy `.env` files with real credentials into the image (`.dockerignore` excludes `.env`).
- Do **not** `COPY` private deployment repos into the build context; mount them at runtime.
- Prefer **deployment-local** secret stores and `configuration_ref`-style indirection (see `deployments/templates/`).

## Limitations of the current image

- **Single-container, developer-oriented:** not a production HA setup.
- **Architecture:** prebuilt wheels differ between `linux/amd64` and `linux/arm64`; if `docker build` fails on one architecture, try `docker build --platform linux/amd64` (where supported) or adjust system packages for your base.
- **Resource use:** conformance, tests, and ML/geo dependencies can be heavy; allocate sufficient RAM/disk for pip installs.
- **`xgboost` wheels on Linux** may still pull an `nvidia-nccl-*` helper package (much smaller than the full PyTorch stack removed with `requirements-docker.txt`). The image remains suitable for Core workflows; GPU is not assumed at runtime.
- **Conformance vs host:** on a pristine container without mounted `data/outputs`, some manifest/runtime artifact checks may not run compared to a host that already generated outputs; mount `./data` if you want parity with local artifact-backed checks.

## Relationship to future production / Kubernetes

This Dockerfile is a **reference runnable image** for AirOS Core workflows (CLI + conformance + demos). Production deployments typically:

- Build from a locked base image in CI
- Inject config via ConfigMaps/Secrets and volumes (not `COPY` of secrets)
- Run separate services for APIs, workers, and dashboards
- Use the same **specs + conformance** gates before promoting images

Treat this path as the **first Docker stepping stone**, not the final production topology. For the **multi-container target** (Core vs providers vs applications vs adapters vs dashboard) and **maturity levels 0–4**, see [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md).
