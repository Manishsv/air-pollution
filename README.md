## AirOS — Urban Intelligence Platform

AirOS (Air OS) is a **specs-first, review-oriented urban intelligence platform**. It validates contract-shaped inputs, runs **allowlisted** application builders, stores **records, outputs, runs, validation receipts, and audit trails**, and supports **human review workflows**.

AirOS does **not** automate final government decisions.

### What works today

- **CLI demo path (file outputs)**: fixture demos via `deployments/examples/*`, writing under `data/outputs/deployments/...`
- **Generic Core API pilot runtime**: `POST /records/{contract_key}`, `POST /applications/{application_id}/runs`, `GET /outputs` (plus runs, validation receipts, audit)
- **Review dashboard**: file mode by default; Program Reporting supports optional API mode

### Quick commands

From repo root:

```bash
python tools/airos_cli.py doctor
python tools/airos_cli.py conformance
python tools/airos_cli.py examples list
```

### Documentation map

- **Product model (Core vs Apps vs Adapters)**: [`docs/PRODUCT_MODEL.md`](docs/PRODUCT_MODEL.md)
- **Project status (what’s done vs pilot vs future)**: [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- **Build your first AirOS App (tutorial)**: [`docs/BUILD_YOUR_FIRST_AIR_OS_APP.md`](docs/BUILD_YOUR_FIRST_AIR_OS_APP.md)
- **Start here**: [`docs/START_HERE.md`](docs/START_HERE.md)
- **Pilot runtime quickstart**: [`docs/PILOT_RUNTIME_QUICKSTART.md`](docs/PILOT_RUNTIME_QUICKSTART.md)
- **Core API reference**: [`docs/CORE_API_PILOT.md`](docs/CORE_API_PILOT.md)
- **CLI deployment quickstart**: [`docs/DEPLOYMENT_QUICKSTART.md`](docs/DEPLOYMENT_QUICKSTART.md)
- **Docker single-image**: [`docs/DOCKER_DEPLOYMENT.md`](docs/DOCKER_DEPLOYMENT.md)
- **Docker Compose pilot runtime**: [`docs/DOCKER_COMPOSE_PILOT_RUNTIME.md`](docs/DOCKER_COMPOSE_PILOT_RUNTIME.md)
- **Beginner developer guide**: [`docs/BEGINNER_DEVELOPER_GUIDE.md`](docs/BEGINNER_DEVELOPER_GUIDE.md)
- **Advanced developer guide**: [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)
- **Developer templates**: [`docs/developer_templates/`](docs/developer_templates/)
- **Specs and contracts**: [`specifications/README.md`](specifications/README.md)
- **Interoperability model**: [`docs/INTEROPERABILITY_MODEL.md`](docs/INTEROPERABILITY_MODEL.md)
- **Pilot-ready runtime plan**: [`docs/PRODUCTION_LIKE_AIR_OS_IMPLEMENTATION_PLAN.md`](docs/PRODUCTION_LIKE_AIR_OS_IMPLEMENTATION_PLAN.md)
- **Production readiness checklist**: [`docs/PRODUCTION_READINESS_CHECKLIST.md`](docs/PRODUCTION_READINESS_CHECKLIST.md)
- **Program Reporting use case**: [`docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md`](docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md)
- **Air Pollution local pipeline**: [`docs/AIR_POLLUTION_LOCAL_PIPELINE.md`](docs/AIR_POLLUTION_LOCAL_PIPELINE.md)
- **Agency demo script**: [`docs/AGENCY_DEMO_SCRIPT.md`](docs/AGENCY_DEMO_SCRIPT.md)
- **UI guidelines**: [`docs/UI_GUIDELINES.md`](docs/UI_GUIDELINES.md)

### Legacy `src/` note

The legacy `src/` package has been migrated into `urban_platform/`. Historical notes are in [`specifications/ARCHITECTURE_NOTE.md`](specifications/ARCHITECTURE_NOTE.md).

### Safety posture

AirOS supports **review**. It does **not** authorize or automate fund release, penalties or recovery, emergency orders, demolitions, blacklisting, public disclosure without authorization, or any final government decision. Outputs must be reviewed through authorized human and institutional processes.

