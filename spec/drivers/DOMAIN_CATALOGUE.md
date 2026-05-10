# AirOS Drivers — Domain Catalogue

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Drivers

---

## Purpose [INFORMATIVE]

This catalogue defines the **14** canonical AirOS domains — the environmental and infrastructure lenses through which the platform analyses a city. Each domain is either a **risk domain** (produces risk assessments) or a **structural context domain** (provides background signals only).

The count of 14 canonical domains is an invariant of this spec version. Adding a canonical domain requires a minor version bump and an update to OVERVIEW.md. Third-party implementers may add non-canonical domains freely without changing this catalogue.

The canonical domains are not exhaustive. Implementers may add new domains by writing a Driver that declares a domain name not in this catalogue. The canonical domains listed here have stable signal names, risk level vocabularies, and cross-domain relationships that all AirOS Apps can reason about.

---

## Domain Classification

### Risk Domains

Risk domains produce both signals (`h3_signals`) and risk assessments (`h3_assessments`). The H3 Expert Agent uses assessments to prioritise cells for analysis.

| Domain | Cadence | Primary Source | Key Composite Index |
|--------|---------|----------------|---------------------|
| `air` | 15 min | AQI sensor network (CPCB / AQICN) | `AQI` |
| `fire` | 15 min | MODIS / VIIRS active fire | `FIRE_SCORE` |
| `heat` | 30 min | Sentinel-2 LST + weather | `HEAT_RISK_SCORE` |
| `flood` | 1 h | Sentinel-2 SAR + DEM | `FLOOD_RISK_INDEX` |
| `water` | 1 h | Sentinel-2 spectral (MNDWI / NDTI) | `WATER_QUALITY_INDEX` |
| `waste` | 1 h | Sentinel-2 spectral + MODIS fire | `WASTE_RISK_INDEX` |
| `construction` | 6 h | Permit API + Sentinel-2 SAR | `CONSTRUCTION_RISK_INDEX` |
| `green` | 6 h | Sentinel-2 NDVI | `GCCI` (Green Cover Change Index) |
| `noise` | 6 h | Noise sensor API | `NOISE_RISK_INDEX` |
| `crowd` | 15 min | CCTV / people count feed | `GATHERING_ALERT` |

### Structural Context Domains

Structural domains produce signals only. They MUST NOT write `h3_assessments` rows. They provide the physical and infrastructure context that the H3 Expert Agent uses to modulate risk reasoning.

| Domain | Cadence | Primary Source | Purpose |
|--------|---------|----------------|---------|
| `weather` | 15 min | OpenMeteo API | Wind, rainfall, temperature — modulates all risk domains |
| `buildings` | 90 days (2160 h) | OSM Overpass | Population exposure, impervious surface |
| `roads` | 90 days (2160 h) | OSM Overpass + osmnx | Traffic emission proximity, flood drainage |
| `drains` | 90 days (2160 h) | OSM Overpass waterways | Flood drainage capacity, waterway density |

---

## Canonical Signal Tables

### `air` — Air Quality

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `PM25` | µg/m³ | yes | IDW (Method A) | PM2.5 concentration |
| `PM10` | µg/m³ | yes | IDW | PM10 concentration |
| `NO2` | µg/m³ | yes | IDW | Nitrogen dioxide |
| `O3` | µg/m³ | yes | IDW | Ozone |
| `SO2` | µg/m³ | yes | IDW | Sulphur dioxide |
| `CO` | µg/m³ | yes | IDW | Carbon monoxide |
| `AQI` | index | no | IDW | Composite air quality index |
| `NEAREST_OBS_KM` | km | no | IDW | Distance to nearest active sensor |
| `DATA_CONFIDENCE` | ratio | no | IDW | 0–1, decays with sensor distance |

**Risk levels:** `good` / `satisfactory` / `moderate` / `poor` / `very_poor` / `severe`  
(6-level vocabulary specific to air quality, following CPCB / WHO PM2.5 breakpoints; configurable via Rules Registry. The `h3_assessments` table permits domain-specific vocabularies — these 6 levels are normative for the `air` domain.)

---

### `fire` — Fire Detection

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `FRP_MW` | MW | yes | Direct (Method D) | Fire Radiative Power |
| `FIRE_SCORE` | index | no | Direct | log1p(FRP) / log1p(saturation), 0–1 |
| `FIRE_TYPE` | category | yes | Direct | crop_burn / waste_burn / vegetation / in_city |
| `DATA_CONFIDENCE` | ratio | no | Direct | Fixed at 0.80 (MODIS 1km pixel, cloud-limited) |

**Risk levels:** `low` / `moderate` / `high` / `severe`

---

### `heat` — Urban Heat

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `LST_CELSIUS` | °C | yes | Direct (Method D) | Land Surface Temperature |
| `UHI_NORM` | index | no | Direct | Normalised Urban Heat Island (LST vs city mean) |
| `GREEN_DEFICIT` | index | no | Direct | 1 − NDVI_norm |
| `HEAT_RISK_SCORE` | index | no | Direct | Weighted composite of UHI_norm and GREEN_DEFICIT (weights configurable via Rules Registry `heat.score_weights`) |
| `DATA_CONFIDENCE` | ratio | no | Direct | Cloud cover–adjusted |

**Risk levels:** `low` / `moderate` / `high` / `severe`

---

### `flood` — Flood Risk

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `FLOOD_RISK_INDEX` | index | no | Direct (Method D) | Composite 0–1 flood probability |
| `SAR_INUNDATION` | ratio | yes | Direct | Radar-detected surface water fraction |
| `SLOPE_RISK` | index | no | Direct | Terrain slope risk contribution |
| `SOIL_MOISTURE` | index | yes | Direct | Saturation proxy |
| `DATA_CONFIDENCE` | ratio | no | Direct | Cloud cover–adjusted |

**Risk levels:** `low` / `moderate` / `high` / `severe`

**Cross-domain note [INFORMATIVE]:** Flood risk reasoning benefits from drain capacity context (`FLOOD_DRAIN_CAPACITY` from the `drains` domain). This join MUST NOT be performed by the `flood` Driver at ingest time — Drivers MUST NOT read from `h3_signals` for other domains. The cross-domain enrichment is performed at reasoning time by the H3 Expert Agent, which reads both `flood` and `drains` signals via the Knowledge Store read interface.

---

### `water` — Water Quality

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `MNDWI` | index | yes | Direct (Method D) | Water body detection |
| `NDTI` | index | yes | Direct | Turbidity (sediment / sewage proxy) |
| `CI` | ratio | yes | Direct | Chlorophyll index (algal bloom proxy) |
| `FAI` | index | yes | Direct | Floating algae / foam index |
| `WATER_QUALITY_INDEX` | index | no | Direct | Composite 0–1 (higher = worse) |
| `DATA_CONFIDENCE` | ratio | no | Direct | Cloud cover–adjusted |

**Risk levels:** `good` / `moderate` / `poor` / `severe`

---

### `waste` — Waste / Illegal Dumping

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `WASTE_SITE_PROBABILITY` | ratio | no | Direct (Method D) | Spectral match to waste land cover |
| `BURN_FRP_MW` | MW | yes | Direct | Fire Radiative Power at waste site |
| `WASTE_RISK_INDEX` | index | no | Direct | Composite risk |
| `PERSISTENCE_DAYS` | count | no | Derived | Days site has been continuously flagged |
| `DATA_CONFIDENCE` | ratio | no | Direct | Cloud cover–adjusted |

**Risk levels:** `low` / `moderate` / `high` / `severe`

---

### `construction` — Construction Activity

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `ACTIVE_PERMIT_COUNT` | count | no | Centroid (Method B) | Open construction permits in cell |
| `SURFACE_CHANGE` | index | yes | Direct (Method D) | SAR-detected ground disturbance |
| `BSI` | index | yes | Direct | Bare Soil Index (vegetation loss proxy) |
| `CONSTRUCTION_RISK_INDEX` | index | no | Direct | Composite risk for AQ and noise impact |
| `DATA_CONFIDENCE` | ratio | no | Derived | min(permit_confidence, SAR_confidence); reflects the weaker of the two data sources |

**Risk levels:** `low` / `moderate` / `high` / `severe`

---

### `green` — Green Cover

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `NDVI` | index | yes | Direct (Method D) | Normalised Difference Vegetation Index |
| `GREEN_COVER_FRACTION` | ratio | no | Direct | Fraction of cell with NDVI > threshold |
| `GCCI` | index | no | Derived | Green Cover Change Index (positive = gain, negative = loss) |
| `DATA_CONFIDENCE` | ratio | no | Direct | Cloud cover–adjusted |

**Risk levels:** `low` / `moderate` / `high` / `severe`  
(Higher severity = greater vegetation loss or degradation. Note: thresholds in the Rules Registry for `green` are **ceiling** thresholds on `GREEN_COVER_FRACTION` — a cell with fraction ≤ threshold enters that risk level. This is the inverse of other domains where thresholds are floor values on a risk index.)

---

### `noise` — Noise

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `LAeq_DB` | dB(A) | no | IDW (Method A) | Ambient noise level |
| `NOISE_RISK_INDEX` | index | no | IDW | Weighted composite |
| `RECEPTOR_PROXIMITY` | index | no | Centroid (Method B) | Nearness to hospitals, schools (OSM) |
| `DATA_CONFIDENCE` | ratio | no | IDW | Sensor network coverage |

**Risk levels:** `low` / `moderate` / `high` / `severe`  
(WHO / CPCB noise standards as thresholds)

---

### `crowd` — Crowd / Gatherings

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `PEOPLE_COUNT` | count | no | Centroid (Method B) | Total people count from cameras whose zone centroid falls in cell |
| `CAMERA_COUNT` | count | no | Centroid (Method B) | Number of active cameras that reported in cell |
| `CROWD_DENSITY` | per_km² | no | Derived | PEOPLE_COUNT / cell_area_km² |
| `CROWD_INDEX` | index | no | Derived | Normalised crowd intensity 0–1 |
| `GATHERING_ALERT` | flag | no | Threshold | 1.0 if density ≥ gathering_threshold (default 500/km²) |
| `DATA_CONFIDENCE` | ratio | no | Fixed | 0.90 for cells with active cameras; 0.0 for uncovered cells |

**Risk levels:** `no_alert` / `elevated` / `high` / `critical`

**Assessment rule:** `GATHERING_ALERT = 1.0` → `risk_level = high`; density ≥ `high_density_threshold_per_km2` → `risk_level = critical`. Cells with no alert → `risk_level = no_alert`. Thresholds configurable via Rules Registry (`crowd.gathering_threshold_per_km2`, `crowd.high_density_threshold_per_km2`).

**Coverage note:** Cells with no camera coverage write no signals (absence ≠ zero crowd density).

---

### `weather` — Weather (Structural)

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `TEMP_C` | °C | no | IDW (Method A) | Air temperature interpolated from model grid points |
| `HUMIDITY_PCT` | % | no | IDW (Method A) | Relative humidity |
| `WIND_SPEED_MS` | m/s | no | IDW (Method A) | Wind speed |
| `WIND_DIR_DEG` | degrees | no | IDW (Method A) | Wind direction (meteorological convention) |
| `RAINFALL_MM` | mm | no | IDW (Method A) | Hourly precipitation |
| `DATA_CONFIDENCE` | ratio | no | Fixed | 0.70 (grid model output; classified as `model_estimate` per SIGNAL_SCHEMA.md which sets ≤ 0.7 for model estimates) |

**No assessments produced.**  
**Used by:** `flood` (rainfall accumulation), `air` (wind-driven dispersion), `heat` (ambient temperature baseline), `crowd` (outdoor event context)

---

### `buildings` — Buildings (Structural)

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `BUILDING_COUNT` | count | no | Centroid (Method B) | OSM footprints with centroid in cell |
| `BUILDING_DENSITY` | per_km² | no | Centroid | Count / cell_area_km² |
| `AVG_FLOORS` | floors | no | Centroid | Mean building:levels (default 1 if missing) |
| `COMMERCIAL_RATIO` | ratio | no | Centroid | Fraction with commercial/retail/office tag |
| `DATA_CONFIDENCE` | ratio | no | Fixed | 0.75 (informal structures often unmapped) |

**No assessments produced.**

---

### `roads` — Roads (Structural)

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `ROAD_LENGTH_M` | metres | no | Clip-and-sum (Method C) | Total clipped road length in cell |
| `ROAD_DENSITY` | m/km² | no | Derived | Road length / cell area |
| `MAJOR_ROAD_RATIO` | ratio | no | Clip-and-sum | Motorway/trunk/primary/secondary fraction |
| `INTERSECTION_COUNT` | count | no | Graph (Method B) | Nodes with degree ≥ 3 |
| `DATA_CONFIDENCE` | ratio | no | Fixed | 0.85 (minor lanes may be missing) |

**No assessments produced.**

---

### `drains` — Drains (Structural)

| Signal | Unit | Nullable | Assignment Method | Description |
|--------|------|----------|------------------|-------------|
| `DRAIN_LENGTH_M` | metres | no | Clip-and-sum (Method C) | Total waterway length in cell |
| `WATERWAY_COUNT` | count | no | Clip-and-sum | Distinct waterway features |
| `OPEN_DRAIN_RATIO` | ratio | no | Clip-and-sum | Open drain / canal vs culvert fraction |
| `FLOOD_DRAIN_CAPACITY` | index | no | Derived | Normalised drainage density 0–1 |
| `DATA_CONFIDENCE` | ratio | no | Fixed | 0.65 (open drains in informal areas often unmapped) |

**No assessments produced.**  
**Used by:** `flood` (primary modulator — low drain density + rainfall = elevated flood risk)

---

## Cross-Domain Relationships [INFORMATIVE]

The H3 Expert Agent uses co-elevation patterns across domains to generate cross-domain hypotheses. Common patterns:

| Signals co-elevated | Likely interpretation |
|--------------------|-----------------------|
| High `AQI` + active `FIRE_SCORE` nearby | Fire is the AQ emission source |
| High `AQI` + high `CONSTRUCTION_RISK_INDEX` + low `WIND_SPEED_MS` | Construction dust trapped by calm conditions |
| High `FLOOD_RISK_INDEX` + low `FLOOD_DRAIN_CAPACITY` | Infrastructure deficit amplifying natural flood risk |
| High `CROWD_DENSITY` + high `HEAT_RISK_SCORE` | Public health risk — cooling station advisory candidate |
| `GCCI` negative + high `WASTE_RISK_INDEX` + low `BUILDING_COUNT` | Possible illegal dumping on vacant land |
| `GATHERING_ALERT = 1` + high `AQI` | Cross-domain: consider event postponement advisory |

These patterns are informative guides for agent prompting — they are not normative rules. The H3 Expert Agent MUST verify cross-domain co-elevation using the `get_domain_cross_correlation` tool before asserting a causal link in a hypothesis.

---

## Domain Spec YAML [NORMATIVE]

Every canonical domain and every third-party domain that declares risk assessments MUST provide a domain spec YAML in `specifications/domain_specs/`. This file is the normative source for safety gates and blocked uses consumed by Apps when generating decision packets (see [App Contract — Safety Posture](../apps/APP_CONTRACT.md#safety-posture)).

**Required fields in a domain spec YAML:**

```yaml
domain: <domain_name>               # REQUIRED: matches Driver identity field
version: "1.0.0"                    # REQUIRED: SemVer
produces_assessments: true|false    # REQUIRED: matches Driver identity field

safety_gates:                       # REQUIRED for risk domains; OPTIONAL for structural
  - gate_id: <string>               # REQUIRED: unique within domain
    description: <string>           # REQUIRED: what this gate checks
    check: <string>                 # REQUIRED: the condition that must be true to pass
    status_if_fail: blocked|warn    # REQUIRED: severity of gate failure

blocked_uses:                       # REQUIRED for risk domains
  - <string>                        # One prohibited use per entry

risk_level_vocabulary:              # REQUIRED for risk domains
  - <risk_level_string>             # Ordered low to high (e.g. low, moderate, high, severe)
```

---

## Adding a New Domain

A third-party domain is any domain name not listed in this catalogue. New domains are fully supported:

1. Declare the domain name and signal table in a `signals.yaml` file
2. Implement the Driver Interface
3. Add the domain spec YAML to `specifications/domain_specs/` (following the structure above)
4. Register the driver in `drivers_registry.yaml`
5. Optionally add threshold rules to the Rules Registry

New domains are immediately visible to the H3 Expert Agent — it reads all signals for a cell regardless of domain. If the new domain's signal names are unfamiliar to a pre-trained agent, the agent system prompt should be updated to include them.
