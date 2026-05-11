"""Terrain DEM connector — elevation point samples for a city bbox.

Sources (tried in order, first success wins):
  1. Open-Elevation API  — free REST API, no key, backed by SRTM/Mapzen.
                           Batches up to 512 points per request.
  2. srtm.py package     — downloads and caches SRTM HGT tiles locally
                           (~30 MB per 1°×1° tile, stored in cache/srtm/).
                           Pure Python, no credentials required.
  3. Synthetic fallback  — flat terrain at bbox mean lat/lon elevation.
                           Returns DATA_CONFIDENCE=0.0 to block operational use.

Output: list of dicts matching the terrain_dem_feed.v1 provider contract:
    lat, lon, elevation_m, quality_flag, source_record_id, provenance

The ingestor (terrain_ingestor.py) aggregates these points to H3 cells
and derives SLOPE_DEG, ASPECT_DEG, RUGGEDNESS_INDEX, DATA_CONFIDENCE.
TERRAIN_CLASS is NOT computed here — it is derived by the agent layer.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Sampling grid density ────────────────────────────────────────────────────
# One sample every ~250 m gives ~10-12 points per H3 res-8 cell (~0.74 km²),
# enough to compute a stable cell mean without overwhelming public APIs.
_SAMPLE_SPACING_DEG = 0.0025   # ≈ 250 m at equatorial scale

# Batch size for Open-Elevation API (hard limit ~512 locations per POST)
_OPEN_ELEV_BATCH = 300
_OPEN_ELEV_URL   = "https://api.open-elevation.com/api/v1/lookup"
_REQUEST_TIMEOUT = 20   # seconds per batch request


def _grid_points(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    spacing: float = _SAMPLE_SPACING_DEG,
) -> list[tuple[float, float]]:
    """Generate a regular lat/lon grid covering the bbox."""
    pts: list[tuple[float, float]] = []
    lat = lat_min + spacing / 2
    while lat < lat_max:
        lon = lon_min + spacing / 2
        while lon < lon_max:
            pts.append((round(lat, 6), round(lon, 6)))
            lon += spacing
        lat += spacing
    return pts


def _provenance(source_id: str) -> dict[str, str]:
    return {
        "source_id":   source_id,
        "source_type": "dem_raster_sampled",
        "license":     (
            "Copernicus Data Space Ecosystem (free with attribution)"
            if "copernicus" in source_id
            else "NASA SRTM public domain"
        ),
        "collected_at": "2021-01-15T00:00:00Z",   # SRTM/Copernicus acquisition period
        "ingested_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── Source 1: Open-Elevation API ─────────────────────────────────────────────

def _fetch_open_elevation(
    points: list[tuple[float, float]],
) -> list[dict[str, Any]] | None:
    """
    POST batches of points to the Open-Elevation API.

    Returns a list of sample dicts on success, None on any error.
    The API uses SRTM data and is free with no key required.
    """
    try:
        import requests
    except ImportError:
        logger.debug("requests not available — skipping Open-Elevation")
        return None

    results: list[dict[str, Any]] = []
    prov = _provenance("open_elevation_srtm")

    for i in range(0, len(points), _OPEN_ELEV_BATCH):
        batch = points[i : i + _OPEN_ELEV_BATCH]
        payload = {"locations": [{"latitude": lat, "longitude": lon} for lat, lon in batch]}
        try:
            resp = requests.post(
                _OPEN_ELEV_URL,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Open-Elevation batch %d failed: %s", i // _OPEN_ELEV_BATCH, exc)
            return None   # give up and try next source

        for item in data.get("results", []):
            elev = item.get("elevation")
            if elev is None:
                flag = "void"
            elif elev < -500 or elev > 9000:
                flag = "suspected_artefact"
            else:
                flag = "ok"
            results.append({
                "lat":             item["latitude"],
                "lon":             item["longitude"],
                "elevation_m":     float(elev) if elev is not None else None,
                "quality_flag":    flag,
                "source_record_id": f"open_elev_{item['latitude']:.4f}_{item['longitude']:.4f}",
                "provenance":      prov,
            })

    logger.info("Open-Elevation: %d points fetched", len(results))
    return results if results else None


# ── Source 2: srtm.py package (local tile cache) ─────────────────────────────

def _srtm_cache_dir() -> str:
    """Return the local SRTM tile cache directory (cache/srtm/ under repo root)."""
    from pathlib import Path
    here = Path(__file__).resolve()
    # airos/drivers/connectors/terrain/srtm.py → parents[4] = repo root
    repo_root = here.parents[4]
    d = repo_root / "cache" / "srtm"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _fetch_srtm_package(
    points: list[tuple[float, float]],
) -> list[dict[str, Any]] | None:
    """
    Use the ``srtm`` Python package to look up elevation for each point.

    Downloads SRTM HGT tiles on first use (~25-30 MB per 1°×1° tile) into
    cache/srtm/. Subsequent calls are fully offline.
    """
    try:
        import srtm
    except ImportError:
        logger.debug("srtm package not installed — skipping (pip install srtm.py)")
        return None

    try:
        elevation_data = srtm.get_data(local_cache_dir=_srtm_cache_dir())
    except Exception as exc:
        logger.warning("srtm.get_data() failed: %s", exc)
        return None

    prov = _provenance("srtm_nasa_30m")
    results: list[dict[str, Any]] = []

    for lat, lon in points:
        try:
            elev = elevation_data.get_elevation(lat, lon)
        except Exception:
            elev = None

        if elev is None:
            flag = "void"
        elif elev < -500 or elev > 9000:
            flag = "suspected_artefact"
            elev = None
        else:
            flag = "ok"

        results.append({
            "lat":              lat,
            "lon":              lon,
            "elevation_m":      float(elev) if elev is not None else None,
            "quality_flag":     flag,
            "source_record_id": f"srtm_{lat:.4f}_{lon:.4f}",
            "provenance":       prov,
        })

    ok_count = sum(1 for r in results if r["quality_flag"] == "ok")
    logger.info("SRTM package: %d points, %d valid", len(results), ok_count)
    return results if results else None


# ── Source 3: Synthetic fallback ─────────────────────────────────────────────

def _synthetic_flat(
    points: list[tuple[float, float]],
    bbox: dict,
) -> list[dict[str, Any]]:
    """
    Return flat terrain at a rough estimate of the bbox's elevation.

    Uses a very rough latitude-based lookup for known Indian cities.
    DATA_CONFIDENCE will be set to 0.0 by the ingestor to block any
    operational use of these values.
    """
    # Very rough elevation look-up by bbox centre latitude/longitude
    # These are plateau/city-centre estimates only — not for production.
    _CITY_ELEV: list[tuple[float, float, float]] = [
        # (lat_centre, lon_centre, elevation_m)
        (12.97, 77.59,  920.0),   # Bangalore
        (17.38, 78.48,  536.0),   # Hyderabad
        (19.07, 72.87,   14.0),   # Mumbai
        (28.61, 77.21,  216.0),   # Delhi
        (13.08, 80.27,    6.0),   # Chennai
        (18.52, 73.85,  559.0),   # Pune
    ]
    clat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    clon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    best_elev = 100.0
    best_dist = float("inf")
    for (alat, alon, aelev) in _CITY_ELEV:
        d = math.hypot(clat - alat, clon - alon)
        if d < best_dist:
            best_dist, best_elev = d, aelev

    prov = _provenance("synthetic_fallback")
    prov["license"] = "synthetic — not for operational use"
    logger.warning(
        "Terrain: using synthetic flat fallback (elevation=%.0f m). "
        "Install srtm.py or ensure Open-Elevation is reachable.",
        best_elev,
    )
    return [
        {
            "lat":              lat,
            "lon":              lon,
            "elevation_m":      best_elev,
            "quality_flag":     "void_filled",   # treated as low-confidence
            "source_record_id": f"synthetic_{lat:.4f}_{lon:.4f}",
            "provenance":       prov,
        }
        for lat, lon in points
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_dem_samples(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    *,
    spacing_deg: float = _SAMPLE_SPACING_DEG,
    force_source: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch elevation point samples covering the bbox.

    Tries sources in order: Open-Elevation → srtm.py → synthetic.
    Returns a list of dicts matching the terrain_dem_feed.v1 provider
    contract (lat, lon, elevation_m, quality_flag, source_record_id,
    provenance).

    Parameters
    ----------
    lat_min, lon_min, lat_max, lon_max
        Bounding box in WGS84 decimal degrees.
    spacing_deg
        Grid spacing in degrees (~250 m at default). Reduce for denser
        sampling; increase for faster/cheaper fetches.
    force_source
        ``"open_elevation"``, ``"srtm"``, or ``"synthetic"`` to bypass
        the normal priority order (useful for testing).
    """
    bbox = dict(lat_min=lat_min, lon_min=lon_min, lat_max=lat_max, lon_max=lon_max)
    points = _grid_points(lat_min, lon_min, lat_max, lon_max, spacing=spacing_deg)
    if not points:
        logger.warning("fetch_dem_samples: empty grid for bbox %s", bbox)
        return []

    logger.info(
        "Terrain DEM: sampling %d points (spacing=%.4f°) for bbox %s",
        len(points), spacing_deg, bbox,
    )

    if force_source == "synthetic":
        return _synthetic_flat(points, bbox)
    if force_source == "srtm":
        return _fetch_srtm_package(points) or _synthetic_flat(points, bbox)
    if force_source == "open_elevation":
        return _fetch_open_elevation(points) or _synthetic_flat(points, bbox)

    # Normal priority: Open-Elevation → srtm.py → synthetic
    result = _fetch_open_elevation(points)
    if result is not None:
        return result

    result = _fetch_srtm_package(points)
    if result is not None:
        return result

    return _synthetic_flat(points, bbox)
