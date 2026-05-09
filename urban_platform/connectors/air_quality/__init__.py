"""
Air quality connector router.

Selects the data source based on environment variables:
  CPCB_API_KEY set  →  CPCB (data.gov.in) — real Indian monitoring stations
  fallback          →  OpenMeteo AQ — free, no key, coarser grid
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def fetch_air_quality_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 24,
    session=None,
    *,
    city_id: str | None = None,
) -> "pd.DataFrame":
    import pandas as pd

    if os.environ.get("CPCB_API_KEY"):
        from .cpcb import fetch_air_quality_observations as _fetch
        logger.debug("Air quality source: CPCB")
    else:
        from .openmeteo_aq import fetch_air_quality_observations as _fetch
        logger.debug("Air quality source: OpenMeteo (set CPCB_API_KEY for real data)")

    df = _fetch(
        city_name, lat_min, lon_min, lat_max, lon_max,
        lookback_hours=lookback_hours,
        session=session,
    )

    if city_id and not df.empty:
        try:
            from urban_platform.observation_store import ObservationStoreWriter
            ObservationStoreWriter().write(df, domain="air", city_id=city_id)
        except Exception:
            pass

    return df


__all__ = ["fetch_air_quality_observations"]
