"""
Heat connector router.

Selects the data source based on environment variables:
  EARTHDATA_TOKEN set  →  NASA Earthdata MODIS MOD11A1 LST (1 km, daily)
  fallback             →  OpenMeteo — air temperature proxy, free, no key
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

    earthdata_token = os.environ.get("EARTHDATA_TOKEN", "").strip()

    if earthdata_token:
        from .earthdata_lst import fetch_lst_observations as _fetch
        logger.debug("Heat source: NASA Earthdata MODIS LST")
        df = _fetch(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_days=max(lookback_days, 8),   # MODIS needs wider window
        )
        if df.empty:
            logger.warning("MODIS LST returned empty — falling back to OpenMeteo")
            earthdata_token = ""
    else:
        logger.debug("Heat source: OpenMeteo (set EARTHDATA_TOKEN for real LST data)")

    if not earthdata_token:
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
