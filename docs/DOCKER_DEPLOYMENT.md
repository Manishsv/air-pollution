# Docker deployment (AirOS Core)

This document describes a **Docker-based alternative** to installing Python and dependencies on the host. It is **packaging only**: the same CLI, conformance, supervisor, and registry-driven flood demo you would run from a git clone.

**Maturity note:** this path corresponds to **Level 1** in [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)—a **single image** carrying Core plus reference stacks for quickstart. Agency-grade deployments target **Level 2+** (Core, providers, applications, and adapters as **separate services**); that document explains the target topology without requiring any change to how you build or run this image today.

If you want a minimal multi-container demonstration of the Level 2 topology (Core service + app service + shared deployment/data volumes), see [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md).

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

## Pull from GitHub Container Registry (no git clone)

If you just want to run AirOS without cloning this repository:

```bash
docker pull ghcr.io/manishsv/air-os:latest
docker run --rm ghcr.io/manishsv/air-os:latest doctor
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

## Optional Streamlit dashboard

Expose port **8501** and bind Streamlit to all interfaces:

```bash
docker run --rm -p 8501:8501 air-os:local \
  streamlit run review_dashboard/app.py --server.address=0.0.0.0 --server.port=8501
```

With Compose (profile `dashboard`):

```bash
docker compose --profile dashboard up dashboard
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
