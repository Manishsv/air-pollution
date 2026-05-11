"""
Heat connector router.

Selects the data source based on environment variables:
  GEE_PROJECT set  →  GEE (MODIS LST + Sentinel-2 NDVI) — 1 km, daily
  fallback         →  OpenMeteo — air temperature proxy, free, no key
"""
from __future__ import annotations

import logging
import os

from .osm_green_cover import compute_green_cover

logger = logging.getLogger(__name__)


def fetch_temperature_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_days: int = 1,
    session=None,
    *,
    city_id: str | None = None,
) -> "pd.DataFrame":

    gee_project = os.environ.get("GEE_PROJECT", "").strip()

    if gee_project:
        from .gee_lst import fetch_lst_observations as _fetch
        logger.debug("Heat source: GEE MODIS LST (project=%s)", gee_project)
        df = _fetch(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_days=max(lookback_days, 8),   # MODIS needs wider window
            project=gee_project,
        )
        # Fall back to OpenMeteo if GEE returned nothing
        if df.empty:
            logger.warning("GEE LST returned empty — falling back to OpenMeteo")
            gee_project = ""
    else:
        logger.debug("Heat source: OpenMeteo (set GEE_PROJECT for real LST data)")

    if not gee_project:
        from .openmeteo import fetch_temperature_observations as _fetch_om
        df = _fetch_om(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_days=lookback_days, session=session,
        )

    if city_id and not df.empty:
        try:
            from airos.drivers.observation_store import ObservationStoreWriter
            ObservationStoreWriter().write(df, domain="heat", city_id=city_id)
        except Exception:
            pass

    return df


__all__ = ["fetch_temperature_observations", "compute_green_cover"]
