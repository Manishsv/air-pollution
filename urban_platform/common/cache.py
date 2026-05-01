from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from src import cache as _legacy_cache


# Thin compatibility wrappers; migrated functionality will live here.
cache_exists = _legacy_cache.cache_exists
is_cache_valid = _legacy_cache.is_cache_valid
stable_slug = _legacy_cache.stable_slug
polygon_hash_wgs84 = _legacy_cache.polygon_hash_wgs84
cache_path = _legacy_cache.cache_path
save_json = _legacy_cache.save_json


def load_geodata(path: str | Path) -> gpd.GeoDataFrame:
    return _legacy_cache.load_cached_geodata(path)


def save_geodata(gdf: gpd.GeoDataFrame, path: str | Path) -> None:
    _legacy_cache.save_cached_geodata(gdf, path)


def load_dataframe(path: str | Path) -> pd.DataFrame:
    return _legacy_cache.load_cached_dataframe(path)


def save_dataframe(df: pd.DataFrame, path: str | Path) -> None:
    _legacy_cache.save_cached_dataframe(df, path)


def with_source_metadata(df: pd.DataFrame, *, source: str, retrieval_type: str, details: Optional[dict] = None) -> pd.DataFrame:
    """
    Attach raw source metadata without mutating persisted schemas.
    """
    df = df.copy()
    meta = {"source": source, "retrieval_type": retrieval_type, "details": details or {}}
    try:
        df.attrs["source_metadata"] = meta
    except Exception:
        # attrs is best-effort; never break pipelines on it.
        pass
    return df

