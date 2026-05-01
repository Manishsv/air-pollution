## Getting started (deploy + run locally)

This project is a local-first “urban platform” prototype. It can run end-to-end with **best-effort live data** and **synthetic fallbacks**, and it exposes outputs via a **local API/SDK** and a **Streamlit dashboard**.

### Prerequisites

- **Python**: 3.10+ recommended (3.9 may work depending on your environment)
- **OS**: macOS/Linux recommended

### Setup

From the **repo root**:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### API keys / environment variables

Edit `.env` (loaded by `main.py` via `python-dotenv`):

- **`OPENAQ_API_KEY`** *(recommended)*: improves station data reliability (OpenAQ v3).
- **`FIRMS_API_KEY`** *(optional)*: enables NASA FIRMS fire detections.

If keys are missing, the pipeline still runs with **documented fallbacks**.

### Configure the run (city, area, resolution)

Edit `config.yaml`:

- **`spatial_mode`**: `bbox` (fast dev default) or `ward_polygon_path`
- **`bbox`**: north/south/east/west
- **`h3_resolution`**: grid resolution
- **`forecast_horizon_hours`**, **`lookback_days`**
- **`conformance.enabled`**: writes `data/outputs/conformance_report.json`

### Run the pipeline

```bash
python main.py
```

Useful variants:

```bash
python main.py --step audit
python main.py --force-refresh aq
python main.py --no-recommendations
python main.py --sample
python main.py --step sensor-siting
```

### Run conformance audit (contracts)

```bash
python main.py --step conformance
```

This writes:

- `data/outputs/conformance_report.json`

### View the dashboard

From the **repo root**:

```bash
streamlit run review_dashboard/app.py
```

The dashboard uses the **SDK** (`UrbanPlatformClient`) which calls the **local API** (files under `data/processed/` and `data/outputs/`).

## Camera “Crowd” use case (people_count)

This is an example of adding a new source + derived signal:

- **Provider contract**: `specifications/provider_contracts/video_camera_people_count_feed.v1.schema.json`
- **Edge publisher (file sink)**: writes JSONL to `data/edge/video_camera_people_count.jsonl`
- **Ingest (phase 1)**: reads JSONL and appends to `data/processed/observation_store.parquet`
- **Dashboard**: Crowd tab queries `get_observations(variable="people_count")`

### Run edge publisher (writes JSONL)

Dummy (always writes 0):

```bash
python -m urban_platform.connectors.camera.publisher --device-id laptop-001
```

YOLO (local camera inference; requires deps):

```bash
pip install -r requirements.txt
python -m urban_platform.connectors.camera.publisher --device-id laptop-001 --use-yolo --camera-index 0
```

### Ingest JSONL into observation_store (one-shot)

```bash
python - <<'PY'
from urban_platform.connectors.camera.ingest_file import ingest_video_camera_people_count_jsonl
print(ingest_video_camera_people_count_jsonl(base_path="."))
PY
```

After ingestion, the Crowd tab should show latest counts per `entity_id`.

## How to add a new data source

Use the contract families:

1) **Provider contract** (`specifications/provider_contracts/`)
   - Add a `*.v1.schema.json` describing the raw feed shape.
   - Register it in `specifications/manifest.json` with `contract_type: "provider"`.

2) **Connector** (`urban_platform/connectors/...`)
   - Fetch/parse upstream data.
   - Emit provider-shaped payloads or raw DataFrames as needed.

3) **Normalize to platform objects**
   - Prefer the canonical Observation/Entity/Feature/Event shapes (see `urban_platform/standards/`).
   - Validate using `urban_platform.standards.validators`.

4) **Persist**
   - Observations → `data/processed/observation_store.parquet`
   - Features → `data/processed/feature_store.parquet`

5) **Conformance**
   - Run `python main.py --step conformance` and ensure the report is clean.

## How to add a new model / processing step

General pattern:

- Add a new module under `src/` (legacy pipeline) or `urban_platform/models|processing/` (platform layer).
- Ensure inputs come from canonical stores (`observation_store`, `feature_store`) when possible.
- Write outputs to `data/outputs/` and register/validate with consumer contracts if you want stability guarantees.

## How to build an app (new use-case tab)

The Streamlit UI is in `review_dashboard/app.py`.

- Add a new tab (e.g., “Heat”, “Crowd”, “Traffic”).
- Use the SDK:
  - `client.get_observations(...)`
  - `client.get_features(...)`
  - `client.get_source_reliability(...)`
  - `client.get_decision_packets(...)`
- Keep the UI reading **only** from persisted artifacts (processed/output files), not in-memory pipeline variables.

