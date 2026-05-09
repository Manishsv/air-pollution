# AirOS — Urban Intelligence Platform

AirOS is a **spatial, specs-first urban intelligence platform** that maps 14 environmental and infrastructure domains to a H3 hexagonal city grid, surfaces risk assessments to ward officers and engineers, and produces human-reviewed decision packets — never automated government decisions.

---

## What works today

| Capability | Status |
|-----------|--------|
| 14-domain H3 knowledge ingestors (air, flood, heat, water, fire, noise, construction, green, waste, weather, buildings, roads, drains, crowd) | ✓ Live |
| H3 Knowledge Store (SQLite, per-cell signals + assessments) | ✓ Live |
| Configurable Rules Registry (thresholds via YAML, no code changes) | ✓ Live |
| CCTV crowd monitoring (real-time 15-min cadence, camera registry) | ✓ Live |
| H3 Expert Agent (Claude-backed cross-domain reasoning) | ✓ Live |
| Review Dashboard (Streamlit, all 14 domain panels) | ✓ Live |
| Infrastructure Panel (buildings / roads / drains / live crowd) | ✓ Live |
| Core API pilot runtime (FastAPI) | ✓ Pilot |
| Program Reporting use case | ✓ Pilot |
| Evidence bundles (exportable audit packages) | ✓ Pilot |
| Identity & Trust, Network Layer, production auth | Future |

---

## Quick start

```bash
# Check environment
python tools/airos_cli.py doctor

# Run conformance suite
python tools/airos_cli.py conformance

# Launch the review dashboard
streamlit run review_dashboard/app.py

# Run flood fixture demo
python tools/airos_cli.py examples run flood_local_demo
```

---

## Documentation

### AirOS Platform
| Doc | What it covers |
|-----|---------------|
| [docs/platform/OVERVIEW.md](docs/platform/OVERVIEW.md) | Architecture, H3 store, ingest pipeline, raw→H3 methods |
| [docs/platform/RULES_REGISTRY.md](docs/platform/RULES_REGISTRY.md) | Configurable thresholds — all 33 rules, per-city overrides |
| [docs/platform/PRODUCT_MODEL.md](docs/platform/PRODUCT_MODEL.md) | Product areas (Core / Apps / SDK / Studio / Catalog) |
| [docs/platform/SDK_SURFACE.md](docs/platform/SDK_SURFACE.md) | Python SDK public surface (import audit) |
| [docs/platform/INTEROPERABILITY_MODEL.md](docs/platform/INTEROPERABILITY_MODEL.md) | How contracts enable interoperability across agencies |
| [docs/platform/ACTOR_MODEL.md](docs/platform/ACTOR_MODEL.md) | Five actor groups and their decision packet requirements |
| [docs/platform/EVIDENCE_BUNDLES.md](docs/platform/EVIDENCE_BUNDLES.md) | Portable audit packages: export, verify, redact |
| [docs/platform/PILOT_STORE_LIFECYCLE.md](docs/platform/PILOT_STORE_LIFECYCLE.md) | FileAirOsStore lifecycle, guarantees, limitations |
| [docs/platform/CORE_API_PILOT.md](docs/platform/CORE_API_PILOT.md) | Core API endpoints reference |
| [docs/platform/URBAN_SYSTEM_MODEL.md](docs/platform/URBAN_SYSTEM_MODEL.md) | Conceptual model: city layers, object types, causal chains |
| [docs/platform/AIR_OS_VISION.md](docs/platform/AIR_OS_VISION.md) | Design philosophy and non-negotiables |
| [docs/platform/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md](docs/platform/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md) | Deployment maturity levels (L0→L4) |
| [docs/platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md](docs/platform/FEDERATED_DEPLOYMENT_ARCHITECTURE.md) | Multi-node / multi-agency federation model |

### AirOS Apps & Use Cases
| Doc | What it covers |
|-----|---------------|
| [docs/apps/OVERVIEW.md](docs/apps/OVERVIEW.md) | All 14 domains: signals, risk levels, use cases, cross-domain patterns |
| [docs/apps/USE_CASE_ROADMAP.md](docs/apps/USE_CASE_ROADMAP.md) | Phased roadmap, 17-stage maturity model, domain sequence |
| [docs/apps/WARD_DECISION_CATALOGUE.md](docs/apps/WARD_DECISION_CATALOGUE.md) | Decision triggers and packets for AQ / Flood / Heat |
| [docs/apps/PROGRAM_REPORTING_AND_FUND_RELEASE.md](docs/apps/PROGRAM_REPORTING_AND_FUND_RELEASE.md) | Program reporting and fund-release review use case |
| [docs/apps/URBAN_HEAT_RISK_SDK_WALKTHROUGH.md](docs/apps/URBAN_HEAT_RISK_SDK_WALKTHROUGH.md) | Heat use case end-to-end walkthrough |
| [docs/apps/DATA_SOURCE_CATALOG.md](docs/apps/DATA_SOURCE_CATALOG.md) | Candidate data sources per domain, connector evaluation template |

### Developer Guides
| Doc | What it covers |
|-----|---------------|
| [docs/developer/START_HERE.md](docs/developer/START_HERE.md) | Choose your path (new developer / API consumer / deployment engineer) |
| [docs/developer/DEVELOPER_GUIDE.md](docs/developer/DEVELOPER_GUIDE.md) | Full technical guide: SDK, CLI, conformance, connectors, store |
| [docs/developer/BEGINNER_DEVELOPER_GUIDE.md](docs/developer/BEGINNER_DEVELOPER_GUIDE.md) | AirOS concepts via web-dev analogies |
| [docs/developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md](docs/developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md) | Step-by-step: adding a new domain from spec to dashboard |
| [docs/developer/SPECS_FIRST_DEVELOPMENT.md](docs/developer/SPECS_FIRST_DEVELOPMENT.md) | Specs-first philosophy, 4 spec families, conformance gate |
| [docs/developer/BUILD_YOUR_FIRST_AIR_OS_APP.md](docs/developer/BUILD_YOUR_FIRST_AIR_OS_APP.md) | Tutorial: scaffold → contracts → builder → validate → package |
| [docs/developer/DEPLOYMENT_QUICKSTART.md](docs/developer/DEPLOYMENT_QUICKSTART.md) | Clean-machine setup, health checks, fixture demos |
| [docs/developer/PILOT_RUNTIME_QUICKSTART.md](docs/developer/PILOT_RUNTIME_QUICKSTART.md) | Core API pilot walkthrough with copy-pasteable commands |
| [docs/developer/UI_GUIDELINES.md](docs/developer/UI_GUIDELINES.md) | Dashboard design rules, language guide, contributor checklist |
| [docs/developer/URBAN_CONTEXT_INDIA.md](docs/developer/URBAN_CONTEXT_INDIA.md) | Why AirOS is designed the way it is for Indian cities |

---

## Safety posture

AirOS supports **review**. It does **not** authorize or automate fund release, penalties, emergency orders, demolitions, blacklisting, or any final government decision. Every output carries confidence scores, safety gates, and "when not to act" guidance. Human officers review and record decisions.

---

## Legacy note

The former top-level `src/` package has been removed. The legacy AQ reference implementation lives at `urban_platform/applications/air_pollution/legacy_pipeline.py`. See [specifications/ARCHITECTURE_NOTE.md](specifications/ARCHITECTURE_NOTE.md).
