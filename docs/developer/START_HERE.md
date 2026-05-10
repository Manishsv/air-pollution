# Start Here — AirOS Developer Orientation

## What is AirOS?

AirOS is an open urban intelligence platform built for city teams, civic-tech developers, and researchers. It ingests data from sensors, weather forecasts, and satellites across 14 urban domains, maps it onto an H3 hexagonal grid (resolution 8, roughly 0.74 km² per cell), runs LLM-backed agents that synthesise signals across domains for each cell, and surfaces structured observations through a review dashboard. AirOS is designed to inform human decision-making — it produces reviewed outputs, not automated government actions.

---

## Four Components

### 1. AirOS Core (the OS)

The runtime platform that everything else depends on.

| | |
|---|---|
| **What it does** | Manages the H3 Knowledge Store (SQLite, WAL mode), a configurable Rules Registry for per-domain thresholds, a Scheduler that orchestrates ingest and agent sweeps, and a conformance layer that validates data before it enters the store. |
| **Where it lives** | `urban_platform/h3_knowledge/`, `urban_platform/rules/`, `urban_platform/scheduler.py` |
| **Extending it** | Add new threshold rules to the Rules Registry; adjust scheduler cadence via environment variables; extend the conformance layer to enforce new data contracts. |

### 2. AirOS Data Sources (Drivers)

The connectors and ingestors that bring data in.

| | |
|---|---|
| **What it does** | Pulls data from OpenMeteo (weather + AQ forecast, no key needed), AQICN (real sensor data, optional), and Google Earth Engine (satellite-derived heat, flood, green layers, optional). Per-domain ingestors normalise raw data to H3 cells and write it to the Knowledge Store. 14 domains are supported: air, flood, heat, water, fire, noise, construction, green, waste, weather, buildings, roads, drains, crowd. |
| **Where it lives** | `urban_platform/h3_knowledge/*_ingestor.py` (per-domain ingestors), `urban_platform/connectors/` (raw connectors: air_quality, weather, satellite, heat, flood, geospatial, camera) |
| **Extending it** | Add a new `*_ingestor.py` following the existing pattern, register it in the scheduler, and define its thresholds in the Rules Registry. See [Add a Data Source](ADD_DATA_SOURCE.md). |

### 3. AirOS Decision Support System (the App)

The intelligence and review layer.

| | |
|---|---|
| **What it does** | An H3 Expert Agent (LLM-backed, cell-level) reads all domain signals for a given H3 cell and produces a structured cross-domain observation. A City Pattern Agent sweeps the highest-risk cells and writes a city-level summary. A Streamlit review dashboard presents all of this to analysts. |
| **Where it lives** | `urban_platform/agents/` (H3 Expert Agent, City Pattern Agent), `review_dashboard/` (Streamlit app) |
| **Extending it** | Add new agent types in `urban_platform/agents/`; build new dashboard panels in `review_dashboard/`; swap or fine-tune the LLM via environment variables without touching agent code. See [Build Your First AirOS App](BUILD_YOUR_FIRST_AIR_OS_APP.md). |

### 4. AirOS Network

Cross-instance communication between AirOS deployments.

| | |
|---|---|
| **What it does** | Defines a domain-agnostic contract envelope that allows AirOS deployments (e.g. a city and its watershed authority) to route structured observations to each other without tight coupling. |
| **Where it lives** | Specification only — see [Federated Deployment Architecture](../platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md) |
| **Extending it** | The specification is complete. Runtime implementation has not yet been built. Contributions welcome. |

---

## Choose Your Path

| I want to… | Go here |
|---|---|
| Run AirOS for the first time | [GETTING_STARTED.md](../../GETTING_STARTED.md) |
| Configure AirOS (LLM provider, thresholds, cities) | [docs/developer/CONFIGURATION.md](CONFIGURATION.md) |
| Add a new data source or domain | [docs/developer/ADD_DATA_SOURCE.md](ADD_DATA_SOURCE.md) |
| Build a decision support app on top of AirOS | [docs/developer/BUILD_YOUR_FIRST_AIR_OS_APP.md](BUILD_YOUR_FIRST_AIR_OS_APP.md) |
| Understand the driver packaging and certification plan | [docs/developer/DRIVER_MECHANISM_PLAN.md](DRIVER_MECHANISM_PLAN.md) |
| Understand how the agents reason | [docs/platform/INTELLIGENCE_METHODOLOGY.md](../platform/INTELLIGENCE_METHODOLOGY.md) |
| Understand the full system architecture | [docs/platform/OVERVIEW.md](../platform/OVERVIEW.md) |
| Deploy AirOS to a city | [docs/developer/DEPLOYMENT_QUICKSTART.md](DEPLOYMENT_QUICKSTART.md) |
| Understand AirOS Network (cross-city coordination) | [docs/platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md](../platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md) |

---

## Safety Posture

AirOS produces structured, reviewable outputs — observations, risk summaries, domain readings — that are intended to support analysts and decision-makers, not replace them. The platform does not automate government decisions, trigger enforcement actions, or write to any external system without a human review step. Every agent output is stored with provenance metadata so it can be audited, challenged, or overridden. Building applications on top of AirOS that bypass this posture is explicitly out of scope.

---

## What Works Today

| Component | Status |
|---|---|
| AirOS Core (Knowledge Store, Rules Registry, Scheduler, Conformance) | Working |
| Data Sources — 14 domains, OpenMeteo baseline, optional AQICN + GEE | Working |
| Decision Support System (H3 Expert Agent, City Pattern Agent, Review Dashboard) | Working |
| AirOS Network (cross-instance routing) | Specification only — not yet implemented |
