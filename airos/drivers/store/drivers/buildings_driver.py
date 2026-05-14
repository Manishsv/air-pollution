"""AirOS built-in buildings driver — OSM building footprints."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class BuildingsDriver(_InTreeDriver):
    domain = "buildings"
    cadence_hours = 24 * 90       # quarterly
    produces_assessments = False  # structural context

    signal_names = [
        "BUILDING_COUNT", "BUILDING_DENSITY",
        "AVG_FLOORS",                # legacy: mean over observed buildings (or 1.0 fallback)
        "AVG_FLOORS_OBSERVED",       # mean over buildings with explicit building:levels (nullable)
        "FLOORS_MISSING_RATIO",      # fraction of buildings lacking the explicit tag (transparency)
        "COMMERCIAL_RATIO", "DATA_CONFIDENCE",
        # GHSL satellite-derived built-mass signals (methodology §D.13)
        "BUILT_VOLUME_M3",           # sum of GHSL built-volume pixels per cell
        "BUILT_SURFACE_M2",          # sum of GHSL built-surface pixels per cell
        "AVG_BUILDING_HEIGHT_M",     # BUILT_VOLUME_M3 / BUILT_SURFACE_M2 (vertical mass proxy)
        "BUILT_INTENSITY",           # BUILT_SURFACE_M2 / cell_area (built-up fraction)
    ]
    data_sources = [
        "OSM Overpass API (open-access)",
        "GHSL R2023A 100 m built-volume / built-surface (JRC, CC-BY 4.0)",
    ]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_buildings
        return _ingest_buildings(city_id, bbox, force=force)
