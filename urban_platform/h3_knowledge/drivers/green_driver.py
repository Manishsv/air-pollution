"""AirOS built-in green cover driver — Sentinel-2 NDVI."""
from __future__ import annotations

import os
from urban_platform.h3_knowledge.drivers._base import _InTreeDriver
from urban_platform.sdk.driver_types import ConformanceResult


class GreenDriver(_InTreeDriver):
    domain = "green"
    cadence_hours = 6.0
    produces_assessments = True

    signal_names = [
        "NDVI", "GREEN_COVER_FRACTION", "GCCI", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 NDVI (GEE)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_green
        return _ingest_green(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — satellite NDVI unavailable"
            )
        return result
