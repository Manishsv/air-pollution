"""AirOS built-in water quality driver — Sentinel-2 spectral indices."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class WaterDriver(_InTreeDriver):
    domain = "water"
    cadence_hours = 1.0
    produces_assessments = True

    signal_names = [
        "OPTICAL_WATER_CLARITY_INDEX", "DATA_CONFIDENCE",
    ]
    data_sources = ["Sentinel-2 (CDSE Sentinel Hub) — MNDWI / NDTI / CI / FAI"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_water
        return _ingest_water(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("CDSE_CLIENT_ID"):
            result.warnings.append(
                "CDSE_CLIENT_ID not set — satellite water quality unavailable"
            )
        return result
