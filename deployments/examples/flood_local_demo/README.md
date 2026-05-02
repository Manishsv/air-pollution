# Flood local demo — registry-driven deployment POC (fixtures only)

This is a **minimal proof of concept** showing:

**AirOS Core + deployment-scoped registries (providers + applications) → runnable vertical slice**

It is **not** a general plugin runtime. The runner uses an **explicit allowlist** of safe functions and does **not** dynamically import arbitrary registry strings.

## Run

From repo root:

```bash
python tools/deployment_runner/run_deployment.py --deployment deployments/examples/flood_local_demo
```

Outputs are written to:

- `data/outputs/deployments/flood_local_demo/`

## What it does

- Reads:
  - `deployment_profile.yaml`
  - `provider_registry.yaml`
  - `application_registry.yaml`
- Uses fixture JSON under `specifications/examples/flood/`:
  - rainfall observations
  - flood incidents
  - drainage assets
- Runs flood scaffolding end-to-end:
  - ingest fixtures → feature rows → dashboard payload → decision packets → field tasks
- Validates generated outputs against consumer contracts.

## Safety / scope

- **Fixture/demo data only**
- **Decision support only**
- **Field verification required**
- **No emergency orders**
