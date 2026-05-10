"""AirOS built-in fire detection driver — MODIS / VIIRS active fire data."""
from __future__ import annotations

from urban_platform.h3_knowledge.drivers._base import _InTreeDriver
from urban_platform.sdk.driver_types import ConformanceResult


class FireDriver(_InTreeDriver):
    domain = "fire"
    cadence_hours = 0.25          # 15 minutes
    produces_assessments = True

    signal_names = ["FRP_MW", "FIRE_SCORE", "FIRE_TYPE", "DATA_CONFIDENCE"]
    data_sources = ["NASA MODIS active fire (FIRMS)", "VIIRS 375m active fire"]
    _required_env_vars = []       # NASA FIRMS is open-access

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_fire
        return _ingest_fire(city_id, bbox, force=force)
