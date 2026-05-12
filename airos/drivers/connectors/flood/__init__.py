"""
Flood connector router.

Selects the data source based on environment variables:
  EARTHDATA_TOKEN set  →  NASA Earthdata GPM IMERG (0.1°, half-hourly) + Open-Elevation
  fallback             →  OpenMeteo rainfall — free, no key, coarser resolution

File-based ingestion utilities (ingest_*) are always available.
"""
from __future__ import annotations

import logging
import os

from .ingest_file import (
    ingest_drainage_asset_feed_json,
    ingest_flood_incident_feed_json,
    ingest_rainfall_observation_feed_json,
)

logger = logging.getLogger(__name__)


def fetch_rainfall_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 3,
    session=None,
    *,
    city_id: str | None = None,
) -> "pd.DataFrame":

    earthdata_token = os.environ.get("EARTHDATA_TOKEN", "").strip()

    if earthdata_token:
        from .earthdata_flood import fetch_rainfall_observations as _fetch
        logger.debug("Flood source: NASA Earthdata GPM IMERG")
        df = _fetch(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_hours=lookback_hours,
        )
        if df.empty:
            logger.warning("GPM IMERG returned empty — falling back to OpenMeteo")
            earthdata_token = ""
    else:
        logger.debug("Flood source: OpenMeteo (set EARTHDATA_TOKEN for real precipitation data)")

    if not earthdata_token:
        from .openmeteo_rainfall import fetch_rainfall_observations as _fetch_om
        df = _fetch_om(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_hours=lookback_hours, session=session,
        )

    if city_id and not df.empty:
        try:
            from airos.drivers.observation_store import ObservationStoreWriter
            ObservationStoreWriter().write(df, domain="flood", city_id=city_id)
        except Exception:
            pass

    return df


__all__ = [
    "ingest_rainfall_observation_feed_json",
    "ingest_flood_incident_feed_json",
    "ingest_drainage_asset_feed_json",
    "fetch_rainfall_observations",
]
