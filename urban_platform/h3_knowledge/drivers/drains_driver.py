"""AirOS built-in drains driver — OSM waterways."""
from __future__ import annotations

from urban_platform.h3_knowledge.drivers._base import _InTreeDriver


class DrainsDriver(_InTreeDriver):
    domain = "drains"
    cadence_hours = 24 * 90       # quarterly
    produces_assessments = False

    signal_names = [
        "DRAIN_LENGTH_M", "WATERWAY_COUNT",
        "OPEN_DRAIN_RATIO", "FLOOD_DRAIN_CAPACITY", "DATA_CONFIDENCE",
    ]
    data_sources = ["OSM Overpass API waterways"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_drains
        return _ingest_drains(city_id, bbox, force=force)
