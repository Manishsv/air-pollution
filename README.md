## Probabilistic urban air-quality observability MVP (Bengaluru/Delhi)

This project is **not an operational air-quality management system**.

It is a local, reliability-first prototype for:

- **data fusion / observability** under sparse station coverage
- **probabilistic PM2.5 forecasting** (baseline models + uncertainty estimates)
- **provenance-first decision-support workflow design** (with safety gates)

The output should be interpreted as **indicative** unless station coverage and data provenance are strong.

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

### Project layout

```
air_quality_mvp/
  README.md
  requirements.txt
  .env.example
  config.yaml
  data/
    raw/
    processed/
      cache/
    outputs/
  notebooks/
    01_exploration.ipynb
  src/
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
    pipeline.py
  main.py
```

### Setup

- **Python**: 3.10+ recommended

```bash
cd air_quality_mvp
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

Useful CLI options:

```bash
python main.py --step audit
python main.py --force-refresh aq
python main.py --no-recommendations
python main.py --sample
```

Outputs land in:

- `data/processed/h3_grid.geojson`
- `data/processed/static_features.geojson`
- `data/processed/model_dataset.csv`
- `data/outputs/pm25_model.joblib`
- `data/outputs/metrics.json`
- `data/outputs/data_audit.json`
- `data/outputs/scale_analysis.json`
- `data/outputs/hotspot_recommendations.geojson`
- `data/outputs/current_pm25_map.html`
- `data/outputs/forecast_pm25_map.html`
- `data/outputs/hotspot_recommendations_map.html`

Open the HTML files in a browser.

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

### How hotspot recommendations are generated

This MVP generates recommendations in a deliberately **simple and explainable** way:

1. **Forecast PM2.5 per H3 cell (with uncertainty)**
   - A baseline regressor predicts `forecast_pm25` for each H3 cell for \(t + forecast_horizon_hours\).
   - For RandomForest, the MVP outputs quantiles (P10/P50/P90) and std as a simple uncertainty estimate.

2. **Category labels use Indian AQI-style PM2.5 breakpoints**
   - The MVP outputs `pm25_category_india` based on `pm25_categories_india` in `config.yaml`.

3. **Likely contributing factors (proxy-based, rule-driven)**
   - The MVP reports `likely_contributing_factors` using conservative proxy rules.
   - It does **not** claim validated causal attribution.

4. **Safety gates**
   - If provenance/audit gates fail (e.g., synthetic AQ), operational recommendations are blocked and replaced with an explicit reason.

### Known limitations (intentional for MVP reliability)

- Synthetic AQ/weather kick in when APIs fail; this is documented but not “real” air-quality truth.
- AQ interpolation is simple **inverse distance weighting**.
- Model is a baseline tree regressor; no spatial-temporal deep learning.
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

### How this can connect later to DIGIT / Airawat

- **DIGIT**: surface `hotspot_recommendations.geojson` as a layer + drive a simple “work order” workflow from hotspot cells.
- **Airawat**: swap in higher quality emissions inventories / dispersion signals and calibrate the forecast model with validated station data.

