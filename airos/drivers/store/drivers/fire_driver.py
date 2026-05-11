"""AirOS built-in fire detection driver — MODIS / VIIRS active fire data."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class FireDriver(_InTreeDriver):
    domain = "fire"
    cadence_hours = 0.25          # 15 minutes
    produces_assessments = True

    signal_names = ["FRP_MW", "FIRE_SCORE", "FIRE_TYPE", "DATA_CONFIDENCE"]
    data_sources = ["NASA MODIS active fire (FIRMS)", "VIIRS 375m active fire"]
    _required_env_vars = []       # NASA FIRMS is open-access

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_fire
        return _ingest_fire(city_id, bbox, force=force)
