from __future__ import annotations

from typing import Any

import pandas as pd

from src import aq_data as _legacy_aq
from urban_platform.common.cache import with_source_metadata
from urban_platform.standards.converters import stations_pm25_to_observations
from urban_platform.standards.validators import validate_observations


def fetch_openaq_raw(config: Any) -> pd.DataFrame:
    """
    Fetch raw station-hourly PM2.5 from OpenAQ (best-effort).

    Returns a DataFrame compatible with legacy pipeline expectations:
      station_id, station_name, latitude, longitude, timestamp, pm25, data_source

    Also attaches best-effort raw source metadata in `df.attrs["source_metadata"]`.
    """
    cfg = getattr(config, "config", config)
    lookback_days = int(getattr(cfg, "lookback_days"))
    city_name = str(getattr(cfg, "city_name"))

    df = pd.DataFrame()
    bbox = getattr(cfg, "bbox", None)
    if bbox is not None:
        west, south, east, north = float(bbox.west), float(bbox.south), float(bbox.east), float(bbox.north)
        df = _legacy_aq.fetch_openaq_pm25_v3(
            bbox_west_south_east_north=(west, south, east, north),
            lookback_days=lookback_days,
            cache_dir=getattr(cfg, "data_processed_dir") / "cache",
            cache_ttl_days=int(getattr(getattr(cfg, "cache"), "ttl_days")),
            force_refresh=bool(getattr(getattr(cfg, "cache"), "force_refresh")),
        )
        if not df.empty:
            return with_source_metadata(
                df,
                source="openaq_v3",
                retrieval_type="bbox",
                details={"bbox_west_south_east_north": (west, south, east, north), "lookback_days": lookback_days},
            )

    df = _legacy_aq.fetch_openaq_pm25(city_name, lookback_days)
    if not df.empty:
        return with_source_metadata(
            df,
            source="openaq_v2",
            retrieval_type="city_name",
            details={"city_name": city_name, "lookback_days": lookback_days},
        )

    return with_source_metadata(
        df,
        source="openaq",
        retrieval_type="unavailable",
        details={"city_name": city_name, "lookback_days": lookback_days},
    )


def fetch_openaq_observations(config: Any, grid_gdf=None) -> pd.DataFrame:
    """
    Schema-native entrypoint.

    - calls `fetch_openaq_raw`
    - converts to canonical Observation records
    - validates and returns observations
    """
    _ = grid_gdf  # reserved for future spatial registration; unused for now
    raw = fetch_openaq_raw(config)
    obs = stations_pm25_to_observations(raw)
    validate_observations(obs)
    return obs


# Backward-compatible alias during migration.
def fetch_openaq(config: Any) -> pd.DataFrame:
    return fetch_openaq_raw(config)

