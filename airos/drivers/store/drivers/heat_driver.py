"""AirOS built-in urban heat driver — Sentinel-2 LST + OpenMeteo."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class HeatDriver(_InTreeDriver):
    domain = "heat"
    cadence_hours = 0.5           # 30 minutes
    produces_assessments = True

    signal_names = [
        "HEAT_RISK_SCORE", "LST", "UHI", "DATA_CONFIDENCE",
    ]
    data_sources = ["NASA Earthdata MODIS LST", "OpenMeteo API"]
    _required_env_vars = []       # EARTHDATA_TOKEN optional — falls back to OpenMeteo

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_heat
        return _ingest_heat(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("EARTHDATA_TOKEN"):
            result.warnings.append(
                "EARTHDATA_TOKEN not set — satellite LST unavailable, "
                "falling back to OpenMeteo air temperature estimates"
            )
        return result
