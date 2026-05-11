"""AirOS built-in waste / illegal dumping driver — Sentinel-2 + MODIS fire."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


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
        from airos.drivers.store.ingestor import _ingest_waste
        return _ingest_waste(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — satellite waste detection unavailable"
            )
        return result
