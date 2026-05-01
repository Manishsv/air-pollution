# AirOS Use Case Roadmap

## Use case maturity stages

Each use case should move through these stages:

1. Concept
2. Data-source discovery
3. Connector implementation
4. Provider contract (provider specification)
5. Normalization to canonical platform objects
6. Domain semantics (domain specification)
7. Consumer contracts (dashboard/API/SDK/report payloads)
8. Feature generation
9. Decision packet
10. Review workflow
11. Field validation / outcome feedback

AirOS is **specs-first**. Stages 4–7 are not optional: connectors and dashboards must be backed by specifications and must pass conformance.

## Current implemented use cases

### Air Quality
Status: Reference application implemented.
Current capabilities:
- H3 grid
- OSM static features
- OpenAQ PM2.5 connector with fallback
- Open-Meteo weather connector
- Optional NASA FIRMS fire connector
- Feature store
- Baseline forecast model
- Decision packets
- Review dashboard
- Conformance audit

### Crowd
Status: Early example.
Current capabilities:
- Camera people-count provider contract
- Edge publisher
- JSONL ingestion
- Observation store integration
- Dashboard tab

## Near-term target use cases

### Flood Risk
Target actors:
- Disaster management cell
- Stormwater department
- Ward officers
- Emergency responders

Operational questions:
- Which areas are at risk of flooding in the next few hours?
- Which drains, lakes, underpasses, and low-lying roads need inspection?
- Where should field teams be deployed?
- Which alerts should be issued?

Likely data sources:
- Rainfall forecasts
- IMD or open weather feeds
- Open-Meteo precipitation
- DEM/elevation data
- OSM drains, water bodies, roads
- Historical flood points
- Citizen reports
- Sensor feeds if available

Initial dashboard:
- Flood risk map
- Rainfall intensity
- Low-lying areas
- Drainage assets
- Field verification queue
- Ward-level risk summary

### Traffic and Mobility
Target actors:
- Traffic police
- Transport department
- City operations center
- Urban planners

Operational questions:
- Where is congestion building up?
- Which corridors need intervention?
- Which junctions are high-risk or overloaded?
- How do events, weather, and road works affect mobility?

Likely data sources:
- OSM road network
- GTFS public transit feeds where available
- TomTom/HERE/Mapbox APIs where licensed
- Public traffic camera counts
- Event data
- Road closure data
- Weather data

Initial dashboard:
- Congestion corridors
- Junction hotspots
- Travel-time reliability
- Incident/event overlay
- Recommended interventions

### Property and Buildings
Target actors:
- Property tax department
- Town planning department
- Building permission department
- Revenue department
- Ward officers

Operational questions:
- Which properties are under-assessed?
- Where are new buildings appearing?
- Which buildings may lack permissions?
- Which areas show high development pressure?
- Which property records need field verification?

Likely data sources:
- Property registry
- Building permits
- OSM buildings
- Microsoft/Google building footprints
- Satellite imagery-derived footprints
- Street-level surveys
- Tax payment records
- Land-use/zoning layers

Initial dashboard:
- Property coverage map
- Building footprint mismatch
- New construction candidates
- Assessment gap queue
- Ward-level revenue risk

### Water
Target actors:
- Water utility
- Ward engineers
- Operations teams
- City administrators

Operational questions:
- Which areas are under-served?
- Where are complaints clustering?
- Which assets are likely failing?
- Where are supply interruptions likely?
- Which valves, tanks, and pipes need inspection?

Likely data sources:
- Water network assets
- Tank levels
- Flow meters
- Pressure sensors
- Complaint systems
- Supply schedules
- Road cutting permissions
- Weather and demand proxies

Initial dashboard:
- Supply risk map
- Complaint clusters
- Asset reliability
- Pressure/flow anomalies
- Field task queue

## Development sequence (required for any new use case)

When starting a new use case, the minimum acceptable sequence is:

1. **Define** the actor and the decision to support
2. **Specify provider contracts** for each required data source
3. **Map to canonical platform objects** (domain-neutral where possible)
4. **Define domain specs** (variables, units, thresholds, safety gates, review prompts)
5. **Define consumer contracts** (dashboard payloads, decision packets, API/SDK responses)
6. **Register specs** in the specifications manifest
7. **Implement/extend conformance checks**
8. **Only then implement** connectors, pipelines, models, dashboards
9. **Run conformance** and attach evidence to the PR

This keeps AirOS interoperable across domains and prevents ad-hoc payloads from becoming de facto contracts.