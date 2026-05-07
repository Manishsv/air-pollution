"""
Flood connector router.

Selects the data source based on environment variables:
  GEE_PROJECT set  →  GEE (GPM IMERG + SRTM + JRC) — near-real-time rain + terrain
  fallback         →  OpenMeteo rainfall — free, no key, coarser resolution

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

    gee_project = os.environ.get("GEE_PROJECT", "").strip()

    if gee_project:
        from .gee_precipitation import fetch_rainfall_observations as _fetch
        logger.debug("Flood source: GEE GPM IMERG (project=%s)", gee_project)
        df = _fetch(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_hours=lookback_hours,
            project=gee_project,
        )
        if df.empty:
            logger.warning("GEE GPM returned empty — falling back to OpenMeteo")
            gee_project = ""
    else:
        logger.debug("Flood source: OpenMeteo (set GEE_PROJECT for real precipitation data)")

    if not gee_project:
        from .openmeteo_rainfall import fetch_rainfall_observations as _fetch_om
        df = _fetch_om(
            city_name, lat_min, lon_min, lat_max, lon_max,
            lookback_hours=lookback_hours, session=session,
        )

    if city_id and not df.empty:
        try:
            from urban_platform.observation_store import ObservationStoreWriter
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
