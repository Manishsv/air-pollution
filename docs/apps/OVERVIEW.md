# AirOS Apps & Providers — Domain Use Cases

AirOS ships fourteen domain modules. Ten produce risk assessments and decision packets for city officers. Four are structural context layers that inform cross-domain reasoning without generating their own alerts.

Each domain follows the same contract:
- **Ingestor** pulls raw data, maps it to H3 cells, writes signals to `h3_signals`
- **Pipeline** (for risk domains) computes a composite index, classifies risk level, writes to `h3_assessments`
- **Dashboard panel** surfaces signals and decision packets to reviewers
- **H3 Expert Agent** can be called on any cell to produce a cross-domain causal insight

---

## Risk Domains (produce signals + assessments + decision packets)

### 1. Air Quality
**Source:** CPCB sensor network / AQICN API · **Cadence:** hourly

Measures PM2.5, PM10, NO2, O3, SO2, CO and computes an AQI composite. Uses IDW interpolation from sparse sensors to all H3 cells. Confidence degrades with distance from nearest sensor (`NEAREST_OBS_KM` signal).

| Signal | Unit | Description |
|--------|------|-------------|
| PM25, PM10, NO2, O3, SO2, CO | µg/m³ | Raw pollutant concentrations |
| AQI | index | Composite air quality index |
| DATA_CONFIDENCE | ratio | 0–1, decays with sensor distance |
| NEAREST_OBS_KM | km | Distance to closest active sensor |

**Risk levels:** good / moderate / poor / unhealthy / very_unhealthy / hazardous (matches CPCB/WHO breakpoints in rules registry)

**Key use cases:**
- Ward officer dispatching inspection to pollution hotspots
- Correlating with construction, traffic density, or fire events
- Sensor siting recommendations (cells with high risk + low confidence = monitoring gap)

---

### 2. Flood Risk
**Source:** Sentinel-2 GEE (SAR backscatter + optical) · **Cadence:** daily / post-event

Combines radar-derived inundation probability (SAR), terrain slope (DEM), soil moisture proxy, and drain capacity (from drains domain) into a Flood Risk Index (0–1).

| Signal | Unit | Description |
|--------|------|-------------|
| FLOOD_RISK_INDEX | index | Composite 0–1 flood probability |
| SAR_INUNDATION | ratio | Radar-detected surface water fraction |
| SLOPE_RISK | index | Terrain slope risk contribution |
| SOIL_MOISTURE | index | Saturation proxy |
| DRAIN_CAPACITY | index | Pulled from drains domain signals |
| DATA_CONFIDENCE | ratio | Cloud cover–adjusted |

**Risk levels:** low / moderate / high / severe

**Key use cases:**
- Pre-monsoon vulnerability mapping
- Post-rainfall inundation confirmation
- Cross-referencing low drain density cells (drains domain) to explain flood persistence
- Ward-level evacuation route planning

---

### 3. Urban Heat
**Source:** Sentinel-2 LST (thermal) + OpenMeteo · **Cadence:** daily

Computes a Heat Risk Score combining Land Surface Temperature anomaly (Urban Heat Island) and Green Deficit (low NDVI). Identifies intervention candidates — cells with high heat + low green cover where tree planting or cool-roof programs would have maximum impact.

| Signal | Unit | Description |
|--------|------|-------------|
| LST_CELSIUS | °C | Land surface temperature |
| UHI_NORM | index | Normalised urban heat island (LST vs city mean) |
| GREEN_DEFICIT | index | 1 − NDVI_norm |
| HEAT_RISK_SCORE | index | 0.6 × UHI_norm + 0.4 × GREEN_DEFICIT |
| DATA_CONFIDENCE | ratio | Cloud cover–adjusted |

**Risk levels:** low / moderate / high / severe (thresholds in rules registry)

**Key use cases:**
- Identifying vulnerable neighbourhoods before summer peak
- Targeting tree-planting programs (high heat, low green)
- Cool-roof scheme prioritisation
- Cross-correlation with crowd density (outdoor events in heat-stressed cells)

---

### 4. Water Quality
**Source:** Sentinel-2 GEE (water body spectral indices) · **Cadence:** daily / clear-sky pass

Detects water bodies via MNDWI and computes three sub-indices: Turbidity (NDTI, suspended sediment/sewage), Algal bloom (CI, chlorophyll-a proxy), and Foam/Scum (FAI, floating algae/industrial foam). Combines into a Water Quality Index (WQI, 0–1, higher = worse).

| Signal | Unit | Description |
|--------|------|-------------|
| MNDWI | index | Water body detection |
| NDTI | index | Turbidity (sediment/sewage) |
| CI | ratio | Chlorophyll index (algal bloom) |
| FAI | index | Floating algae/foam index |
| WATER_QUALITY_INDEX | 0–1 | Composite: higher = worse |
| DATA_CONFIDENCE | ratio | Cloud cover–adjusted |

**Risk levels:** good / moderate / poor / severe

**Known hotspots pre-seeded (Bangalore):** Bellandur Lake (high), Varthur Lake (high), Ulsoor Lake (moderate)

**Key use cases:**
- Algal bloom and lake foam event detection
- Sewage discharge identification upstream of intakes
- Pre-closing recreational water bodies before lab confirmation
- Cross-correlation with flood events (runoff turbidity spikes)

---

### 5. Fire Detection
**Source:** MODIS / VIIRS active fire data · **Cadence:** every 3 hours

Detects active fire events by Fire Radiative Power (FRP, megawatts). Distinguishes crop-burning, waste burning, and in-city fire events. FRP > threshold → assessment written.

| Signal | Unit | Description |
|--------|------|-------------|
| FRP_MW | MW | Fire Radiative Power |
| FIRE_SCORE | index | log1p(FRP) / log1p(saturation), 0–1 |
| FIRE_TYPE | category | crop_burn / waste_burn / vegetation / in_city |
| DATA_CONFIDENCE | ratio | 0.80 (MODIS 1km pixel, cloud-limited) |

**Key use cases:**
- Rapid alert for in-city fire events (co-located with buildings or roads)
- AQ spike attribution (unexplained PM2.5 rise + nearby fire = likely source)
- Waste burning monitoring (FRP cluster near waste domain signals)

---

### 6. Noise
**Source:** Noise sensor API · **Cadence:** hourly

Computes a Noise Risk Index (NRI) combining ambient decibel levels with proximity to sensitive receptors (hospitals, schools from OSM) and time-of-day weighting.

| Signal | Unit | Description |
|--------|------|-------------|
| LAeq_DB | dB(A) | Ambient noise level |
| NOISE_RISK_INDEX | index | Weighted composite |
| RECEPTOR_PROXIMITY | index | Nearness to sensitive uses |
| DATA_CONFIDENCE | ratio | Sensor network coverage |

**Risk levels:** low / moderate / high / severe (WHO / CPCB noise standards in rules registry)

---

### 7. Construction Activity
**Source:** Construction permit API + SAR change detection · **Cadence:** every 6 hours

Identifies active construction zones by combining permit data with satellite-detected surface change. Computes a Construction Risk Index (CRI) for AQ and noise impact.

| Signal | Unit | Description |
|--------|------|-------------|
| ACTIVE_PERMIT_COUNT | count | Open construction permits in cell |
| SURFACE_CHANGE | index | SAR-detected ground disturbance |
| BSI | index | Bare Soil Index (vegetation loss proxy) |
| CONSTRUCTION_RISK_INDEX | index | Composite |
| DATA_CONFIDENCE | ratio | |

**Key use cases:**
- Explaining PM2.5 spikes near active construction
- Permit compliance monitoring (activity without permit)
- Ward-level construction impact complaints

---

### 8. Green Cover
**Source:** Sentinel-2 NDVI + land use · **Cadence:** daily

Tracks green cover change over time using NDVI. The Green Cover Change Index (GCCI) detects gain (tree planting success) or loss (clearing, drought stress).

| Signal | Unit | Description |
|--------|------|-------------|
| NDVI | index | Normalised Difference Vegetation Index |
| GREEN_COVER_FRACTION | ratio | Fraction of cell with NDVI > threshold |
| GCCI | index | Change vs baseline (positive = gain) |
| DATA_CONFIDENCE | ratio | Cloud cover–adjusted |

**Key use cases:**
- Tracking Miyawaki/urban forest program outcomes
- Detecting illegal tree felling
- Heat island intervention targeting (complement to heat domain)

---

### 9. Waste / Illegal Dumping
**Source:** Sentinel-2 spectral indices + MODIS fire · **Cadence:** daily

Identifies open waste dumping sites via spectral signatures and detects waste-burning events via FRP clustering at known dump locations.

| Signal | Unit | Description |
|--------|------|-------------|
| WASTE_SITE_PROBABILITY | ratio | Spectral match to waste land cover |
| BURN_FRP_MW | MW | Fire Radiative Power at waste site |
| WASTE_RISK_INDEX | index | Composite |
| PERSISTENCE_DAYS | count | Days site has been flagged |
| DATA_CONFIDENCE | ratio | |

**Key use cases:**
- Illegal dump site identification for enforcement
- Chronic waste burning alerting (persistent sites)
- AQ source attribution (waste burn + PM2.5 spike)

---

### 10. Crowd / Gatherings
**Source:** CCTV camera people_count feed · **Cadence:** every 15 minutes · **Live signal**

Reads `people_count` observations from `data/processed/observation_store.parquet` (written by the camera analytics publisher pipeline). Joins camera locations from `data/config/camera_registry.json`. Cells with no camera coverage are absent (not zero — absence = no data).

| Signal | Unit | Description |
|--------|------|-------------|
| PEOPLE_COUNT | count | Total people across cameras in cell, 15-min window |
| CAMERA_COUNT | count | Number of active cameras that reported |
| CROWD_DENSITY | per_km² | PEOPLE_COUNT / cell area |
| CROWD_INDEX | 0–1 | Normalised crowd intensity |
| GATHERING_ALERT | flag | 1.0 if density ≥ 500 people/km² (configurable) |
| DATA_CONFIDENCE | ratio | 0.90 for cells with active cameras |

Cells with `GATHERING_ALERT = 1` also write an `h3_assessment` at `risk_level = "high"` so the H3 Expert Agent sees gathering events in its initial context alongside AQ and heat signals.

**Key use cases:**
- Real-time event and protest monitoring
- Festival crowd management (Diwali, Ganesh Chaturthi)
- Cross-domain: large crowd + poor air → public health advisory
- Cross-domain: large crowd + heat stress → cooling station activation

**Camera registry:** `data/config/camera_registry.json` maps `entity_id` (device ID from publisher) to city, lat/lon, location name. Add new cameras here without touching pipeline code.

---

## Structural Context Domains (signals only, no assessments)

These four domains provide the "city anatomy" that the H3 Expert Agent and risk pipelines use to reason about exposure, capacity, and source proximity. They do not generate their own risk alerts.

### Buildings
**Source:** OSM Overpass · **Cadence:** quarterly

| Signal | Unit | Notes |
|--------|------|-------|
| BUILDING_COUNT | count | OSM footprints with centroid in cell |
| BUILDING_DENSITY | per_km² | Count / cell area |
| AVG_FLOORS | floors | Mean `building:levels` tag, default 1 if missing |
| COMMERCIAL_RATIO | ratio | Fraction with commercial/retail/office tag |
| DATA_CONFIDENCE | 0.75 | Informal structures often unmapped |

**Used by:** air (exposure estimation), heat (impervious surface), flood (flow obstruction)

### Roads
**Source:** OSM Overpass · **Cadence:** quarterly

| Signal | Unit | Notes |
|--------|------|-------|
| ROAD_LENGTH_M | metres | Total clipped road length in cell |
| ROAD_DENSITY | m/km² | Normalised network density |
| MAJOR_ROAD_RATIO | ratio | Motorway/trunk/primary/secondary fraction |
| INTERSECTION_COUNT | count | Nodes with degree ≥ 3 (osmnx graph) |
| DATA_CONFIDENCE | 0.85 | Minor lanes may be missing |

**Used by:** air (traffic emission proximity), heat (heat island — impervious), flood (drainage blockage risk)

### Drains
**Source:** OSM Overpass · **Cadence:** quarterly

| Signal | Unit | Notes |
|--------|------|-------|
| DRAIN_LENGTH_M | metres | Total waterway length in cell |
| WATERWAY_COUNT | count | Distinct features |
| OPEN_DRAIN_RATIO | ratio | Open drain/canal vs culvert fraction |
| FLOOD_DRAIN_CAPACITY | 0–1 | Normalised drainage density index |
| DATA_CONFIDENCE | 0.65 | Open drains in informal settlements often unmapped |

**Used by:** flood (primary modulator — low drain density + rainfall = high flood risk)

### Weather
**Source:** OpenMeteo API · **Cadence:** hourly

| Signal | Unit | Notes |
|--------|------|-------|
| TEMP_C | °C | Air temperature |
| HUMIDITY_PCT | % | Relative humidity |
| WIND_SPEED_MS | m/s | Wind speed |
| WIND_DIR_DEG | degrees | Wind direction |
| RAINFALL_MM | mm | Hourly precipitation |
| DATA_CONFIDENCE | 0.90 | Grid model, point observation at city center |

**Used by:** flood (rainfall accumulation), air (wind-driven dispersion), heat (ambient temperature baseline), crowd (outdoor event planning)

---

## Cross-Domain Reasoning

The H3 Expert Agent sees all signals simultaneously for any requested cell. Common cross-domain patterns:

| Signals present | Likely interpretation |
|----------------|----------------------|
| High PM2.5 + active fire nearby | Fire is the AQ source |
| High PM2.5 + active construction + low wind | Construction dust trapped |
| High flood risk + low FLOOD_DRAIN_CAPACITY | Infrastructure deficit amplifying risk |
| High crowd density + high heat + outdoor event | Public health risk — cooling advisory |
| High NDVI loss + high WASTE_RISK + low BUILDING_COUNT | Possible illegal dumping on vacant land |
| GATHERING_ALERT + high AQ risk | Cross-domain: consider event postponement advisory |

---

## Domain Maturity

| Domain | OSM structural | Satellite | Real-time sensors | Assessment | Decision packets |
|--------|---------------|-----------|-------------------|------------|-----------------|
| Air Quality | — | — | ✓ | ✓ | ✓ |
| Flood | ✓ (drains) | ✓ | — | ✓ | ✓ |
| Heat | ✓ (roads, bldg) | ✓ | — | ✓ | ✓ |
| Water Quality | — | ✓ | — | ✓ | ✓ |
| Fire | — | ✓ (MODIS) | — | ✓ | ✓ |
| Noise | — | — | ✓ | ✓ | ✓ |
| Construction | — | ✓ | — | ✓ | ✓ |
| Green Cover | — | ✓ | — | ✓ | ✓ |
| Waste | — | ✓ | — | ✓ | ✓ |
| Crowd | — | — | ✓ (CCTV) | ✓ (gathering) | planned |
| Buildings | ✓ | — | — | — | — |
| Roads | ✓ | — | — | — | — |
| Drains | ✓ | — | — | — | — |
| Weather | — | — | ✓ (model) | — | — |

---

## Use Case: Program Reporting & Fund Release
→ See [PROGRAM_REPORTING_AND_FUND_RELEASE.md](PROGRAM_REPORTING_AND_FUND_RELEASE.md)

Cities submit structured program submissions (e.g. AMRUT 2.0 infrastructure reports). State officers review consolidated evidence packets — spatially indexed, with H3-level supporting signals — before approving fund release. No automated fund release. Evidence bundles are exportable for audit.

---

## Adding a New Domain

Follow the Domain Development Playbook at [../developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md](../developer/DOMAIN_DEVELOPMENT_PLAYBOOK.md):

1. Write a domain spec YAML (`specifications/domain_specs/<domain>.yaml`)
2. Write provider contracts for each data source
3. Write consumer contracts for the dashboard panel
4. Implement the ingestor (`urban_platform/h3_knowledge/<domain>_ingestor.py`)
5. Add domain thresholds to `data/config/rules_registry.yaml`
6. Wire into `urban_platform/h3_knowledge/ingestor.py` (add to ALL_DOMAINS, cadence table, dispatch)
7. Add dashboard panel (`review_dashboard/components/<domain>_panel.py`)
8. Update the H3 Expert Agent system prompt with new signal names
