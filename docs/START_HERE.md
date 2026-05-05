# Start Here

## What AirOS is

AirOS is a **specs-first, review-oriented urban intelligence platform**. It validates contract-shaped inputs, runs **allowlisted** application builders, stores outputs and receipts, and supports **human review**.

AirOS is **not production-secure** in this repository configuration (no authentication / RBAC / hardening), and it does **not** automate or authorize final government actions.

## What works today

### CLI demo path (file outputs)

- Deployment config validation
- Allowlisted fixture demos (`deployments/examples/*`)
- Outputs written under `data/outputs/deployments/<deployment_id>/...`
- Dashboard reads outputs in **file mode** by default

Start with:

- [`docs/DEPLOYMENT_QUICKSTART.md`](DEPLOYMENT_QUICKSTART.md)
- [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md) (single-image Docker)

### Generic Core API pilot runtime (API + store)

The generic Core API is a **pilot-runtime** HTTP surface over:

- manifest-backed schema validation
- `FileAirOsStore` (records, outputs, runs, validation receipts, audit events)
- allowlisted application execution

Key endpoints:

- `POST /records/{contract_key}`
- `POST /applications/{application_id}/runs`
- `GET /runs`
- `GET /outputs`
- `GET /validation-receipts`
- `GET /audit-events`
- `GET /contracts/{contract_key}`

Supported verticals (tested end-to-end):

- **Program Reporting** (review packets + state summary)
- **Flood** (multi-input demo)

Start with:

- [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md) (main how-to)
- [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md) (API reference)

### Dashboard

- **File mode (default)**: reads `data/outputs/deployments/...`
- **Program Reporting API mode (optional)**: reads from the Core API `/outputs`

Start with:

- [`docs/PILOT_RUNTIME_QUICKSTART.md`](PILOT_RUNTIME_QUICKSTART.md)
- [`docs/UI_GUIDELINES.md`](UI_GUIDELINES.md) (for dashboard contributors)

## Choose your path

- If you are new: [`docs/BEGINNER_DEVELOPER_GUIDE.md`](BEGINNER_DEVELOPER_GUIDE.md)
- If you want the product model (Core vs Apps vs Adapters): [`docs/PRODUCT_MODEL.md`](PRODUCT_MODEL.md)
- If you want the safe repo restructuring plan (no breaking moves): [`docs/REPO_RESTRUCTURING_PLAN.md`](REPO_RESTRUCTURING_PLAN.md)
- If you want to build/extend the platform: [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) and [`docs/developer_templates/`](developer_templates/)
- If you want Docker:
  - single image: [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)
  - compose stack: [`docs/DOCKER_COMPOSE_PILOT_RUNTIME.md`](DOCKER_COMPOSE_PILOT_RUNTIME.md) (pilot-runtime profile)
- If you want architecture/roadmap:
  - contracts + registries + deployments + federation: [`docs/INTEROPERABILITY_MODEL.md`](INTEROPERABILITY_MODEL.md)
  - container topology (architecture): [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md)
  - implementation sequencing: [`docs/PRODUCTION_LIKE_AIR_OS_IMPLEMENTATION_PLAN.md`](PRODUCTION_LIKE_AIR_OS_IMPLEMENTATION_PLAN.md)
  - product model boundaries: [`docs/PRODUCT_MODEL.md`](PRODUCT_MODEL.md)

## Safety posture (pilot + demo)

AirOS supports **review**. It does **not** authorize or automate:

- fund release
- penalties / recovery
- emergency orders / evacuations
- blacklisting
- public disclosure without authorization
- any final government decision

