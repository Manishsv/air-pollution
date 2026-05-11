"""Synthetic fallback data generators for the flood domain.

These are used when no live rainfall gauge or satellite data is available,
so the flood pipeline still produces a risk surface for display and analysis.

Moved from review_dashboard/components/flood_panel.py — drivers layer only,
no Streamlit dependencies.
"""
from __future__ import annotations

import pandas as pd


def synthetic_rainfall(bbox: dict) -> pd.DataFrame:
    """3×3 grid of synthetic rainfall matching OpenMeteo's sampling pattern.

    NE corner is the storm cell (45 mm/hr), creating a flood risk gradient
    across the city with two elevated-risk clusters at center and NE corner.
    """
    lats = [bbox["lat_min"], (bbox["lat_min"] + bbox["lat_max"]) / 2, bbox["lat_max"]]
    lons = [bbox["lon_min"], (bbox["lon_min"] + bbox["lon_max"]) / 2, bbox["lon_max"]]
    # [lat_row][lon_col]: south→north rows, west→east columns
    intensities = [
        [0.5,  2.0,  5.0],   # south: mostly dry
        [1.5,  4.0, 15.0],   # center: moderate in NE direction
        [3.0, 18.0, 45.0],   # north: heavy storm cell at NE corner
    ]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            r = intensities[i][j]
            rows.append({
                "station_id": f"demo_{lat:.3f}_{lon:.3f}",
                "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "rainfall_intensity_mm_per_hr": r,
                "rainfall_accumulation_3h_mm": round(r * 3, 1),
                "data_source": "openmeteo",
                "quality_flag": "synthetic",
            })
    return pd.DataFrame(rows)


def synthetic_incidents(bbox: dict) -> pd.DataFrame:
    """A few waterlogging incidents near the storm cell (NE corner)."""
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]
    lat_mid = (bbox["lat_min"] + lat_max) / 2
    lon_mid = (bbox["lon_min"] + lon_max) / 2
    return pd.DataFrame([
        {"latitude": lat_max - 0.01, "longitude": lon_max - 0.02,
         "severity": "high", "incident_type": "waterlogging", "quality_flag": "unverified"},
        {"latitude": lat_max - 0.03, "longitude": lon_max - 0.05,
         "severity": "high", "incident_type": "road_flooding", "quality_flag": "unverified"},
        {"latitude": lat_mid + 0.02, "longitude": lon_mid + 0.03,
         "severity": "moderate", "incident_type": "waterlogging", "quality_flag": "unverified"},
    ])


def synthetic_assets(bbox: dict) -> pd.DataFrame:
    """Distributed drainage assets across the city."""
    lat_min, lat_max = bbox["lat_min"], bbox["lat_max"]
    lon_min, lon_max = bbox["lon_min"], bbox["lon_max"]
    lat_mid = (lat_min + lat_max) / 2
    lon_mid = (lon_min + lon_max) / 2
    return pd.DataFrame([
        {"latitude": lat_mid - 0.04, "longitude": lon_mid - 0.03, "asset_type": "drain"},
        {"latitude": lat_mid + 0.05, "longitude": lon_mid - 0.04, "asset_type": "drain"},
        {"latitude": lat_min + 0.03, "longitude": lon_min + 0.05, "asset_type": "pump_station"},
        {"latitude": lat_max - 0.05, "longitude": lon_min + 0.04, "asset_type": "drain"},
    ])
