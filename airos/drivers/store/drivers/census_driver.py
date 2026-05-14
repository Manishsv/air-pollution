"""AirOS built-in census driver — GHSL_POP 100 m population raster."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class CensusDriver(_InTreeDriver):
    domain = "census"
    cadence_hours = 24 * 365      # yearly — GHSL_POP epoch updates are years apart
    produces_assessments = False  # structural context for exposure / vulnerability

    signal_names = [
        "POPULATION",
        "POPULATION_DENSITY_PER_KM2",
        "VULNERABLE_POPULATION_EST",   # under-5 + over-65 estimate (NFHS-5 fraction)
        "DATA_CONFIDENCE",
    ]
    data_sources = [
        "GHSL R2023A 100 m residential population grid (JRC, CC-BY 4.0)",
    ]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_census
        return _ingest_census(city_id, bbox, force=force)
