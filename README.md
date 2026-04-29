## Air Quality MVP (Bengaluru/Delhi) — hotspot detection + 12–24h PM2.5 forecasting

Local, reliable MVP that builds a **grid-based urban air-quality intelligence prototype**:

- Boundary (bbox / ward polygon / full city)
- H3 grid
- OSM features → static grid covariates
- AQ data (OpenAQ best-effort, **synthetic fallback** so pipeline always runs)
- Weather data (Open-Meteo best-effort, **synthetic fallback**)
- Optional fire signals (NASA FIRMS if `FIRMS_API_KEY` is set)
- Baseline forecasting model (persistence + RandomForest + optional XGBoost)
- Hotspot classification + intervention recommendations
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

Outputs land in:

- `data/processed/h3_grid.geojson`
- `data/processed/static_features.geojson`
- `data/processed/model_dataset.csv`
- `data/outputs/pm25_model.joblib`
- `data/outputs/metrics.json`
- `data/outputs/hotspot_recommendations.geojson`
- `data/outputs/current_pm25_map.html`
- `data/outputs/forecast_pm25_map.html`
- `data/outputs/hotspot_recommendations_map.html`

Open the HTML files in a browser.

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
- **AQ**: OpenAQ (best-effort) → **synthetic station fallback**
- **Weather**: Open-Meteo archive API → **synthetic weather fallback**
- **Fire events**: NASA FIRMS (optional; only if `FIRMS_API_KEY` is set)

### Known limitations (intentional for MVP reliability)

- Synthetic AQ/weather kick in when APIs fail; this is documented but not “real” air-quality truth.
- AQ interpolation is simple **inverse distance weighting**.
- Model is a baseline tree regressor; no spatial-temporal deep learning.
- OSM feature extraction uses straightforward spatial joins; for full-city scale you’d want spatial indexing + chunking.

### Replacing fallback AQ with CPCB/CAAQMS later

Implement a loader in `src/aq_data.py` that produces the same schema as `fetch_openaq_pm25`:

- `station_id, station_name, latitude, longitude, timestamp, pm25, data_source`

Then the pipeline will automatically:

- map stations to H3
- interpolate to all cells
- rebuild the panel dataset and retrain the model

### How this can connect later to DIGIT / Airawat

- **DIGIT**: surface `hotspot_recommendations.geojson` as a layer + drive a simple “work order” workflow from hotspot cells.
- **Airawat**: swap in higher quality emissions inventories / dispersion signals and calibrate the forecast model with validated station data.

