"""
Flood connectors (specs-first).

This package provides provider-contract validated ingestion utilities for flood-related feeds.
No modeling or dashboard logic lives here.
"""

from .ingest_file import ingest_drainage_asset_feed_json, ingest_flood_incident_feed_json, ingest_rainfall_observation_feed_json

__all__ = [
    "ingest_rainfall_observation_feed_json",
    "ingest_flood_incident_feed_json",
    "ingest_drainage_asset_feed_json",
]

