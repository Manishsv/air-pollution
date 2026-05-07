"""
Flood connectors (specs-first).

This package provides provider-contract validated ingestion utilities for flood-related feeds.
No modeling or dashboard logic lives here.
"""

from .ingest_file import ingest_drainage_asset_feed_json, ingest_flood_incident_feed_json, ingest_rainfall_observation_feed_json
from .openmeteo_rainfall import fetch_rainfall_observations as _fetch_rainfall_raw


def fetch_rainfall_observations(
    city_name, lat_min, lon_min, lat_max, lon_max,
    lookback_hours=3, session=None, *, city_id=None,
):
    df = _fetch_rainfall_raw(city_name, lat_min, lon_min, lat_max, lon_max,
                             lookback_hours=lookback_hours, session=session)
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

