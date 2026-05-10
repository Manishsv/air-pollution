"""AirOS built-in buildings driver — OSM building footprints."""
from __future__ import annotations

from urban_platform.h3_knowledge.drivers._base import _InTreeDriver


class BuildingsDriver(_InTreeDriver):
    domain = "buildings"
    cadence_hours = 24 * 90       # quarterly
    produces_assessments = False  # structural context

    signal_names = [
        "BUILDING_COUNT", "BUILDING_DENSITY",
        "AVG_FLOORS", "COMMERCIAL_RATIO", "DATA_CONFIDENCE",
    ]
    data_sources = ["OSM Overpass API (open-access)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_buildings
        return _ingest_buildings(city_id, bbox, force=force)
