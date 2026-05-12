"""AirOS built-in construction activity driver — permit API + SAR change."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class ConstructionDriver(_InTreeDriver):
    domain = "construction"
    cadence_hours = 6.0
    produces_assessments = True

    signal_names = [
        "CONSTRUCTION_RISK_INDEX", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 BSI + Sentinel-5P NO2 (CDSE Sentinel Hub)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_construction
        return _ingest_construction(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("CDSE_CLIENT_ID"):
            result.warnings.append(
                "CDSE_CLIENT_ID not set — construction risk signals unavailable"
            )
        return result
