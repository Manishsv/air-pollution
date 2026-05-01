from __future__ import annotations

from typing import Any

import pandas as pd

from src.weather_data import fetch_open_meteo_hourly as _legacy_fetch
from urban_platform.common.cache import with_source_metadata
from urban_platform.standards.converters import weather_hourly_to_observations
from urban_platform.standards.validators import validate_observations


def fetch_open_meteo_raw(config: Any) -> pd.DataFrame:
    """
    Fetch hourly weather using Open-Meteo archive API.

    Returns a DataFrame compatible with legacy pipeline expectations.
    """
    cfg = getattr(config, "config", config)
    boundary = getattr(config, "_boundary_bundle_for_connectors", None)
    if boundary is None:
        # Best effort: compute centroid from bbox if boundary isn't available.
        bbox = getattr(cfg, "bbox", None)
        if bbox is None:
            df = pd.DataFrame()
            return with_source_metadata(df, source="open_meteo", retrieval_type="unavailable", details={"reason": "No bbox/boundary"})
        centroid_lat = (float(bbox.north) + float(bbox.south)) / 2.0
        centroid_lon = (float(bbox.east) + float(bbox.west)) / 2.0
    else:
        centroid_lat = float(boundary.boundary_wgs84.geometry.iloc[0].centroid.y)
        centroid_lon = float(boundary.boundary_wgs84.geometry.iloc[0].centroid.x)

    df = _legacy_fetch(latitude=centroid_lat, longitude=centroid_lon, lookback_days=int(getattr(cfg, "lookback_days")))
    return with_source_metadata(
        df,
        source="open_meteo",
        retrieval_type="point",
        details={"latitude": centroid_lat, "longitude": centroid_lon, "lookback_days": int(getattr(cfg, "lookback_days"))},
    )


def fetch_open_meteo_observations(config: Any, grid_gdf=None) -> pd.DataFrame:
    """
    Schema-native entrypoint.

    - calls `fetch_open_meteo_raw`
    - converts to canonical Observation records
    - validates and returns observations
    """
    _ = grid_gdf  # reserved for future spatial broadcast; unused for now
    raw = fetch_open_meteo_raw(config)
    obs = weather_hourly_to_observations(raw)
    validate_observations(obs)
    return obs


# Backward-compatible alias during migration.
def fetch_open_meteo(config: Any) -> pd.DataFrame:
    return fetch_open_meteo_raw(config)

