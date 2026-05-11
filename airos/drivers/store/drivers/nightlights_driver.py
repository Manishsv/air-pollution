"""AirOS built-in night lights driver — VIIRS NTL monthly composite context."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class NightLightsDriver(_InTreeDriver):
    domain = "nightlights"
    cadence_hours = 24 * 30       # monthly VIIRS composites
    produces_assessments = False  # structural context only

    signal_names = [
        "NTL_RADIANCE",
        "NTL_LIT_FRACTION",
        "ECONOMIC_ACTIVITY_INDEX",
        "DATA_CONFIDENCE",
        "ACTIVITY_CLASS",   # rule-based classifier runs at end of ingest
    ]
    data_sources = [
        "NASA Black Marble VNP46A2 — VIIRS DNB monthly composite 500 m (EARTHDATA_TOKEN required)",
        "EOG VIIRS Monthly Composite — no auth required (stub, falls through to synthetic)",
        "Synthetic fallback — literature-based radiance estimates for Indian cities",
    ]
    # EARTHDATA_TOKEN is optional: tier 1 (NASA) uses it; tiers 2 and 3 work without it.
    # Set EARTHDATA_TOKEN in .env for real VIIRS data from NASA Black Marble.
    _required_env_vars = []   # synthetic mode works without any key

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_nightlights
        return _ingest_nightlights(city_id, bbox, force=force)
