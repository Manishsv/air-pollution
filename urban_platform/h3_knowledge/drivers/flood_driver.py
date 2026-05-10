"""AirOS built-in flood risk driver — Sentinel-2 SAR + DEM."""
from __future__ import annotations

import os
from urban_platform.h3_knowledge.drivers._base import _InTreeDriver
from urban_platform.sdk.driver_types import ConformanceResult


class FloodDriver(_InTreeDriver):
    domain = "flood"
    cadence_hours = 1.0
    produces_assessments = True

    signal_names = [
        "FLOOD_RISK_INDEX", "SAR_INUNDATION", "SLOPE_RISK",
        "SOIL_MOISTURE", "DRAIN_CAPACITY", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 SAR (GEE)", "SRTM DEM", "OSM drains domain"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_flood
        return _ingest_flood(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — SAR inundation unavailable"
            )
        return result
