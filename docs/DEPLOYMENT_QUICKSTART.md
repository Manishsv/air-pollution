# Deployment quickstart (AirOS Core — clean machine test)

This quickstart is a **clean-machine sanity check** for AirOS Core using a **registry-driven local flood demo** (`deployments/examples/flood_local_demo`) with **fixture data only**.

It is designed to help another engineer clone the repo, install dependencies, run health checks, execute the flood local deployment, and understand how AirOS Core can be **configured** with deployment-scoped registries (providers + applications) without any external integrations.

## 1) Purpose

- Validate that **AirOS Core** installs and passes tests/conformance in a fresh environment.
- Run a **controlled** “AirOS Core + configured providers + configured applications” demo for `flood_risk` using only `specifications/examples/flood/` fixtures.
- Produce contract-shaped outputs and validate them against consumer contracts.

## 2) Prerequisites

- Git
- Python **3.11** preferred (3.10+ may work, but 3.11 is the reference in CI)
- `pip` and `venv`
- Optional system dependencies if geospatial wheels fail to install (Linux/macOS):
  - GDAL/GEOS/PROJ build deps (see `.github/workflows/ci.yml` for a known-good Ubuntu package list)

## 3) Fresh clone setup

```bash
git clone https://github.com/Manishsv/air-os.git
cd air-os

python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt pytest
```

If `python3.11` is unavailable:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt pytest
```

## 4) Run core health checks

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance
```

CLI equivalents:

```bash
python tools/airos_cli.py conformance
python tools/airos_cli.py review --run-conformance
```

Expected result:

- **tests pass**
- **conformance exits 0** and writes `data/outputs/conformance_report.json`
- **supervisor exits 0**

## 5) Run the registry-driven flood deployment demo

```bash
python tools/deployment_runner/validate_deployment.py --deployment deployments/examples/flood_local_demo
python tools/deployment_runner/run_deployment.py --deployment deployments/examples/flood_local_demo
```

CLI equivalents:

```bash
python tools/airos_cli.py deployment validate deployments/examples/flood_local_demo
python tools/airos_cli.py deployment run deployments/examples/flood_local_demo
```

This reads:

- `deployments/examples/flood_local_demo/deployment_profile.yaml`
- `deployments/examples/flood_local_demo/provider_registry.yaml`
- `deployments/examples/flood_local_demo/application_registry.yaml`

And then runs configured **fixture providers** + configured **flood application outputs** using an **explicit allowlist** (not arbitrary plugin loading).

## 6) Inspect generated outputs

```bash
find data/outputs/deployments/flood_local_demo -maxdepth 1 -type f | sort
cat data/outputs/deployments/flood_local_demo/deployment_run_summary.json
```

Expected files:

- `flood_risk_dashboard_payload.json`
- `flood_decision_packets.json`
- `flood_field_verification_tasks.json`
- `deployment_run_summary.json`

## 7) Run conformance again

```bash
python main.py --step conformance
```

## 8) Optional dashboard

```bash
streamlit run review_dashboard/app.py
```

## 9) What this proves

- AirOS Core can be **cloned and checked** independently (tests + conformance + supervisor).
- A deployment can select providers through **`provider_registry.yaml`** (fixtures here).
- A deployment can select consumers/applications through **`application_registry.yaml`** (dashboard payloads, packets, field tasks).
- The flood demo uses **fixtures only**; **no external APIs** or agency integrations are required.
- This is **not** full dynamic plugin loading yet—no arbitrary imports from user-provided registry strings.

## 10) How to adapt the demo (forward deployment safety)

- Copy `deployments/examples/flood_local_demo/` into a **private deployment** folder/repo.
- Change `deployment_id` and labels first.
- Only later replace `fixture_path` entries with **authorized** provider inputs and contracts.
- **Do not commit** secrets, API keys, credentials, mailbox passwords, restricted datasets, or sensitive city/agency operational profiles into the public AirOS repository.

## 11) Troubleshooting

- **`No module named pytest`**: ensure you activated the venv and installed pytest: `pip install pytest` (or `python -m pip install pytest`).  
- **Geospatial dependency install fails**: install system packages (GDAL/GEOS/PROJ). On Ubuntu, mirror `.github/workflows/ci.yml` packages.  
- **Conformance fails**: open `data/outputs/conformance_report.json` and search for `invalid` entries; fix schema/example registration issues first.  
- **Deployment output missing**: ensure the demo ran from repo root and the deployment path is correct; confirm fixture files exist under `specifications/examples/flood/`.  
- **Dashboard fails to start**: `pip install streamlit` (already in requirements) and rerun; check port conflicts; run `streamlit run review_dashboard/app.py` from repo root.

