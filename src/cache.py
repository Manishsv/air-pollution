from __future__ import annotations

"""
Legacy import path for cache helpers.

Canonical implementation lives in `urban_platform.common.cache`.
"""

from urban_platform.common.cache import (  # noqa: F401
    cache_exists,
    cache_path,
    is_cache_valid,
    load_cached_dataframe,
    load_cached_geodata,
    polygon_hash_wgs84,
    save_cached_dataframe,
    save_cached_geodata,
    save_json,
    stable_slug,
)
