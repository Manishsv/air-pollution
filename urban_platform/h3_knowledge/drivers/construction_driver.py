"""AirOS built-in construction activity driver — permit API + SAR change."""
from __future__ import annotations

from urban_platform.h3_knowledge.drivers._base import _InTreeDriver


class ConstructionDriver(_InTreeDriver):
    domain = "construction"
    cadence_hours = 6.0
    produces_assessments = True

    signal_names = [
        "ACTIVE_PERMIT_COUNT", "SURFACE_CHANGE",
        "BSI", "CONSTRUCTION_RISK_INDEX", "DATA_CONFIDENCE",
    ]
    data_sources = ["Municipal construction permit API", "Sentinel-2 SAR (GEE)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_construction
        return _ingest_construction(city_id, bbox, force=force)
