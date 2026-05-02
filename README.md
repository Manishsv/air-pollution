## AirOS — Urban Intelligence Platform

**AirOS (Air OS)** is an **urban intelligence platform**: a closed-loop city data and decision-support system. It is not a single-purpose application.

Air pollution management, heat risk assessment, flood preparedness, mobility planning, crowd monitoring, and sensor siting are all **applications that can be built on top of AirOS** — sharing the same data infrastructure, reliability layer, and decision-support tools.

- **Getting started**: [`GETTING_STARTED.md`](GETTING_STARTED.md)
- **Contract architecture**: [`specifications/ARCHITECTURE_NOTE.md`](specifications/ARCHITECTURE_NOTE.md)
- **Specifications**: [`specifications/README.md`](specifications/README.md)
- **Specs-first development**: [`docs/SPECS_FIRST_DEVELOPMENT.md`](docs/SPECS_FIRST_DEVELOPMENT.md)
- **Vision**: [`docs/AIR_OS_VISION.md`](docs/AIR_OS_VISION.md)
- **Actor model**: [`docs/ACTOR_MODEL.md`](docs/ACTOR_MODEL.md)
- **Use-case roadmap**: [`docs/USE_CASE_ROADMAP.md`](docs/USE_CASE_ROADMAP.md)
- **Data-source discovery**: [`docs/DATA_SOURCE_CATALOG.md`](docs/DATA_SOURCE_CATALOG.md)
- **Urban governance context (India)**: [`docs/URBAN_CONTEXT_INDIA.md`](docs/URBAN_CONTEXT_INDIA.md)
- **Architecture overview (text diagrams)**: [`docs/AIR_OS_ARCHITECTURE_OVERVIEW.md`](docs/AIR_OS_ARCHITECTURE_OVERVIEW.md)
- **Federated deployment (node-first)**: [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md)
- **Agency node model**: [`docs/AGENCY_NODE_MODEL.md`](docs/AGENCY_NODE_MODEL.md)
- **Cross-agency coordination / Network Layer**: [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](docs/CROSS_AGENCY_COORDINATION_LAYER.md)
- **AI CoE operating strategy**: [`docs/AI_COE_OPERATING_STRATEGY.md`](docs/AI_COE_OPERATING_STRATEGY.md)
- **Specs policy (machine-readable)**: [`specifications/spec_policy.yaml`](specifications/spec_policy.yaml)

### What is AirOS?

AirOS is to city data what an operating system is to a computer: applications run on top of it, while the platform handles the common, hard parts (connectors, standardized objects, reliability scoring, conformance, APIs/SDKs, decision packets).

This is **not** an operational system out of the box. It is a reliability-first prototype intended to demonstrate how trusted city intelligence can be built and improved over time.

### Architecture (condensed)

```
Actors → Apps/UI (presentation) → Domain applications (contract-shaped outputs)
      → Processing/features → Canonical objects → Connectors → Data fabric
      ↘ Specs+Conformance (source of truth) ↘ CI+Supervisor (quality gates)

Federation: AirOS Nodes ↔ (optional) Network Layer ↔ transports (email/api/bus/file)
```

### AirOS is a closed feedback loop

This is not just a data pipeline. AirOS is designed as a **closed loop**:

1) ingest + standardize city signals  
2) assess source reliability and provenance  
3) build reusable features  
4) run models and produce recommendations/decision packets  
5) humans review and decide  
6) outcomes are measured and fed back to improve models and playbooks

### Current reference application: air pollution (PM2.5)

The reference app in this repo is **probabilistic air-quality observability**:

- data fusion under sparse station coverage
- probabilistic PM2.5 forecasting (baseline models + uncertainty estimates)
- provenance-first decision support (quality gates + human review)

Outputs should be interpreted as **indicative** unless station coverage and provenance are strong.

- Boundary (bbox / ward polygon / full city)
- H3 grid
- OSM features → static grid covariates
- AQ data (OpenAQ v3 best-effort, **synthetic fallback** so pipeline always runs)
- Weather data (Open-Meteo best-effort, **synthetic fallback**)
- Optional fire signals (NASA FIRMS if `FIRMS_API_KEY` is set)
- Baseline forecasting model (persistence + RandomForest + optional XGBoost)
- **Data provenance + audit + safety gates** before any recommendations
- Proxy-based **likely contributing factors** (not validated attribution)
- GeoJSON exports + Folium HTML maps

### Algorithm (simple overview)

The algorithm is intentionally simple:

**Break the area into small grid cells, collect signals for each cell, estimate pollution now and later, then explain the uncertainty and suggest cautious actions.**

1) **Divide the area into grid cells**
- We use **H3** hexagonal cells. Each cell is one small unit of analysis.

2) **Add static city features (proxies)**
- From **OpenStreetMap (OSM)** (current implementation), we extract per-cell proxies such as:
  - **roads** → traffic/emission proxy
  - **buildings / built-up ratio** → built environment proxy
  - **land use** → industrial / commercial / residential / green areas
  - **POIs** → activity proxy
- You can swap/augment these with other building/landcover sources later (e.g., Microsoft/Google building footprints), but the MVP currently uses OSM for reliability.

3) **Add air-quality readings (PM2.5)**
- From **OpenAQ/CPCB-like station feeds** (OpenAQ v3 in this MVP), we ingest station-hourly PM2.5.
- Cells with stations get **observed** values.
- Cells without stations get **estimated** values from nearby stations using **IDW (inverse distance weighting)** and are marked clearly as **interpolated** (with distance + station count recorded).
- If live AQ fails, the pipeline uses a **documented synthetic fallback** so the workflow is still runnable end-to-end.

4) **Add weather**
- We add wind, humidity, rain, temperature (Open-Meteo). Weather matters because pollution can disperse, accumulate, or advect.
- If live weather fails, a **synthetic fallback** is used (with provenance flags).

5) **Add optional fire/burning signals**
- If `FIRMS_API_KEY` is set, we pull satellite fire detections (NASA FIRMS) as a coarse burning proxy.
- If no detections exist, we record that as **real/no-fires-detected** (not “missing data”).

6) **Build a table (panel dataset)**
- Each row is:

  **(grid cell, time)**  
  + static proxies (roads, buildings, land use, POIs)  
  + current PM2.5 + PM2.5 lags  
  + weather  
  + fire proxy  
  → **PM2.5 after 12 hours** (configurable horizon)

7) **Train a simple model**
- First compare against a baseline: **future PM2.5 = current PM2.5** (persistence).
- Then train a baseline ML model like **RandomForest / XGBoost**.

8) **Forecast PM2.5 + uncertainty**
- For each grid cell, we predict PM2.5 at \(t + horizon\).
- We also output uncertainty (RandomForest quantiles / band heuristics), not just one number.

9) **Mark confidence (provenance + audit gates)**
- The system checks:
  - Was AQ **real / interpolated / synthetic**?
  - How far is the nearest station? How many stations were used?
  - How uncertain is the forecast band?
- Outputs explicitly report **what we predict** and **how much to trust it**.

10) **Suggest cautious actions**
- Based on **likely contributing factors** (proxy-based, non-causal):
  - high road density → traffic management
  - high built-up/dust proxy → road sweeping / construction inspection
  - fire signal → field verification
  - low wind → advisory / preventive measures
  - low confidence → verify before acting

**Honest one-line version:** the system does not directly “know” pollution causes. It combines measured PM2.5, weather, and city-form proxies to forecast likely hotspots and recommend cautious, confidence-rated actions.

### Project layout

```
<repo root>/
  README.md
  GETTING_STARTED.md
  requirements.txt
  .env.example
  config.yaml
  data/
    raw/
    processed/
      cache/
    outputs/
    edge/
  notebooks/
    01_exploration.ipynb
  src/                    # legacy AQ MVP pipeline (see specifications/ARCHITECTURE_NOTE.md — src vs urban_platform)
    __init__.py
    cache.py
    config.py
    boundary.py
    grid.py
    osm_features.py
    aq_data.py
    weather_data.py
    fire_data.py
    feature_engineering.py
    model.py
    recommendations.py
    visualization.py
    sensor_siting.py
    pipeline.py
  urban_platform/          # layered platform architecture
    connectors/
    standards/
    registries/
    fabric/
    processing/
    models/
    decision_support/
    applications/
    outputs/
    common/
  review_dashboard/
    app.py
    components/
  specifications/
    manifest.json
    provider_contracts/
    platform_objects/
    consumer_contracts/
    openapi/
  main.py
```

**Code layout:** `main.py` calls `urban_platform.applications.air_pollution.pipeline`, which **delegates** to `src.pipeline` for the reference AQ run. **`src/`** is legacy AQ only; **new domains and shared platform code** belong under **`urban_platform/`**. Full ownership map and migration guidance: [`specifications/ARCHITECTURE_NOTE.md`](specifications/ARCHITECTURE_NOTE.md) (*Repository code layout: `src/` vs `urban_platform/`*).

During the migration to `urban_platform/`, **connectors expose two entrypoints**:

- **raw**: `fetch_*_raw(config)` returns the legacy-shaped DataFrame (for backward compatibility)
- **schema-native**: `fetch_*_observations(config, grid_gdf=None)` returns canonical **Observation** records (validated)

The current reference air-pollution pipeline still uses raw fetchers internally and converts to Observations immediately after ingestion.

### Setup

- **Python**: 3.10+ recommended

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Run

Default config runs **fast `bbox` mode** (recommended for development):

```bash
python main.py
```

### Conformance audit (contracts)

Run a full specification conformance audit (schemas, manifest, outputs, local API/SDK responses):

```bash
python main.py --step conformance
```

This writes `data/outputs/conformance_report.json`.

Useful CLI options:

```bash
python main.py --step audit
python main.py --force-refresh aq
python main.py --no-recommendations
python main.py --sample
python main.py --step sensor-siting
python main.py --sensor-siting-mode coverage
python main.py --sensor-siting-mode hotspot_discovery
python main.py --sensor-siting-mode equity
```

### Review dashboard (Streamlit)

Run the dashboard UI:

```bash
streamlit run review_dashboard/app.py
```

The dashboard uses the **SDK** (`UrbanPlatformClient`) to read persisted artifacts and supports tabs for multiple use cases (e.g., Air Pollution + Crowd).

Outputs land in:

- `data/processed/h3_grid.geojson`
- `data/processed/static_features.geojson`
- `data/processed/observation_store.parquet`
- `data/processed/feature_store.parquet`
- `data/processed/model_dataset.csv`
- `data/outputs/pm25_model.joblib`
- `data/outputs/metrics.json`
- `data/outputs/data_audit.json`
- `data/outputs/scale_analysis.json`
- `data/outputs/hotspot_recommendations.geojson`
- `data/outputs/current_pm25_map.html`
- `data/outputs/forecast_pm25_map.html`
- `data/outputs/hotspot_recommendations_map.html`
- `data/outputs/decision_packets.json`
- `data/outputs/decision_packets/<packet_id>.json`
- `data/outputs/sensor_siting_candidates.geojson` (if `sensor_siting.enabled` and after a full run)
- `data/outputs/sensor_siting_candidates_map.html`
- A `sensor_siting_summary` block inside `data/outputs/metrics.json` when sensor siting runs

Open the HTML files in a browser.

### Crowd (camera people_count) example

This repo also includes a privacy-first “Crowd” example:

- Edge publisher writes provider-contract JSONL: `data/edge/video_camera_people_count.jsonl`
- File ingestion normalizes into `data/processed/observation_store.parquet`
- Dashboard “Crowd” tab shows latest `people_count` per `entity_id`

See [`GETTING_STARTED.md`](GETTING_STARTED.md) for the exact commands (dummy publisher and YOLO mode).

### Human review and decision packets

**Recommendations are not final decisions.** The system produces decision support outputs that must be reviewed by a human officer before any operational action.

For each grid-cell recommendation, the pipeline writes a **decision packet** that bundles:

- **evidence** (observations, nearby stations, weather, static + dynamic features)
- **provenance** (real/interpolated/synthetic flags, interpolation method, station distance/count, warnings)
- **confidence + uncertainty** (confidence score, data quality score, uncertainty band / quantiles where available)
- **review guidance** (questions, verification steps, and “when not to act” reminders)

Important:

- Proxy-based **likely contributing factors are not causal attribution**.
- Do not issue enforcement actions without **field verification**.
- Do not act solely on **synthetic data** or low-confidence outputs.

### Sensor siting support

The `src/sensor_siting.py` step helps **prioritize candidate H3 cells for adding a new AQ sensor**.

**This module does not find the most polluted places.** It ranks candidate cells where an **additional** sensor might **reduce map uncertainty**, improve spatial coverage proxies, or meet an **equity-style** objective (urban exposure proxies using OSM static features such as roads, POIs, built-up fraction, low green fraction). Modes (`config.sensor_siting.mode` or `--sensor-siting-mode`) are **`coverage`**, **`hotspot_discovery`** (forecast mean × uncertainty proxies — still not “hottest pollution” as ground truth), and **`equity`**.

**Limitations:** Results assume sparse interpolation and imperfect uncertainty bands; IDW/neighbor summaries are **not** ground-truth dispersion. Outputs are **planning support only**; **field validation** is required before deployment. If the audit shows synthetic AQ or failing quality gates, candidates are still written but flagged with **`planning_confidence: low`** and a fixed demonstration warning banner.

### When outputs should NOT be used

Do **not** use outputs for real decisions when:

- maps show **“WARNING: Synthetic AQ data used”**
- real station coverage is low (audit flags low confidence)
- the ML model **does not outperform** the persistence baseline (metrics warning)
- most grid PM2.5 values are interpolated from sparse stations

In those cases, the MVP will still generate maps, but recommendations are blocked or downgraded to **field verification** language.

### Spatial modes

Set `spatial_mode` in `config.yaml`:

- **`bbox` (default)**: builds a polygon from bbox and downloads OSM **only within that polygon** (no city road graph download).
- **`ward`**: provide `ward_polygon_path` (GeoJSON with a polygon).
- **`full_city`**: uses OSMnx geocoding boundary; roads use `graph_from_place(..., network_type="drive")`.

### Caching

All expensive steps cache into `data/processed/cache/` with deterministic filenames:

Example:

`data/processed/cache/bengaluru_india_bbox_12.97000_13.02000_77.57000_77.62000_h3r7_roads.geojson`

Controls in `config.yaml`:

- `cache.enabled`: load cached artifacts
- `cache.force_refresh`: re-download and overwrite
- `cache.ttl_days`: invalidate cache after N days

### Data sources (MVP)

- **Boundary & OSM features**: OpenStreetMap via `osmnx`
- **AQ**: OpenAQ **v3** (best-effort; API key recommended) → **synthetic station fallback**
- **Weather**: Open-Meteo archive API → **synthetic weather fallback**
- **Fire events**: NASA FIRMS (optional; only if `FIRMS_API_KEY` is set)

### OpenAQ v3 API key (recommended)

OpenAQ **v2 is retired** and returns HTTP 410. The MVP uses **OpenAQ v3** which may require an API key (otherwise you may see HTTP 401 and the pipeline will fall back to synthetic AQ).

1. Copy env file:

```bash
cp .env.example .env
```

2. Set:

- `OPENAQ_API_KEY=...`

### Data provenance (first-class)

Major datasets (AQ panel, model dataset, GeoJSON outputs) carry provenance fields such as:

- `aq_source_type`: real | interpolated | synthetic | unavailable
- `weather_source_type`: real | synthetic | unavailable
- `fire_source_type`: real | unavailable
- `interpolation_method`, `nearest_station_distance_km`, `station_count_used`
- `data_quality_score`, `warning_flags`

If synthetic data is used anywhere, outputs and maps are required to show visible warnings.

### Data audit (before modelling)

Before training the model, the pipeline writes:

- `data/outputs/data_audit.json`

This includes station counts, interpolated/synthetic ratios, nearest-station distance stats, and whether recommendations are allowed.

### Source reliability and observation quality

Sensors and external feeds can degrade: they may go offline, become stale, flatline at a constant value, or emit impossible/spiky readings.

The platform runs a **Source Reliability Layer** before persisting and trusting observations:

- **What it produces**: `data/outputs/source_reliability.json` (one row per `entity_id + variable`) with a transparent `status` (healthy/degraded/suspect/offline/unknown), `reliability_score` (0–1), and the concrete `reliability_issues` that triggered penalties.
- **How it affects observations**: the canonical `data/processed/observation_store.parquet` gains:
  - `source_reliability_score`, `source_reliability_status`, `source_reliability_issues`
  - `original_quality_flag` (preserved)
  - adjusted `confidence = confidence * source_reliability_score`
  - if a source is `suspect`/`offline`, `quality_flag` is set to `suspect`
- **Why it matters**: reliability affects observation confidence, downstream confidence, decision packet risk warnings, and the review dashboard’s system warnings.

This layer is reusable for AQ sensors, flood sensors, traffic feeds, weather feeds, and other IoT sources: it operates on canonical Observations and does not depend on air-pollution-specific model logic.

### How hotspot recommendations are generated

This MVP generates recommendations in a deliberately **simple and explainable** way:

1. **Forecast PM2.5 per H3 cell (with uncertainty)**
   - A baseline regressor predicts `forecast_pm25` for each H3 cell for \(t + forecast_horizon_hours\).
   - For RandomForest, the MVP outputs quantiles (P10/P50/P90) and std as a simple uncertainty estimate.

2. **Category labels use Indian AQI-style PM2.5 breakpoints**
   - The MVP outputs `pm25_category_india` based on `pm25_categories_india` in `config.yaml`.

### AQI Interpretation

- This system reports **PM2.5-based categorization only** (configured as `aqi_standard: CPCB_PM25_ONLY`).
- It **does not compute full AQI** (multi-pollutant AQI requires additional pollutants and aggregation rules).
- Interpret `pm25_category_india` as a **PM2.5 breakpoint category**, not a full AQI index value.

3. **Likely contributing factors (proxy-based, rule-driven)**
   - The MVP reports `likely_contributing_factors` using conservative proxy rules.
   - It does **not** claim validated causal attribution.

4. **Safety gates**
   - If provenance/audit gates fail (e.g., synthetic AQ), operational recommendations are blocked and replaced with an explicit reason.

### Known limitations (intentional for MVP reliability)

- Synthetic AQ/weather kick in when APIs fail; this is documented but not “real” air-quality truth.
- AQ interpolation is simple **inverse distance weighting**.
- Model is a baseline tree regressor; no spatial-temporal deep learning.
- Prediction intervals are **approximate and not formally calibrated** (RandomForest quantile-based heuristic).
  - Future work: residual-based calibration / conformal intervals.
- OSM feature extraction uses straightforward spatial joins; for full-city scale you’d want spatial indexing + chunking.
- Station coverage is often sparse for Indian cities in OpenAQ; replace with CPCB/CAAQMS for operational use.

### Replacing fallback AQ with CPCB/CAAQMS later

Implement a loader in `src/aq_data.py` that produces the same schema as `fetch_openaq_pm25`:

- `station_id, station_name, latitude, longitude, timestamp, pm25, data_source`

Then the pipeline will automatically:

- map stations to H3
- interpolate to all cells
- rebuild the panel dataset and retrain the model

### API call minimization and caching

To avoid calling external APIs repeatedly for the same area/time window:

- The pipeline caches each expensive artifact (boundary, grid, OSM, AQ, weather, dataset) under `data/processed/cache/`.
- For **OpenAQ v3**, the MVP additionally caches:
  - the **locations** response (bbox query, and a centroid+radius fallback query), and
  - the **per-sensor hourly time series** (`/v3/sensors/{id}/hours`),
  so reruns do not re-download the same data until `cache.ttl_days` expires.

Controls:

- `cache.enabled`: use cached artifacts when valid
- `cache.force_refresh`: re-download and overwrite caches
- `cache.ttl_days`: cache time-to-live in days
