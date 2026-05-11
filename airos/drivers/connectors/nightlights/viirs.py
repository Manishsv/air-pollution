"""VIIRS Night-Time Light (NTL) connector — monthly composite samples for a city bbox.

Sources (tried in order, first success wins):
  1. NASA Black Marble VNP46A3 via HTTPS — requires EARTHDATA_TOKEN env var
     (free NASA Earthdata account at urs.earthdata.nasa.gov).
     Queries NASA CMR API for granule URLs, downloads HDF5 tiles to
     cache/nightlights/, reprojects sinusoidal pixels → WGS84, and returns
     NearNadir_Composite_Snow_Free radiance with quality-flag filtering.
  2. EOG VIIRS monthly composite via HTTP — no auth required.
     URL: https://eogdata.mines.edu/nighttime_light/monthly_notile/v10/{year}/{month}/
     GeoTIFF download — implemented as stub that falls through to tier 3.
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

import json
import logging
import math
import os
import random
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Sampling grid density (synthetic fallback only) ──────────────────────────
# VIIRS DNB pixel is ~500 m — use ~0.005° (~500 m) spacing to match.
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
_NOISE_SIGMA      = 5.0    # Gaussian noise sigma for synthetic variation

# ── VIIRS / MODIS sinusoidal projection constants ─────────────────────────────
# The MODIS/VIIRS sinusoidal grid divides the globe into 36 (H) × 18 (V) tiles.
# Forward projection:  x = R·λ·cos(φ),  y = R·φ   (λ, φ in radians)
# Inverse projection:  φ = y/R,          λ = x/(R·cos(φ))
_R_EARTH     = 6_371_007.181            # m — MODIS/VIIRS Earth radius
_T_SIZE      = 2.0 * math.pi * _R_EARTH / 36   # ≈ 1 111 950 m per tile
_PIR         = math.pi * _R_EARTH       # πR  — half x-extent
_PIR2        = math.pi * _R_EARTH / 2  # πR/2 — half y-extent
_TILE_PIXELS = 2400                     # VNP46A3: 2400 × 2400 pixels at 500 m
_PIXEL_SIZE  = _T_SIZE / _TILE_PIXELS  # ≈ 463.3 m

# VNP46A3 HDF5 dataset paths.
# Grid group changed from VNP_Grid_DNB → VIIRS_Grid_DNB_2d in version 2.
# Values are already in nW/cm²/sr (scale_factor=1.0, offset=0.0).
_HDF_ROOT     = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
_HDF_NTL_CANDIDATES = [
    f"{_HDF_ROOT}/NearNadir_Composite_Snow_Free",   # preferred: near-nadir only
    f"{_HDF_ROOT}/AllAngle_Composite_Snow_Free",     # fallback: all-angle composite
    f"{_HDF_ROOT}/OffNadir_Composite_Snow_Free",     # last resort
    # Legacy paths (older product versions)
    "HDFEOS/GRIDS/VNP_Grid_DNB/Data Fields/NearNadir_Composite_Snow_Free",
    "HDFEOS/GRIDS/VNP_Grid_DNB/Data Fields/AllAngle_Composite_Snow_Free",
]
_HDF_QA_CANDIDATES = [
    f"{_HDF_ROOT}/NearNadir_Composite_Snow_Free_Quality",
    f"{_HDF_ROOT}/AllAngle_Composite_Snow_Free_Quality",
    "HDFEOS/GRIDS/VNP_Grid_DNB/Data Fields/Mandatory_Quality_Flag",
]
_HDF_LAT      = f"{_HDF_ROOT}/lat"   # 1-D latitude  array  (shape 2400)
_HDF_LON      = f"{_HDF_ROOT}/lon"   # 1-D longitude array  (shape 2400)

_NTL_FILL_F   = -999.9   # float fill value (version 2 uses float32)
_NTL_FILL_I   = 65535    # integer fill value (legacy versions)
_QA_FILL      = 255      # quality-flag fill

# NASA CMR granule search API
_CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
_PRODUCT_NAME = "VNP46A3"   # monthly composite
_CMR_VERSION  = "2"         # collection version (must be "2", not "001")

# Local tile cache — survives across ingest runs
_CACHE_DIR = Path(__file__).parents[4] / "cache" / "nightlights"


# ── Sinusoidal projection helpers ─────────────────────────────────────────────

def _latlon_to_tile(lat: float, lon: float) -> tuple[int, int]:
    """Return VIIRS sinusoidal tile (h, v) containing WGS84 (lat, lon)."""
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    x = _R_EARTH * lon_r * math.cos(lat_r)
    y = _R_EARTH * lat_r
    h = int((x + _PIR) / _T_SIZE)
    v = int((_PIR2 - y) / _T_SIZE)
    return max(0, min(35, h)), max(0, min(17, v))


def _pixel_to_latlon(h: int, v: int, row: int, col: int) -> tuple[float, float]:
    """Convert tile pixel (row, col) to WGS84 (lat, lon) via inverse sinusoidal."""
    x = -_PIR + h * _T_SIZE + (col + 0.5) * _PIXEL_SIZE
    y =  _PIR2 - v * _T_SIZE - (row + 0.5) * _PIXEL_SIZE
    lat_r = y / _R_EARTH
    cos_lat = math.cos(lat_r)
    lon_r = x / (_R_EARTH * cos_lat) if abs(cos_lat) > 1e-10 else 0.0
    return math.degrees(lat_r), math.degrees(lon_r)


def _bbox_tiles(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> list[tuple[int, int]]:
    """Return all VIIRS tiles intersecting the bbox (typically 1–4)."""
    seen: set[tuple[int, int]] = set()
    for lat in (lat_min, lat_max):
        for lon in (lon_min, lon_max):
            seen.add(_latlon_to_tile(lat, lon))
    return sorted(seen)


def _last_available_month() -> tuple[int, int]:
    """
    (year, month) of the most recently available VNP46A3 composite.

    NASA Black Marble monthly composites have a ~2-month processing lag, so
    we request the composite from 2 months prior to today.
    """
    now = datetime.now(timezone.utc)
    month = now.month - 2
    year  = now.year
    if month < 1:
        month += 12
        year  -= 1
    return year, month


# ── NASA CMR granule search ───────────────────────────────────────────────────

def _find_granule_urls(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    year: int, month: int,
    token: str,
) -> dict[tuple[int, int], str]:
    """
    Query NASA CMR for VNP46A3 granule download URLs intersecting the bbox.

    Returns a dict mapping tile (h, v) → HTTPS download URL.
    """
    import calendar
    import re

    last_day = calendar.monthrange(year, month)[1]
    params = urllib.parse.urlencode({
        "short_name":   _PRODUCT_NAME,
        "version":      _CMR_VERSION,
        "temporal":     (
            f"{year}-{month:02d}-01T00:00:00Z,"
            f"{year}-{month:02d}-{last_day:02d}T23:59:59Z"
        ),
        "bounding_box": f"{lon_min:.4f},{lat_min:.4f},{lon_max:.4f},{lat_max:.4f}",
        "page_size":    "20",
    })
    cmr_url = f"{_CMR_GRANULES}?{params}"
    logger.debug("CMR query: %s", cmr_url)

    req = urllib.request.Request(cmr_url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("Night Lights CMR search failed: %s", exc)
        return {}

    # Parse (h, v) from granule title and extract .h5 data links
    _TILE_RE = re.compile(r"\.h(\d{2})v(\d{2})\.")
    tile_urls: dict[tuple[int, int], str] = {}

    for entry in data.get("feed", {}).get("entry", []):
        title = entry.get("producer_granule_id") or entry.get("title", "")
        m = _TILE_RE.search(title)
        if not m:
            continue
        tile = (int(m.group(1)), int(m.group(2)))

        for link in entry.get("links", []):
            href = link.get("href", "")
            if href.endswith(".h5"):
                tile_urls[tile] = href
                break

    logger.info(
        "CMR: %d tile(s) found for bbox (%.3f,%.3f,%.3f,%.3f) %d/%02d — tiles: %s",
        len(tile_urls), lat_min, lon_min, lat_max, lon_max, year, month,
        sorted(tile_urls.keys()),
    )
    return tile_urls


# ── HDF5 tile download ────────────────────────────────────────────────────────

def _download_tile(url: str, token: str) -> Path | None:
    """
    Download a VNP46A3 HDF5 tile to the local cache directory.

    Uses Bearer-token auth required by NASA Earthdata Cloud.
    Files are cached by filename — subsequent calls for the same granule
    return immediately from disk without re-downloading.

    Returns the local Path on success, None on error.
    """
    fname = url.rsplit("/", 1)[-1]
    dest  = _CACHE_DIR / fname

    if dest.exists() and dest.stat().st_size > 1_000_000:
        logger.debug("NTL tile cache hit: %s", fname)
        return dest

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".h5.tmp")

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            status = resp.status
            if status == 401:
                logger.error(
                    "NTL download: 401 Unauthorized — EARTHDATA_TOKEN may be invalid "
                    "or expired. Renew at https://urs.earthdata.nasa.gov/"
                )
                return None
            with open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out)
        tmp.rename(dest)
        logger.info(
            "NTL tile downloaded: %s (%.1f MB)", fname, dest.stat().st_size / 1e6
        )
        return dest
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        logger.warning(
            "NTL tile download HTTP %d for %s: %s", exc.code, fname, exc.reason
        )
        return None
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        logger.warning("NTL tile download failed for %s: %s", fname, exc)
        return None


# ── HDF5 pixel extraction ─────────────────────────────────────────────────────

def _extract_samples_hdf5(
    filepath: Path,
    h: int, v: int,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    acquired: str,
) -> list[dict[str, Any]]:
    """
    Extract NTL pixel samples within the bbox from a VNP46A3 HDF5 file.

    VNP46A3 version 2 provides:
    - NearNadir_Composite_Snow_Free (float32, nW/cm2/sr already, fill=-999.9)
    - NearNadir_Composite_Snow_Free_Quality (uint8, fill=255)
    - 1-D lat/lon arrays for direct coordinate lookup (no projection math needed)

    Returns a list of point dicts matching the nightlights_ntl_feed.v1 contract.
    """
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        logger.error("Missing dependency for HDF5 parsing: %s. pip install h5py numpy", exc)
        return []

    prov = _provenance(f"nasa_vnp46a3_{filepath.stem}", collected_at=acquired)

    # Open HDF5 and load all needed arrays in one pass
    try:
        with h5py.File(filepath, "r") as f:
            # NTL radiance: try candidates in priority order
            ntl_arr = None
            ntl_path = None
            for candidate in _HDF_NTL_CANDIDATES:
                if candidate in f:
                    ntl_arr  = f[candidate][:]
                    ntl_path = candidate
                    break
            if ntl_arr is None:
                avail: list[str] = []
                f.visititems(
                    lambda name, obj, _h=__import__("h5py"):
                    avail.append(name) if isinstance(obj, _h.Dataset) else None
                )
                logger.warning(
                    "No known NTL dataset in %s. Datasets found:\n  %s",
                    filepath.name, "\n  ".join(avail[:30]),
                )
                return []

            # Quality flag array (gracefully absent in some versions)
            qa_arr = None
            for qcand in _HDF_QA_CANDIDATES:
                if qcand in f:
                    qa_arr = f[qcand][:]
                    break

            # 1-D coordinate arrays (version 2 embeds these directly)
            has_coords = _HDF_LAT in f and _HDF_LON in f
            if has_coords:
                lat_arr = f[_HDF_LAT][:]   # shape (nrows,)
                lon_arr = f[_HDF_LON][:]   # shape (ncols,)

    except Exception as exc:
        logger.warning("HDF5 read error for %s: %s", filepath.name, exc)
        return []

    nrows, ncols = ntl_arr.shape
    is_float = ntl_arr.dtype.kind == "f"
    logger.debug(
        "NTL h%02dv%02d: dataset='%s' shape=%dx%d dtype=%s has_coords=%s",
        h, v, ntl_path, nrows, ncols, ntl_arr.dtype, has_coords,
    )

    # Find row/col index window for the bbox
    if has_coords:
        # Use embedded coordinate arrays with binary search (fast, exact)
        if lat_arr[0] > lat_arr[-1]:
            # Descending lat (north-to-south): lat_max -> smaller row index
            row0 = max(0,     int(np.searchsorted(-lat_arr, -lat_max, "left"))  - 1)
            row1 = min(nrows, int(np.searchsorted(-lat_arr, -lat_min, "right")) + 1)
        else:
            row0 = max(0,     int(np.searchsorted(lat_arr, lat_min, "left"))  - 1)
            row1 = min(nrows, int(np.searchsorted(lat_arr, lat_max, "right")) + 1)
        col0 = max(0,     int(np.searchsorted(lon_arr, lon_min, "left"))  - 1)
        col1 = min(ncols, int(np.searchsorted(lon_arr, lon_max, "right")) + 1)

        lat_win = lat_arr[row0:row1]
        lon_win = lon_arr[col0:col1]
    else:
        # Fallback: approximate via sinusoidal projection math
        def _lat_to_row_approx(lat_deg: float) -> float:
            y = _R_EARTH * math.radians(lat_deg)
            return (_PIR2 - v * _T_SIZE - y) / _PIXEL_SIZE - 0.5

        row0 = max(0,     int(_lat_to_row_approx(lat_max)) - 2)
        row1 = min(nrows, int(_lat_to_row_approx(lat_min)) + 3)

        mid_cos  = math.cos(math.radians((lat_min + lat_max) / 2.0))
        x0_tile  = -_PIR + h * _T_SIZE

        def _lon_to_col_approx(lon_deg: float) -> float:
            return (_R_EARTH * math.radians(lon_deg) * mid_cos - x0_tile) / _PIXEL_SIZE - 0.5

        col0 = max(0,     int(_lon_to_col_approx(lon_min)) - 5)
        col1 = min(ncols, int(_lon_to_col_approx(lon_max)) + 6)

        # Build coordinate arrays via sinusoidal inverse projection
        lat_win = np.array([_pixel_to_latlon(h, v, r, col0)[0] for r in range(row0, row1)])
        lon_win = np.array([_pixel_to_latlon(h, v, row0, c)[1] for c in range(col0, col1)])

    ntl_win = ntl_arr[row0:row1, col0:col1]
    qa_win  = qa_arr[row0:row1, col0:col1] if qa_arr is not None else None
    win_rows, win_cols = ntl_win.shape

    logger.debug(
        "NTL h%02dv%02d: window rows=%d-%d (%d), cols=%d-%d (%d)",
        h, v, row0, row1, win_rows, col0, col1, win_cols,
    )

    # Extract samples
    results: list[dict[str, Any]] = []
    for ri in range(win_rows):
        lat = float(lat_win[ri])
        if not (lat_min <= lat <= lat_max):
            continue

        for ci in range(win_cols):
            lon = float(lon_win[ci])
            if not (lon_min <= lon <= lon_max):
                continue

            raw_val = ntl_win[ri, ci]

            # Fill / no-data filter
            if is_float:
                fval = float(raw_val)
                if fval <= _NTL_FILL_F + 1.0:   # -999.9 fill (allow tiny float err)
                    continue
                radiance = round(fval, 3)
            else:
                ival = int(raw_val)
                if ival >= _NTL_FILL_I:
                    continue
                radiance = round(ival * 0.1, 3)  # legacy DN scale

            if radiance < 0.0:
                continue

            # Quality gate: 0=good, 1=tentatively good, 2=poor (kept as degraded)
            if qa_win is not None:
                qa = int(qa_win[ri, ci])
                if qa == _QA_FILL:
                    continue
                qflag = "good" if qa == 0 else "degraded"
            else:
                qflag = "good"

            lit_fraction = 1.0 if radiance > 0.0 else 0.0

            results.append({
                "lat":              round(lat, 6),
                "lon":              round(lon, 6),
                "radiance_nw":      radiance,
                "lit_fraction":     lit_fraction,
                "quality_flag":     qflag,
                "source_record_id": (
                    f"nasa_vnp46a3_{filepath.stem}_r{row0+ri:04d}c{col0+ci:04d}"
                ),
                "provenance":       prov,
            })

    logger.info(
        "NTL HDF5 h%02dv%02d: %d samples from %dx%d pixel window",
        h, v, len(results), win_rows, win_cols,
    )
    return results


# ── Helper shared across sources ─────────────────────────────────────────────

def _grid_points(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    spacing: float = _SAMPLE_SPACING_DEG,
) -> list[tuple[float, float]]:
    """Generate a regular lat/lon grid covering the bbox (used by synthetic tier)."""
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


# ── Source 1: NASA Black Marble VNP46A3 ──────────────────────────────────────

def _fetch_black_marble(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> list[dict[str, Any]] | None:
    """
    NASA Black Marble VNP46A3 monthly composite (500 m VIIRS DNB).

    Requires EARTHDATA_TOKEN environment variable (free account at
    https://urs.earthdata.nasa.gov/).

    Pipeline:
      1. Query NASA CMR for VNP46A3 granule URLs covering the bbox.
      2. Download HDF5 tiles (cached in cache/nightlights/).
      3. Reproject sinusoidal pixels → WGS84 lat/lon.
      4. Return NearNadir_Composite_Snow_Free samples (nW/cm²/sr).

    Returns None on missing token, no CMR results, or download/parse failure
    (triggers fall-through to EOG tier or synthetic fallback).
    """
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        logger.info(
            "Night Lights (NASA Black Marble): EARTHDATA_TOKEN not set. "
            "Register free at https://urs.earthdata.nasa.gov/ to enable real VIIRS data. "
            "Falling through to EOG composite tier."
        )
        return None

    year, month = _last_available_month()
    logger.info(
        "Night Lights (NASA Black Marble): fetching VNP46A3 for %d/%02d, "
        "bbox=(%.3f, %.3f, %.3f, %.3f) ...",
        year, month, lat_min, lon_min, lat_max, lon_max,
    )

    # Step 1: find tiles and their granule URLs via CMR
    tile_urls = _find_granule_urls(
        lat_min, lon_min, lat_max, lon_max, year, month, token,
    )
    if not tile_urls:
        logger.warning(
            "Night Lights (NASA Black Marble): CMR returned no granules. "
            "Falling through to EOG tier."
        )
        return None

    acquired = f"{year}-{month:02d}-01T00:00:00Z"
    all_samples: list[dict[str, Any]] = []

    # Step 2-4: for each tile, download HDF5 and extract samples
    for (h, v), url in sorted(tile_urls.items()):
        logger.info("NTL: downloading tile h%02dv%02d from %s ...", h, v, url)
        filepath = _download_tile(url, token)
        if filepath is None:
            logger.warning(
                "NTL: download failed for tile h%02dv%02d — skipping.", h, v
            )
            continue

        samples = _extract_samples_hdf5(
            filepath, h, v,
            lat_min, lon_min, lat_max, lon_max,
            acquired,
        )
        all_samples.extend(samples)

    if not all_samples:
        logger.warning(
            "Night Lights (NASA Black Marble): 0 samples extracted from %d tile(s). "
            "Falling through to EOG tier.",
            len(tile_urls),
        )
        return None

    logger.info(
        "Night Lights (NASA Black Marble): %d samples from %d tile(s).",
        len(all_samples), len(tile_urls),
    )
    return all_samples


# ── Source 2: EOG VIIRS monthly composite ────────────────────────────────────

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


# ── Source 3: Synthetic fallback ──────────────────────────────────────────────

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
        dist_deg  = math.hypot(lat - clat, lon - clon)
        dist_frac = min(dist_deg / half_diag, 1.0)   # 0=centre, 1=edge
        centre_factor = 1.3 - 0.6 * dist_frac         # 1.3 → 0.7 linearly

        radiance_raw = base_radiance * centre_factor
        noise        = rng.gauss(0.0, _NOISE_SIGMA)
        radiance     = max(0.0, round(radiance_raw + noise, 3))

        lit_fraction = round(rng.uniform(0.3, 0.9), 3) if radiance > 0.3 else 0.0

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
      1. NASA Black Marble VNP46A3 (EARTHDATA_TOKEN required)
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
    bbox   = dict(lat_min=lat_min, lon_min=lon_min, lat_max=lat_max, lon_max=lon_max)
    points = _grid_points(lat_min, lon_min, lat_max, lon_max)
    if not points:
        logger.warning("fetch_ntl_samples: empty grid for bbox %s", bbox)
        return []

    logger.info(
        "Night Lights VIIRS: bbox=(%.3f,%.3f,%.3f,%.3f) — %d synthetic grid points "
        "(used only if real sources fail)",
        lat_min, lon_min, lat_max, lon_max, len(points),
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
