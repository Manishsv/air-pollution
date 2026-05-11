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
        "LST_CELSIUS", "UHI_NORM", "GREEN_DEFICIT",
        "HEAT_RISK_SCORE", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 LST (GEE)", "OpenMeteo API"]
    _required_env_vars = []       # GEE credentials optional — falls back to OpenMeteo

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_heat
        return _ingest_heat(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            result.warnings.append(
                "GOOGLE_APPLICATION_CREDENTIALS not set — satellite LST unavailable, "
                "falling back to OpenMeteo air temperature estimates"
            )
        return result
