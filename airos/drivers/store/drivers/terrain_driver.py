"""AirOS built-in terrain driver — SRTM / Copernicus DEM elevation context."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class TerrainDriver(_InTreeDriver):
    domain = "terrain"
    cadence_hours = 24 * 90       # quarterly — terrain is effectively static
    produces_assessments = False  # structural context only

    signal_names = [
        "ELEVATION_M",
        "SLOPE_DEG",
        "ASPECT_DEG",
        "RUGGEDNESS_INDEX",
        "DATA_CONFIDENCE",
        # TERRAIN_CLASS is intentionally absent here — it is derived by the
        # H3 Expert Agent after ingest, not written by the ingestor.
    ]
    data_sources = [
        "Open-Elevation API (SRTM-backed, free, no key)",
        "SRTM 30m DEM — NASA public domain (srtm.py local tile cache)",
        "Copernicus DEM GLO-30 — ESA free (future direct tile support)",
    ]
    _required_env_vars = []   # no API key required

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_terrain
        return _ingest_terrain(city_id, bbox, force=force)
