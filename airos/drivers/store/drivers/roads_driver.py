"""AirOS built-in roads driver — OSM road network + osmnx."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class RoadsDriver(_InTreeDriver):
    domain = "roads"
    cadence_hours = 24 * 90       # quarterly
    produces_assessments = False

    signal_names = [
        "ROAD_LENGTH_M", "ROAD_DENSITY",
        "MAJOR_ROAD_RATIO", "INTERSECTION_COUNT", "DATA_CONFIDENCE",
    ]
    data_sources = ["OSM Overpass API", "osmnx graph"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_roads
        return _ingest_roads(city_id, bbox, force=force)
