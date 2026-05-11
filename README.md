# AirOS — Urban Intelligence Platform

AirOS maps 14 environmental and infrastructure domains to a H3 hexagonal city grid, runs LLM-backed cross-domain risk analysis per cell, and surfaces human-reviewed decision support to ward officers and engineers.

---

## Components

| Component | What it does | Status |
|-----------|-------------|--------|
| AirOS Core (the OS) | H3 knowledge store, rules registry, scheduler | Live |
| AirOS Data Sources (Drivers) | 14 domain connectors (air, heat, flood, water, fire, noise, construction, green, waste, weather, buildings, roads, drains, crowd) | Live |
| AirOS Decision Support (App) | H3 Expert Agent, City Pattern Agent, Review Dashboard | Live |
| AirOS Network | Cross-instance communication | Spec only |

---

## Quick start

```bash
git clone <repo-url> && cd AirStack
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add LLM_API_KEY and any overrides
streamlit run airos/network/dashboard/app.py
```

---

## Documentation

| Topic | File |
|-------|------|
| Getting started | GETTING_STARTED.md |
| Configuration | docs/developer/CONFIGURATION.md |
| Add a data source | docs/developer/ADD_DATA_SOURCE.md |
| Build a decision support app | docs/developer/BUILD_YOUR_FIRST_AIR_OS_APP.md |
| Platform overview and architecture | docs/platform/OVERVIEW.md |
| Intelligence methodology | docs/platform/INTELLIGENCE_METHODOLOGY.md |
| AirOS Network | docs/platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md |
| Deployment quickstart | docs/developer/DEPLOYMENT_QUICKSTART.md |

---

## Project layout

```
AirStack/
├── airos/                 # Five-layer Python implementation
│   ├── os/                #   Runtime: storage, SDK, specs, standards, config, scheduling
│   ├── apps/              #   Domain logic: air, heat, flood, water, fire, noise, … (10 apps)
│   ├── agents/            #   AI agents: H3 Expert, City Pattern, LLM client
│   ├── drivers/           #   Data integration: connectors, H3 store, processing, feature/obs stores
│   └── network/           #   External surfaces: dashboard (Streamlit), REST API, CLI
├── specifications/        # Machine-readable contracts — JSON schemas, YAML domain specs
├── agentic/               # Agentic loop framework (to be extracted to its own repo)
├── spec/                  # Narrative design docs (what the platform must do and why)
├── docs/                  # Human-readable documentation
│   ├── developer/         #   Guides: getting started, building drivers/apps
│   ├── platform/          #   Architecture, vision, methodology
│   └── apps/              #   App-layer walkthroughs
├── deployments/           # City deployment configs and examples
├── examples/              # SDK walkthrough scripts
├── scripts/               # Migration and maintenance scripts
├── tests/                 # Test suite (883 tests)
└── data/                  # Local data files (store, outputs, config)
```

> **Note:** `urban_platform/` is kept as a backward-compatibility shim — old imports still work but new code should use `airos.*`.

---

## Safety posture

AirOS produces human-reviewed decision support — every output carries confidence scores, hypothesis chains, and "when not to act" guidance for officer review. It does not automate government decisions, authorise fund release, issue penalties, or initiate any final administrative action.
