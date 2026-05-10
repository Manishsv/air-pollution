"""AirOS built-in waste / illegal dumping driver — Sentinel-2 + MODIS fire."""
from __future__ import annotations

from urban_platform.h3_knowledge.drivers._base import _InTreeDriver


class WasteDriver(_InTreeDriver):
    domain = "waste"
    cadence_hours = 1.0
    produces_assessments = True

    signal_names = [
        "WASTE_SITE_PROBABILITY", "BURN_FRP_MW",
        "WASTE_RISK_INDEX", "PERSISTENCE_DAYS", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 spectral (GEE)", "MODIS/VIIRS active fire"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_waste
        return _ingest_waste(city_id, bbox, force=force)
