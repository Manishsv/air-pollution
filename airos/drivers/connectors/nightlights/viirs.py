"""VIIRS Night-Time Light (NTL) connector — monthly composite samples for a city bbox.

Sources (tried in order, first success wins):
  1. NASA Black Marble VNP46A2 via HTTPS — requires EARTHDATA_TOKEN env var
     (free NASA Earthdata account at urs.earthdata.nasa.gov).
     URL base: https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/
     Complex HDF5 parsing — implemented as stub that logs a helpful message
     and falls through to tier 2.
  2. EOG VIIRS monthly composite via HTTP — no auth required.
     URL: https://eogdata.mines.edu/nighttime_light/monthly_notile/v10/{year}/{month}/
     Complex GeoTIFF — implemented as stub that falls through to tier 3.
  3. Synthetic fallback — literature-based radiance estimates for Indian cities
     with spatial variation.  Always works; no network or credentials needed.
     Returns quality_flag="void_filled" and embeds "synthetic_fallback" in
     source_record_id so the ingestor sets DATA_CONFIDENCE=0.0.

Output: list of dicts matching the nightlights_ntl_feed.v1 provider contract:
    lat, lon, radiance_nw, lit_fraction, quality_flag,
    source_record_id, provenance

The ingestor (nightlights_ingestor.py) aggregates these points to H3 cells
and derives ECONOMIC_ACTIVITY_INDEX, DATA_CONFIDENCE, and ACTIVITY_CLASS.
"""
from __future__ import annotations

import logging
import math
import os
import random
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Sampling grid density ────────────────────────────────────────────────────
# VIIRS DNB pixel is ~500 m — use ~0.005° (~500 m) spacing to match.
# This gives roughly 2-4 samples per H3 res-8 cell (~0.74 km²), which is
# appropriate for a 500 m resolution source.
_SAMPLE_SPACING_DEG = 0.005   # ≈ 500 m at equatorial scale

# NTL saturation value used in ECONOMIC_ACTIVITY_INDEX
_SATURATION_VALUE = 60.0   # nW/cm²/sr

# City-centre radiance estimates (nW/cm²/sr) from published VIIRS-India studies
_CITY_RADIANCE: list[tuple[float, float, float]] = [
    # (lat_centre, lon_centre, radiance_nw)
    (28.61, 77.21, 28.0),   # Delhi
    (19.07, 72.87, 22.0),   # Mumbai
    (12.97, 77.59, 18.0),   # Bangalore
    (17.38, 78.48, 14.0),   # Hyderabad
    (13.08, 80.27, 11.0),   # Chennai
    (18.52, 73.85,  9.0),   # Pune
]
_DEFAULT_RADIANCE = 12.0   # nW/cm²/sr for unknown cities

# Gaussian noise sigma for synthetic variation
_NOISE_SIGMA = 5.0


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


def _provenance(source_id: str, collected_at: str | None = None) -> dict[str, str]:
    return {
        "source_id":    source_id,
        "source_type":  "viirs_hdf5" if "nasa" in source_id else (
            "viirs_geotiff" if "eog" in source_id else "synthetic"
        ),
        "license": (
            "NASA Earthdata — open access with attribution"
            if "nasa" in source_id
            else (
                "EOG VIIRS — academic/research use"
                if "eog" in source_id
                else "synthetic — not for operational use"
            )
        ),
        "collected_at": collected_at or "2025-12-01T00:00:00Z",
        "ingested_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── Source 1: NASA Black Marble VNP46A2 ──────────────────────────────────────

def _fetch_black_marble(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> list[dict[str, Any]] | None:
    """
    Stub for NASA Black Marble VNP46A2 (VIIRS DNB monthly composite, 500 m).

    Requires EARTHDATA_TOKEN environment variable (free NASA account at
    urs.earthdata.nasa.gov).  The full implementation would:
      1. Resolve the MODIS tile grid (h/v) from the bbox.
      2. Download HDF5 tile(s) from LAADS DAAC:
         https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/
         Archive/5000/VNP46A2/YYYY/DDD/VNP46A2.A<YYYYDDD>.h<HH>v<VV>.001.h5
      3. Extract 'DNB_BRDF-Corrected_NTL' and 'Mandatory_Quality_Flag' datasets.
      4. Reproject from MODIS sinusoidal to WGS84 and sample to the bbox grid.

    Currently implemented as a stub that logs a setup guide and falls through.
    """
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        logger.info(
            "Night Lights (NASA Black Marble): EARTHDATA_TOKEN not set. "
            "Register at https://urs.earthdata.nasa.gov/ (free) to enable real VIIRS data. "
            "Falling through to EOG composite tier."
        )
        return None

    logger.info(
        "Night Lights (NASA Black Marble): EARTHDATA_TOKEN found but HDF5 tile "
        "download is not yet implemented in this tier. "
        "Falling through to EOG composite tier."
    )
    return None


# ── Source 2: EOG VIIRS monthly composite ───────────────────────────────────

def _fetch_eog_composite(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> list[dict[str, Any]] | None:
    """
    Stub for EOG VIIRS monthly composite (no auth required).

    The full implementation would:
      1. Determine year/month for most recent available composite.
      2. Download GeoTIFF from:
         https://eogdata.mines.edu/nighttime_light/monthly_notile/v10/{year}/{month}/
      3. Clip to bbox and resample to grid points.

    Currently implemented as a stub that falls through to synthetic.
    """
    logger.info(
        "Night Lights (EOG composite): GeoTIFF download not yet implemented. "
        "Falling through to synthetic fallback. "
        "Data URL: https://eogdata.mines.edu/nighttime_light/monthly_notile/v10/"
    )
    return None


# ── Source 3: Synthetic fallback ─────────────────────────────────────────────

def _synthetic_ntl(
    points: list[tuple[float, float]],
    bbox: dict,
) -> list[dict[str, Any]]:
    """
    Generate synthetic NTL samples based on literature estimates for Indian cities.

    City-centre radiance is looked up from _CITY_RADIANCE; spatial variation is
    added using:
      - Distance-from-centre decay: cells near city centre get ~1.3x, edge ~0.7x.
      - Gaussian noise (sigma=5 nW, clipped to 0).

    Returns quality_flag="void_filled" and "synthetic_fallback" in source_record_id
    so the ingestor can set DATA_CONFIDENCE=0.0.
    """
    clat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    clon = (bbox["lon_min"] + bbox["lon_max"]) / 2

    # Find nearest city-centre radiance estimate
    base_radiance = _DEFAULT_RADIANCE
    best_dist = float("inf")
    for (alat, alon, arad) in _CITY_RADIANCE:
        d = math.hypot(clat - alat, clon - alon)
        if d < best_dist:
            best_dist, base_radiance = d, arad

    # Bbox diagonal half-length (in degrees) for distance normalisation
    half_diag = math.hypot(
        (bbox["lat_max"] - bbox["lat_min"]) / 2,
        (bbox["lon_max"] - bbox["lon_min"]) / 2,
    )
    if half_diag < 1e-6:
        half_diag = 1.0

    prov = _provenance("synthetic_fallback")

    logger.warning(
        "Night Lights: using synthetic fallback (base_radiance=%.1f nW). "
        "Set EARTHDATA_TOKEN for real NASA Black Marble VIIRS data.",
        base_radiance,
    )

    rng = random.Random(int(clat * 10000) ^ int(clon * 10000))

    results: list[dict[str, Any]] = []
    for lat, lon in points:
        # Distance-from-centre factor: 1.3 at centre, 0.7 at bbox edge
        dist_deg = math.hypot(lat - clat, lon - clon)
        dist_frac = min(dist_deg / half_diag, 1.0)  # 0=centre, 1=edge
        centre_factor = 1.3 - 0.6 * dist_frac       # 1.3 → 0.7 linearly

        radiance_raw = base_radiance * centre_factor
        # Add Gaussian noise, clip to 0
        noise = rng.gauss(0.0, _NOISE_SIGMA)
        radiance = max(0.0, round(radiance_raw + noise, 3))

        # Lit fraction: simulate 0.3–0.9 for non-trivial radiance
        if radiance > 0.3:
            lit_fraction = round(rng.uniform(0.3, 0.9), 3)
        else:
            lit_fraction = 0.0

        results.append({
            "lat":               lat,
            "lon":               lon,
            "radiance_nw":       radiance,
            "lit_fraction":      lit_fraction,
            "quality_flag":      "void_filled",
            "source_record_id":  f"synthetic_fallback_{lat:.4f}_{lon:.4f}",
            "provenance":        prov,
        })

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_ntl_samples(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    *,
    force_source: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch VIIRS NTL point samples covering the bbox.

    Tries sources in order:
      1. NASA Black Marble VNP46A2 (EARTHDATA_TOKEN required)
      2. EOG VIIRS monthly composite (no auth)
      3. Synthetic fallback (always works)

    Returns a list of dicts matching the nightlights_ntl_feed.v1 provider contract:
      lat, lon, radiance_nw, lit_fraction, quality_flag,
      source_record_id, provenance

    Parameters
    ----------
    lat_min, lon_min, lat_max, lon_max
        Bounding box in WGS84 decimal degrees.
    force_source
        ``"nasa"``, ``"eog"``, or ``"synthetic"`` to bypass the normal
        priority order (useful for testing).
    """
    bbox = dict(lat_min=lat_min, lon_min=lon_min, lat_max=lat_max, lon_max=lon_max)
    points = _grid_points(lat_min, lon_min, lat_max, lon_max)
    if not points:
        logger.warning("fetch_ntl_samples: empty grid for bbox %s", bbox)
        return []

    logger.info(
        "Night Lights VIIRS: sampling %d points (spacing=%.4f°) for bbox %s",
        len(points), _SAMPLE_SPACING_DEG, bbox,
    )

    if force_source == "synthetic":
        return _synthetic_ntl(points, bbox)
    if force_source == "nasa":
        return _fetch_black_marble(lat_min, lon_min, lat_max, lon_max) \
               or _synthetic_ntl(points, bbox)
    if force_source == "eog":
        return _fetch_eog_composite(lat_min, lon_min, lat_max, lon_max) \
               or _synthetic_ntl(points, bbox)

    # Normal priority: NASA Black Marble → EOG → synthetic
    result = _fetch_black_marble(lat_min, lon_min, lat_max, lon_max)
    if result is not None:
        return result

    result = _fetch_eog_composite(lat_min, lon_min, lat_max, lon_max)
    if result is not None:
        return result

    return _synthetic_ntl(points, bbox)
