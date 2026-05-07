# AirOS Urban System Model

## 1. Purpose

This document defines the conceptual model that underpins AirOS. It exists to
give a shared mental model to everyone who designs, builds, or operates the
system — domain architects, specification writers, pipeline engineers, and
governance reviewers.

The model answers: **what is a city, and what is AirOS trying to do within it?**

---

## 2. Citizen quality of life as the top-level outcome

The top of the model is not a department. It is not a dataset. It is not a
technology. It is:

```
Citizen Quality of Life
= safety + health + access + dignity + affordability + opportunity + resilience + trust
```

Every layer below this exists to contribute to, or explain departures from,
this outcome. A drain registry is not valuable because it is a registry. It is
valuable because a well-maintained drain prevents flooding, which preserves
school access, prevents disease, and builds citizen trust in government.

AirOS should always be able to trace from a technical signal to a citizen
outcome. If it cannot, the signal should be questioned.

The **economic domain** maps directly to `affordability`, `opportunity`, and
`resilience` in the equation above. It is distinct from environmental domains
in a critical way: it operates **bidirectionally**.

- **Inward:** economic conditions determine how badly environmental risk hurts
  citizens. The same flood risk hits an informal market vendor far harder than
  a salaried professional.
- **Outward:** environmental interventions unlock economic potential. Fixing
  flood risk in a market ward is not just hazard mitigation — it is urban
  development investment with a calculable economic return.

This makes the economic lens a cross-cutting multiplier, not just another
domain column.

---

## 3. Layered city model

The city is a layered living system. Each layer has assets, events, flows,
risks, and decisions. Higher layers depend on lower layers, but also feed back
into them.

```
Layer 7: Urban outcomes and quality of life
Layer 6: Governance, finance, regulation, and trust
Layer 5: People, households, firms, and institutions
Layer 4: Public services and civic operations
Layer 3: Utility and environmental flows
Layer 2: Physical infrastructure networks
Layer 1: Built form and land use
Layer 0: Geography and natural systems
```

### Layer 0 — Geography and natural systems

The base layer. Defines what is physically possible and what risks exist.

| Domain | Examples |
|--------|---------|
| Land | Topography, soil type, slope |
| Water | Lakes, rivers, wetlands, groundwater, watersheds, flood plains |
| Green cover | Tree canopy, biodiversity, ecological buffers |
| Climate | Rainfall patterns, heat accumulation, air sheds, natural drains |

Key questions:
- Where does water naturally flow?
- Where does heat accumulate?
- Where is air pollution trapped or dispersed?
- Where are ecological buffers being lost?
- Which areas are naturally risky for construction?

Typical registries: land parcel registry, water body registry, tree/green asset
registry, watershed registry, flood plain registry, heat-risk zone registry,
air monitoring zone registry.

**Status in AirOS:** Air quality, flood, and heat natural systems are modelled
as observation feeds. Watershed and drainage basin topology not yet modelled.

### Layer 1 — Built form and land use

How human settlement sits on the natural base.

Buildings, plots, property, land use, zoning, roads, footpaths, public spaces,
markets, informal settlements, transit-oriented zones, heritage areas,
construction activity.

Key questions:
- What is built where?
- Is land use compatible with infrastructure capacity?
- Where is density growing?
- Where is unauthorised or risky construction happening?
- Where are public spaces missing?

**Status in AirOS:** Property and buildings domain partially modelled. Land use,
zoning, and construction activity not yet modelled.

### Layer 2 — Physical infrastructure networks

The city's hardware. Must be modelled as **networks**, not just maps.

```
Drain → catchment → outfall → lake
Water pipe → valve → reservoir → household
Road → junction → traffic flow → bus route
Transformer → feeder → consumer cluster
```

Includes roads, drainage, sewerage, water supply, electricity, gas, stormwater,
solid waste, streetlights, telecom, public transport, health and education
facilities.

Key questions:
- Where are assets? What condition are they in? What capacity?
- What dependencies exist between networks?
- Where are bottlenecks? Which assets serve which citizens?

**Status in AirOS:** Drainage assets partially modelled in flood domain. Full
network topology not yet built.

### Layer 3 — Utility and environmental flows

What moves through the city. This is where digital twins become useful.

Water flow, sewage, stormwater, electricity demand, traffic, people movement,
waste, air pollutant movement, heat exposure, disease risk, money flows.

Key questions:
- How much demand exists where and when?
- Where does supply fall short?
- What happens if rainfall doubles?
- What happens if a road is blocked?
- Where do failures cascade?

**Status in AirOS:** Air quality (PM2.5), rainfall intensity, and urban heat are
modelled as H3-gridded flows. Full demand/supply modelling not yet built.

### Layer 4 — Public services and civic operations

What the city government does every day.

Complaints, licences, permits, inspections, approvals, property tax, water
connections, certificates, trade licences, building plan approvals, waste
collection, road repair, drain desilting, public health responses, emergency
response, welfare delivery.

Key distinction: **system of record** vs **system of service delivery**.

```
Property registry = system of record
Property tax payment = transaction/service
Building permit = regulatory workflow
Grievance = issue-resolution workflow
```

**Status in AirOS:** Program reporting domain started. Permits, complaints, and
regulatory workflows not yet modelled.

### Layer 5 — People, households, firms, and institutions

The demand, vulnerability, and opportunity layer.

Population, households, density, age groups, income, vulnerable groups,
migrants, informal workers, businesses, schools, hospitals, community
institutions, government departments, parastatals, utilities.

This layer turns infrastructure analysis into **equity analysis** and
environmental risk analysis into **economic impact analysis**.

A drain failure is not just a hydraulic event. It becomes a citizen issue when
it affects school access, health risk, livelihood loss, property damage,
mobility, dignity, and trust in government.

**Economic vulnerability signals** (who gets hurt more when risk materialises):
- Housing type — kutcha / informal structures vs permanent construction
- Livelihood exposure — outdoor workers, daily-wage, agricultural, street
  vendors who cannot work when flooded, heat-stressed, or air-quality-impaired
- Market dependency — households relying on local informal markets for food,
  income, and credit
- Income proxy — nighttime light intensity per ward as a relative economic
  activity measure
- Distance from formal employment, banking, and healthcare (isolation index)

**Economic opportunity signals** (where intervention creates the most growth):
- Commercial and market density — OSM shops, markets, hawker zones, mandis
- Employment zone classification — industrial, commercial, residential, informal
- Connectivity to economic corridors — transit access, arterial road quality
- Underutilised land with high accessibility — latent development potential
- Green economy potential — rooftop area for solar, urban forestry canopy
  deficit as job-creation opportunity, waste-to-value zones

**Status in AirOS:** Not yet modelled. Economic vulnerability and opportunity
signals are the next planned domain after the environmental trio (air, flood,
heat) is stable.

### Layer 6 — Governance, finance, regulation, and trust

Why cities succeed or fail institutionally.

Departments, jurisdictions, mandates, budgets, schemes, projects, contracts,
vendors, regulations, standards, approvals, compliance, audit, revenue,
expenditure, procurement, inter-agency coordination, data-sharing agreements.

Key questions:
- Who is authorised to act? Who pays? Who maintains? Who is accountable?
- Which data can be trusted?
- What is the fiscal capacity of the city?

**Status in AirOS:** Program reporting domain touches fiscal flows. Institutional
and governance modelling not yet built.

### Layer 7 — Citizen quality of life

The outcome layer. Instead of departmental outputs, measure citizen outcomes:

Safety, health, mobility, clean air, clean water, sanitation, flood safety,
thermal comfort, access to services, access to livelihoods, housing quality,
public space access, affordability, trust, dignity, resilience.

**Status in AirOS:** Ward-level quality of life index introduced as the first
outcome aggregation, computed from air, flood, and heat domain features.

---

## 4. Core object types

For any urban domain, ask:

| Object | Question |
|--------|---------|
| **Registry** | What exists? (assets, parcels, buildings, drains, trees, zones) |
| **Observation** | What was measured? (sensor, complaint, inspection, payment, image) |
| **Event** | What happened? (failure, flood, spike, outage, violation) |
| **Feature** | What does it mean spatially? (IDW-interpolated H3 cell value) |
| **Decision packet** | What should be done? (recommendation + evidence + confidence) |
| **Outcome** | What changed for citizens? (safety, health, access, trust) |

Concrete example — stormwater:

```
Registry:    Drain D-102, length 240m, capacity 0.8m³/s, last desilt 2025-11-01
Observation: Rainfall 38mm/hr at station S-12; complaint cluster C-88 in Ward 7
Event:       Waterlogging event W-44; road blocked; school access disrupted
Feature:     H3 cell 8a283082a657fff — flood_risk_score 0.84, incident_count 3
Decision:    Desilt D-102 before next rain; inspect blockage; prioritise Ward 12
Outcome:     Ward 12 flood safety index: 0.42 → field action → 0.71 (post-desilt)
```

---

## 5. Spatial unit hierarchy

AirOS uses H3 cells as the computational unit (fine-grained, uniform,
spatially indexable). But governance operates at coarser units.

```
H3 cell (resolution 9 ≈ 0.1 km²)   ← pipeline computation unit
    ↓ spatial join
Ward / neighbourhood                  ← governance decision unit
    ↓ aggregation
Zone / assembly constituency          ← political accountability unit
    ↓ aggregation
City                                  ← fiscal and planning unit
```

Decision packets and quality of life indices should be expressible at the ward
level at minimum. Citizens and field officers operate at ward level; planners at
zone/city level.

---

## 6. AirOS architecture mapping

```
Provider contracts   →  raw observations / events
Observation store    →  append-only Parquet landing zone (domain/city/date)
Feature store        →  H3-indexed DuckDB (cross-domain features per cell/hour)
Place hierarchy      →  ward registry + H3→ward spatial join
Domain pipelines     →  IDW interpolation, scoring, decision packet generation
Consumer contracts   →  validated dashboard payloads and decision packets
Review dashboard     →  per-domain panels + cross-domain + ward quality-of-life
Evidence bundles     →  data_source_status + computation_trace per packet
Outcome layer        →  ward quality-of-life index (safety, health, comfort)
```

---

## 7. Cross-domain causal chains

AirOS should be able to model and communicate causal chains that span domains.

**Flooding → health → trust:**
```
Poor drain maintenance
→ localised flooding (flood domain)
→ school / work access disrupted (Layer 5)
→ disease risk increases (health outcome)
→ complaints rise (Layer 4 event)
→ trust falls (Layer 7 outcome)
→ property values decline (Layer 1 feedback)
```

**Land use → heat → energy → health:**
```
Dense construction, reduced green cover (Layer 1)
→ Urban heat island intensifies (Layer 0/3)
→ Thermal discomfort increases (Layer 7)
→ Electricity demand spikes (Layer 3)
→ Grid stress, possible outage (Layer 2)
→ Vulnerable household health risk (Layer 5/7)
```

**Rainfall → runoff → flooding → disease:**
```
Rainfall event (Layer 0)
→ Runoff through drainage network (Layer 2/3)
→ Waterlogging where capacity exceeded (Layer 3 event)
→ Contamination risk (Layer 3/5)
→ Hospitalisation spike (Layer 7)
→ Inspection and repair decision (Layer 4/6)
```

**Environmental risk → economic suppression → missed opportunity:**
```
Flood risk in informal market ward (Layer 0/3)
→ Vendors cannot operate during monsoon (Layer 5)
→ Daily-wage income lost; household debt pressure (economic outcome)
→ Market abandonment; land value decline (Layer 1)
→ Tax base erosion; reduced maintenance budget (Layer 6)
→ Infrastructure degrades further → risk worsens (feedback loop)
```

**Environmental intervention → economic unlock:**
```
Flood mitigation investment in Ward X (Layer 4/6)
→ Informal market operates year-round (Layer 5)
→ Vendor incomes stabilise; 400 livelihoods secured (economic outcome)
→ Property values recover; new businesses enter (Layer 1/5)
→ Property tax and trade licence revenue increases (Layer 6)
→ City can fund next ward's drain upgrade (reinvestment cycle)
```

**Heat → outdoor worker productivity → economic exclusion:**
```
Urban heat island intensifies (Layer 0/3)
→ Outdoor workers (construction, street vending) lose productive hours
→ Heat-related illness increases; healthcare cost rises (Layer 5/7)
→ Low-income households disproportionately affected (equity gap widens)
→ Green cover intervention + cool zone creation (Layer 1/4)
→ Productivity restored; economic inclusion improves (Layer 7)
```

---

## 8. Urban metabolism view

The city as metabolism. Useful for sustainability and climate resilience.

```
Inputs:    water, energy, food, materials, money, people, data
Processes: transport, consumption, construction, production, governance
Outputs:   waste, sewage, emissions, heat, economic value, social outcomes
Feedback:  complaints, sensors, inspections, audits, budgets, elections
```

Cross-domain connections:
```
Land use → mobility → emissions → air quality → health
Buildings → heat → electricity demand → grid stress
Rainfall → runoff → flooding → disease → service complaints
Property tax → revenue → maintenance → service quality
```

---

## 9. Economic domain model

### 9.1 Purpose

The economic domain answers three questions that no other domain answers:

1. **Who is most harmed?** Economic vulnerability determines how environmental
   risk translates into citizen hardship. Equal risk ≠ equal harm.
2. **Where is the highest return on intervention?** Economic opportunity signals
   show which wards will generate the most livelihood benefit from a given
   environmental fix.
3. **What is the intervention ROI?** Combining risk reduction with economic
   opportunity produces a ward-level investment prioritisation score.

### 9.2 Two-index model

**Economic Vulnerability Index (EVI)**

Measures how exposed a ward's population is to economic harm when
environmental risk materialises. A high EVI ward suffers more from the same
flood or heat level than a low EVI ward.

```
EVI = f(
  housing_informality,       # share of kutcha / non-permanent structures
  livelihood_outdoor_share,  # share of outdoor / daily-wage / informal workers
  market_dependency,         # reliance on local informal markets
  income_proxy,              # nighttime light intensity (relative)
  isolation_index,           # distance from formal employment, healthcare, banking
)
```

EVI acts as a multiplier on environmental risk scores when computing ward
priority for intervention. A ward with `flood_risk = 0.5` and `EVI = high`
should rank higher for intervention than one with `flood_risk = 0.7` and
`EVI = low`.

**Economic Opportunity Index (EOI)**

Measures the latent economic potential that gets unlocked when environmental
risk in a ward is reduced. A high EOI ward has more to gain from intervention.

```
EOI = f(
  commercial_density,        # shops, markets, vendors, mandis per km²
  employment_zone_class,     # industrial / commercial / mixed / residential / informal
  corridor_connectivity,     # transit and road access to economic hubs
  land_activation_potential, # underutilised accessible land
  green_economy_potential,   # rooftop solar area, urban forestry opportunity,
                             #   waste-to-value zones
)
```

### 9.3 Intervention ROI score

```
Intervention ROI (ward) = risk_severity × EVI × EOI
```

This ranks wards not just by how bad conditions are, but by how much
improvement in citizen lives and economic activity a unit of intervention
investment would produce.

### 9.4 Integration with Ward QoL index

The current QoL formula:
```
QoL = 0.40 × (1 − flood_risk) + 0.35 × (1 − aqi_score) + 0.25 × (1 − heat_risk)
```

With economic domain added:
```
Adjusted QoL = QoL × (1 − EVI_weight)    # vulnerability-corrected outcome
Economic Opportunity Score = EOI          # separate output, not folded into QoL
Intervention Priority Score = (1 − QoL) × EVI × EOI
```

The economic scores surface as additional columns in the ward aggregation
output and as a separate dashboard view: **Ward Investment Prioritisation**,
ranking wards by intervention priority score rather than QoL index alone.

### 9.5 Data sources (planned)

| Signal | Source |
|--------|--------|
| Housing informality | GHSL built-up surface type (formal vs informal) |
| Nighttime lights | VIIRS/NPP monthly composites (NASA LAADS) |
| Commercial density | OpenStreetMap amenity/shop/market features |
| Road / transit access | OSM road network + GTFS transit feeds |
| Employment zones | City master plan land-use layer (GeoJSON) |
| Rooftop solar potential | DSM + sun angle computation or Google Solar API |
| Urban forestry gaps | NDVI raster (Sentinel-2) vs. ward canopy targets |

All economic signals will be ingested through the same observation store →
feature store pipeline as environmental domains, keyed by H3 cell.

---

## 10. Urban ontology (top level)

```
Urban Area
  Natural System
    Land · Water · Air · Green Cover · Climate/Weather
  Built Environment
    Parcel · Building · Road · Public Space · Infrastructure Asset
  Network
    Mobility · Drainage · Water · Sewerage · Power · Gas · Data
  Service
    Civic · Utility · Regulatory · Welfare · Emergency
  Actor
    Citizen · Household · Business · Department · Utility · Vendor · Community
  Economic Unit
    Informal Market · Employment Zone · Business Cluster · Green Economy Asset
    Livelihood Group · Supply Chain Node
  Event
    Complaint · Failure · Payment · Inspection · Rainfall · Pollution Spike
    Construction · Permit Application · Market Disruption · Livelihood Loss
  Decision
    Approve · Reject · Inspect · Repair · Prioritise · Notify
    Allocate Budget · Issue Warning · Invest · Unlock Zone
  Outcome
    Health · Safety · Access · Affordability · Environment · Trust · Resilience
    Economic Opportunity · Livelihood Stability · Intervention ROI
```

---

## 10. Use-case prioritisation framework

For every new domain or feature, score it:

| Criterion | Weight |
|-----------|--------|
| Citizen impact | High |
| Institutional pain point | High |
| Data availability | Medium |
| Model/AI readiness | Medium |
| Integration complexity | Medium (inverse) |
| Adoption feasibility | Medium |
| Revenue/funding potential | Low–Medium |
| Ecosystem leverage | Medium |
| Risk/safety sensitivity | High |

Use the score to decide whether something is:

- AirOS core capability
- AirOS domain app
- Provider adapter
- Dashboard/review workflow
- Sandbox / demo
- Partner opportunity
- Deferred research

---

## 11. Scope for v1

**In scope:**
- Layer 0 natural systems: air quality, flood risk, heat risk
- Layer 1 built form: property and buildings (partial)
- Layer 3 flows: PM2.5, rainfall intensity, urban heat index
- Layer 4 services: program reporting (partial)
- Observation store, feature store, ward quality-of-life index
- H3 → ward spatial hierarchy

**Next domain (planned):**
- Economic domain: Economic Vulnerability Index (EVI) + Economic Opportunity
  Index (EOI) per ward
- Ward Investment Prioritisation view: ranks wards by intervention ROI
- Data sources: GHSL (housing informality), VIIRS nighttime lights, OSM
  commercial density, Sentinel-2 NDVI (green economy potential)

**Deferred:**
- Drainage network topology (Layer 2 graph model)
- Population and vulnerability overlay (Layer 5 — demographic detail)
- Governance and fiscal modelling (Layer 6)
- Water supply, sewerage, electricity networks
- Complaints and permit workflows (Layer 4)
- Causal chain simulation
- Digital twin / real-time sensor integration

---

## 12. Design principles

1. **Citizen outcome first.** Every feature traces to a quality-of-life dimension.
2. **Registries before flows.** You cannot model what flows through an asset you have not registered.
3. **Observation before inference.** Raw data must be preserved before features are computed.
4. **Evidence with every decision.** No decision packet is valid without an auditable evidence chain.
5. **Separate record from service.** The registry is not the workflow. The asset is not the transaction.
6. **H3 for computation, ward for governance.** Fine-grained grids for pipelines; named places for people.
7. **Local-first, cloud-ready.** Every component runs offline; nothing assumes a network.
8. **Domain-first, then cross-domain.** Build one vertical slice fully before joining domains.
9. **Economic lens is bidirectional.** Measure who is made more vulnerable by risk (inward),
   and where interventions create the most economic opportunity (outward). Environmental
   action is urban development investment with a calculable return.
10. **Equal risk ≠ equal harm.** Always weight environmental risk by economic vulnerability.
    A flood-risk score without an EVI multiplier understates harm to informal market wards.
