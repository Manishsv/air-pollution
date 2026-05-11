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
        "ACTIVE_PERMIT_COUNT", "SURFACE_CHANGE",
        "BSI", "CONSTRUCTION_RISK_INDEX", "DATA_CONFIDENCE",
    ]
    data_sources = ["Municipal construction permit API", "Sentinel-2 SAR (GEE)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_construction
        return _ingest_construction(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — Sentinel-2 SAR change detection "
                "unavailable; construction risk will rely on permit data only"
            )
        return result
