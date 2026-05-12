"""AirOS built-in flood risk driver — OpenMeteo rainfall + Open-Elevation terrain."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class FloodDriver(_InTreeDriver):
    domain = "flood"
    cadence_hours = 1.0
    produces_assessments = True

    signal_names = [
        "FLOOD_RISK_SCORE", "RAINFALL", "DATA_CONFIDENCE",
    ]
    data_sources = [
        "OpenMeteo API (precipitation, free, no key)",
        "Open-Elevation API (SRTM terrain, free, no key)",
    ]
    _required_env_vars = []   # EARTHDATA_TOKEN optional — upgrades to GPM IMERG

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_flood
        return _ingest_flood(city_id, bbox, force=force)
