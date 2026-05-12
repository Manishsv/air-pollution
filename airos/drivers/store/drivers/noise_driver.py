"""AirOS built-in noise driver — noise sensor API."""
from __future__ import annotations

import os
from airos.drivers.store.drivers._base import _InTreeDriver
from airos.os.sdk.driver_types import ConformanceResult


class NoiseDriver(_InTreeDriver):
    domain = "noise"
    cadence_hours = 6.0
    produces_assessments = True

    signal_names = [
        "NOISE_RISK_INDEX", "DATA_CONFIDENCE",
    ]
    data_sources = ["Noise sensor API (NOISE_API_URL)"]
    _required_env_vars = []     # NOISE_API_URL falls back to simulated data

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_noise
        return _ingest_noise(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        if not os.getenv("NOISE_API_URL"):
            result.warnings.append(
                "NOISE_API_URL not set — noise domain will use simulated data"
            )
        return result
