# Urban Heat Risk SDK Walkthrough

A read-only walkthrough of the urban heat risk use case using the AirOS SDK
(`urban_platform.sdk`) and the heat pipeline public surface.

**Run from repo root:**
```bash
python examples/sdk/heat_risk_walkthrough.py
```

---

## Overview

The urban heat risk use case combines:
1. **OpenMeteo temperature observations** — hourly temperature, apparent temperature, humidity
   for a city bounding box (no API key required)
2. **OSM green cover** — parks, forests, grass, and water bodies per H3 cell (via osmnx)

Together they produce a **heat risk score** per H3 cell and a ranked list of **intervention
candidates** (cells most in need of tree planting, shade structures, cool pavement).

All outputs are **review-support only** — human review is required before any operational
or public-facing action.

---

## 1. Platform inventory

```python
import urban_platform.sdk as sdk

sdk.list_app_ids()
# → ['flood_risk_review', 'program_reporting_review', 'urban_heat_risk_review']

sdk.list_contract_keys()
# Includes: 'heat_risk_dashboard', 'heat_intervention_candidates'
```

`urban_heat_risk_review` is the app identifier for the heat use case.
Both consumer contracts are registered in the manifest and accessible via the SDK.

---

## 2. App descriptor & safety gates

```python
descriptor = sdk.get_app_descriptor("urban_heat_risk_review")
safety = descriptor["safety"]

safety["review_support_only"]    # True
safety["human_review_required"]  # True
safety["blocked_uses"]
# [
#   "automated_displacement_or_demolition",
#   "public_heat_advisory_without_authorization",
#   "enforcement_or_fines_from_pipeline_outputs",
#   "operational_action_on_synthetic_data",
# ]
```

The app descriptor encodes the governance model:
- **review_support_only**: this app produces inputs for human reviewers, not automated decisions
- **human_review_required**: no output should be acted on without a human in the loop
- **blocked_uses**: lists actions that must never be automated from this pipeline

---

## 3. Consumer contract schemas

```python
dashboard_schema = sdk.get_contract_schema("heat_risk_dashboard")
# Required fields: generated_at, city_id, heat_cells, summary,
#                  data_quality_flag, provenance_summary

candidates_schema = sdk.get_contract_schema("heat_intervention_candidates")
# Required fields: generated_at, city_id, candidates,
#                  data_quality_flag, provenance_summary
```

Both schemas use `data_quality_flag` to surface provenance:
- `"real"` — temperature data from a live API
- `"synthetic"` — demo/offline fallback (must not be used operationally)
- `"unavailable"` — temperature feed returned no data

---

## 4. Connectors

### Temperature observations (OpenMeteo)

```python
from urban_platform.connectors.heat.openmeteo import fetch_temperature_observations

df = fetch_temperature_observations(
    city_name="bangalore",
    lat_min=12.87, lon_min=77.49,
    lat_max=13.07, lon_max=77.69,
    lookback_days=1,
)
# Returns DataFrame: station_id, latitude, longitude, timestamp,
#                    temperature_c, apparent_temperature_c,
#                    relative_humidity_pct, data_source, quality_flag
```

- Samples a 3×3 grid of points across the bounding box
- Returns empty DataFrame on any network failure (no exception raised)
- `data_source` is always `"openmeteo"`

### Green cover (OSM via osmnx)

```python
from shapely.geometry import box
from urban_platform.connectors.heat.osm_green_cover import compute_green_cover

boundary = box(77.49, 12.87, 77.69, 13.07)  # lon_min, lat_min, lon_max, lat_max
df = compute_green_cover(boundary, h3_resolution=9)
# Returns DataFrame: h3_id, green_cover_fraction, water_proximity_score,
#                    osm_feature_count
```

- Fetches parks, forests, grass, tree rows, water bodies from OpenStreetMap
- `green_cover_fraction`: 0–1, fraction of H3 cell covered by green features
- `water_proximity_score`: 1.0 if water in cell, 0.0 if no water within 500 m, interpolated
- Returns empty DataFrame on OSM or H3 failure

---

## 5. Pipeline outputs

```python
from urban_platform.applications.heat.heat_pipeline import (
    build_heat_risk_dashboard,
    build_intervention_candidates,
)

bbox = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)

dashboard = build_heat_risk_dashboard(
    temperature_df=temp_df,
    green_cover_df=green_df,
    h3_resolution=9,
    city_id="bangalore",
    **bbox,
)
```

The dashboard payload includes:
- `summary.city_median_temperature_c` — city-wide baseline
- `summary.max_heat_risk_score` — highest risk cell score
- `summary.high_risk_cell_count` — cells with score ≥ 0.66
- `heat_cells` — per-H3 list with `heat_index_c`, `uhi_intensity`,
  `green_cover_fraction`, `water_proximity_score`, `heat_risk_score`
- `active_warnings` — IDW interpolation caveat, synthetic data warning
- `data_quality_flag` — provenance summary
- `provenance_summary.sources` — e.g. `["openmeteo", "osm_via_osmnx"]`

### Heat risk score formula

```
heat_risk_score = 0.6 × uhi_norm + 0.4 × green_deficit
```

Where:
- `uhi_intensity = cell_heat_index − city_median` (Urban Heat Island signal)
- `uhi_norm` = UHI intensity normalized to [0, 1] across all cells
- `green_deficit = 1.0 − green_cover_fraction`

---

## 6. Intervention candidates

```python
candidates = build_intervention_candidates(
    temperature_df=temp_df,
    green_cover_df=green_df,
    h3_resolution=9,
    city_id="bangalore",
    **bbox,
)
```

Returns the top-10 H3 cells ranked by `heat_risk_score` descending. Each candidate has:
- `h3_id` — H3 cell identifier
- `risk_score` — composite heat risk (0–1)
- `green_deficit` — how much greening is needed (0–1)
- `uhi_intensity` — Urban Heat Island signal in °C
- `water_proximity_score` — cooling benefit from nearby water
- `suggested_interventions` — rule-based list: `tree_planting`, `shade_structures`,
  `green_roofs`, `cool_pavement`

Suggestions are heuristic-based (not certified recommendations) and require expert
review before implementation.

---

## Safety gates

| Gate | When triggered | Effect |
|------|---------------|--------|
| `data_quality_flag = "synthetic"` | Temperature data is demo fallback | `provenance_summary.synthetic_used = True`; warning in `active_warnings` |
| IDW interpolation in use | No in-cell temperature stations | `idw_interpolation_in_use` warning emitted |
| `data_quality_flag = "unavailable"` | No temperature data at all | All scores unreliable; empty candidates |

The pipeline **does not block output on synthetic data** — it surfaces the flag so
the human reviewer can decide. Consumer applications must display the `active_warnings`
list and the `data_quality_flag` prominently.

---

## Running the tests

```bash
python -m pytest tests/test_heat_openmeteo_connector.py   # 14 tests
python -m pytest tests/test_heat_osm_green_cover.py       # 18 tests
python -m pytest tests/test_heat_pipeline.py              # 33 tests
python -m pytest tests/test_sdk_heat_risk_walkthrough.py  # 28 tests
```
