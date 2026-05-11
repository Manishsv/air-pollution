"""Shared Streamlit data cache for expensive API calls.

All panels import loaders from here so identical requests hit the same
@st.cache_data entry regardless of which tab triggered them first.
"""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


@st.cache_data(ttl=3600, show_spinner="Fetching FIRMS fire/waste hotspots…")
def load_firms(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
               day_range: int) -> pd.DataFrame:
    try:
        from airos.drivers.connectors.satellite.firms import fetch_firms_fires
        return fetch_firms_fires(lat_min, lon_min, lat_max, lon_max, day_range=day_range)
    except Exception as exc:
        logger.warning("load_firms failed (%s): %s", type(exc).__name__, exc)
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner="Loading air quality data…")
def load_live_aq(city_id: str, lat_min: float, lon_min: float,
                 lat_max: float, lon_max: float, lookback_hours: int) -> pd.DataFrame:
    try:
        from airos.os.sdk import store as _sdk_store
        cached = _sdk_store.get_recent_observations("air", city_id, max_age_hours=1)
        if not cached.empty:
            from airos.drivers.observation_store import to_wide
            return to_wide(cached)
    except Exception:
        pass
    from airos.drivers.connectors.air_quality import fetch_air_quality_observations
    return fetch_air_quality_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_hours=lookback_hours,
        city_id=city_id,
    )


@st.cache_data(ttl=3600, show_spinner="Fetching MODIS AOD…")
def load_aod(h3_ids: tuple, lat_min: float, lon_min: float,
             lat_max: float, lon_max: float) -> dict:
    try:
        from airos.drivers.connectors.satellite.gee_aod import fetch_aod_for_cells
        return fetch_aod_for_cells(list(h3_ids), lat_min, lon_min, lat_max, lon_max)
    except Exception as exc:
        logger.warning("load_aod failed (%s): %s", type(exc).__name__, exc)
        return {}


@st.cache_data(ttl=7200, show_spinner="Fetching Sentinel-2 NDVI…")
def load_ndvi(h3_ids: tuple, lat_min: float, lon_min: float,
              lat_max: float, lon_max: float) -> dict:
    try:
        from airos.drivers.connectors.satellite.gee_waste import fetch_ndvi_for_cells
        return fetch_ndvi_for_cells(list(h3_ids), lat_min, lon_min, lat_max, lon_max)
    except Exception as exc:
        logger.warning("load_ndvi failed (%s): %s", type(exc).__name__, exc)
        return {}


@st.cache_data(ttl=7200, show_spinner="Fetching Sentinel-5P CH4…")
def load_ch4(h3_ids: tuple, lat_min: float, lon_min: float,
             lat_max: float, lon_max: float) -> dict:
    try:
        from airos.drivers.connectors.satellite.gee_waste import fetch_ch4_for_cells
        return fetch_ch4_for_cells(list(h3_ids), lat_min, lon_min, lat_max, lon_max)
    except Exception as exc:
        logger.warning("load_ch4 failed (%s): %s", type(exc).__name__, exc)
        return {}


@st.cache_data(ttl=300, show_spinner="Loading temperature data…")
def load_live_temperature(city_id: str, lat_min: float, lon_min: float,
                          lat_max: float, lon_max: float, lookback_hours: int) -> pd.DataFrame:
    try:
        from airos.os.sdk import store as _sdk_store
        cached = _sdk_store.get_recent_observations("heat", city_id, max_age_hours=1)
        if not cached.empty:
            from airos.drivers.observation_store import to_wide
            return to_wide(cached)
    except Exception:
        pass
    from airos.drivers.connectors.heat import fetch_temperature_observations
    return fetch_temperature_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_hours=lookback_hours,
        city_id=city_id,
    )


@st.cache_data(ttl=300, show_spinner="Loading rainfall data…")
def load_live_rainfall(city_id: str, lat_min: float, lon_min: float,
                       lat_max: float, lon_max: float, lookback_hours: int) -> pd.DataFrame:
    try:
        from airos.os.sdk import store as _sdk_store
        cached = _sdk_store.get_recent_observations("flood", city_id, max_age_hours=1)
        if not cached.empty:
            from airos.drivers.observation_store import to_wide
            return to_wide(cached)
    except Exception:
        pass
    from airos.drivers.connectors.flood import fetch_rainfall_observations
    return fetch_rainfall_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_hours=lookback_hours,
        city_id=city_id,
    )


@st.cache_data(ttl=86400)
def h3_grid_for_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                     resolution: int) -> tuple:
    """Sorted tuple of H3 cells covering bbox — cached 24h (grid is static)."""
    try:
        import h3
        region = h3.geo_to_cells(
            {
                "type": "Polygon",
                "coordinates": [[
                    [lon_min, lat_min], [lon_max, lat_min],
                    [lon_max, lat_max], [lon_min, lat_max],
                    [lon_min, lat_min],
                ]],
            },
            resolution,
        )
        return tuple(sorted(region))
    except Exception as exc:
        logger.warning("h3_grid_for_bbox failed (%s): %s", type(exc).__name__, exc)
        return ()


@st.cache_data(ttl=7200, show_spinner="Fetching Sentinel-2 water quality…")
def load_water_quality(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                       h3_resolution: int, lookback_days: int = 10) -> dict:
    """Cache key is 6 scalars — avoids hashing thousands of H3 strings every render."""
    h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)
    if not h3_ids:
        return {}
    try:
        from airos.drivers.connectors.satellite.gee_water import fetch_water_quality
        return fetch_water_quality(list(h3_ids), lat_min, lon_min, lat_max, lon_max,
                                   lookback_days=lookback_days)
    except Exception as exc:
        logger.warning("load_water_quality failed (%s): %s", type(exc).__name__, exc)
        return {}


@st.cache_data(ttl=7200, show_spinner="Fetching Sentinel-2 green cover change…")
def load_green_cover(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                     h3_resolution: int, recent_days: int = 30,
                     baseline_days: int = 365) -> dict:
    """Cache key is 7 scalars; h3_ids computed inside."""
    h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)
    if not h3_ids:
        return {}
    try:
        from airos.drivers.connectors.satellite.gee_green import fetch_green_cover
        return fetch_green_cover(list(h3_ids), lat_min, lon_min, lat_max, lon_max,
                                 recent_days=recent_days, baseline_days=baseline_days)
    except Exception as exc:
        logger.warning("load_green_cover failed (%s): %s", type(exc).__name__, exc)
        return {}


@st.cache_data(ttl=7200, show_spinner="Fetching Sentinel-2 BSI + S5P NO₂ (construction)…")
def load_construction_signals(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                              h3_resolution: int, lookback_days: int = 20) -> dict:
    """Cache key is 6 scalars — avoids hashing thousands of H3 strings every render."""
    h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)
    if not h3_ids:
        return {}
    try:
        from airos.drivers.connectors.satellite.gee_construction import fetch_construction_signals
        return fetch_construction_signals(
            list(h3_ids), lat_min, lon_min, lat_max, lon_max,
            lookback_days=lookback_days,
        )
    except Exception as exc:
        logger.warning("load_construction_signals failed (%s): %s", type(exc).__name__, exc)
        return {}
