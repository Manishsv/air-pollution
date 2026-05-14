"""AirOS built-in POI driver — OSM points-of-interest by category."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class POIsDriver(_InTreeDriver):
    domain = "pois"
    cadence_hours = 24 * 90       # quarterly
    produces_assessments = False  # structural context

    signal_names = [
        "POI_INDUSTRIAL_COUNT", "POI_CONSTRUCTION_COUNT", "POI_FUEL_STATION_COUNT",
        "POI_KILN_COUNT", "POI_EATERY_COUNT", "POI_CREMATORIUM_COUNT",
        "POI_WASTE_FACILITY_COUNT", "POI_MARKET_COUNT", "POI_TRANSIT_TERMINAL_COUNT",
        "POI_HOSPITAL_COUNT", "POI_SCHOOL_COUNT", "DATA_CONFIDENCE",
    ]
    data_sources = ["OSM Overpass API (open-access)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_pois
        return _ingest_pois(city_id, bbox, force=force)
