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
        "UPWIND_PM25_LOAD",         # k≤2 (~1.5 km) — neighbourhood-scale advection
        "UPWIND_PM25_LOAD_K10",     # k≤10 (~7.5 km) — metro-scale advection
        "UPWIND_PM25_LOAD_REGIONAL",# bearing-based bbox aggregate (~100-300 km,
                                   # scales with wind speed) — airshed-scale
                                   # transport. Produced by the airshed
                                   # compositor (Phase 3), not by air ingest.
        "UPWIND_PM10_LOAD",       # same neighbourhood aggregation applied to PM10
        "VENTILATION_INDEX",      # wind speed dampened by topographic enclosure
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
