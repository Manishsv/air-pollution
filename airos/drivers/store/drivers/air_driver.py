"""AirOS built-in air quality driver — AQICN / CPCB sensor network."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class AirDriver(_InTreeDriver):
    domain = "air"
    cadence_hours = 0.25          # 15 minutes
    produces_assessments = True

    signal_names = [
        "PM25", "PM10", "NO2", "SO2", "PM25_PM10_RATIO",
        "AQI", "DATA_CONFIDENCE", "NEAREST_OBS_KM",
        # Wind-aware airborne aggregation (methodology §D.1)
        "UPWIND_PM25_LOAD",      # sum of upwind k≤2 cells' PM25, distance- + angle-weighted
        "UPWIND_PM10_LOAD",      # same aggregation applied to PM10 (used when CPCB has no PM2.5)
        "VENTILATION_INDEX",     # wind speed dampened by topographic enclosure
    ]
    data_sources = ["AQICN API", "CPCB sensor network"]
    _required_env_vars = []       # AQICN_API_KEY is optional (degrades to mock)

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_air
        return _ingest_air(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("AQICN_API_KEY"):
            result.warnings.append(
                "AQICN_API_KEY not set — air quality data will use mock/offline mode"
            )
        return result
