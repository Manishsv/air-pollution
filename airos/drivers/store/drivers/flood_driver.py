"""AirOS built-in flood risk driver — Sentinel-2 SAR + DEM."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class FloodDriver(_InTreeDriver):
    domain = "flood"
    cadence_hours = 1.0
    produces_assessments = True

    signal_names = [
        "FLOOD_RISK_INDEX", "SAR_INUNDATION", "SLOPE_RISK",
        "SOIL_MOISTURE", "DATA_CONFIDENCE",
    ]
    # DRAIN_CAPACITY removed: it belongs to the drains domain driver.
    # Cross-domain joins (flood + drains) happen at App reasoning time, not in the Driver.
    # See spec/drivers/DOMAIN_CATALOGUE.md §Flood and spec/drivers/DRIVER_INTERFACE.md §Isolation.
    data_sources = ["Sentinel-2 SAR (GEE)", "SRTM DEM"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_flood
        return _ingest_flood(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — SAR inundation unavailable"
            )
        return result
