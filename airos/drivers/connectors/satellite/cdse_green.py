"""Sentinel-2 urban green cover connector via Copernicus Data Space Ecosystem (CDSE).

Drop-in replacement for gee_green.py / pc_green.py — same output schema, no GEE
or Planetary Computer dependency.

Authentication: OAuth2 client credentials (CDSE_CLIENT_ID + CDSE_CLIENT_SECRET).

Approach
--------
1. Obtain a short-lived Bearer token from the CDSE identity endpoint.
2. POST two requests to the Sentinel Hub Process API (recent window + baseline
   window), each returning a cloud-filtered GeoTIFF with two float32 bands:
     band 1 — NDVI
     band 2 — EVI
   Mosaicking order: leastCC — the least-cloudy scene within the window is used.
3. Use rasterio.MemoryFile to open each GeoTIFF from memory and sample at H3
   cell centroids.
4. Compute ΔNDVI, classify change, return per-cell signal dict.

Environment variables
---------------------
  CDSE_CLIENT_ID      OAuth2 client ID from CDSE dashboard
  CDSE_CLIENT_SECRET  OAuth2 client secret from CDSE dashboard
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timedelta, timezone

import numpy as np

logger = logging.getLogger(__name__)

_TOKEN_URL  = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

_VEG_THRESHOLD    = 0.15
_CHANGE_THRESHOLD = 0.05
_CLOUD_THRESHOLD  = 30   # % scene-level cloud cover
_OUTPUT_PX        = 512  # image pixels per side — sufficient for H3 res-8 centroids

# Evalscript: return NDVI (band 1) and EVI (band 2) as float32
_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["B02", "B04", "B08"], units: "REFLECTANCE"}],
    output: {bands: 2, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  var eps = 1e-10;
  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + eps);
  var devi = s.B08 + 6.0 * s.B04 - 7.5 * s.B02 + 1.0;
  var evi  = 2.5 * (s.B08 - s.B04) / (devi + eps);
  return [
    Math.max(-1, Math.min(1, ndvi)),
    Math.max(-1, Math.min(1, evi))
  ];
}
"""


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _get_token(client_id: str, client_secret: str) -> str:
    import requests

    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Process API
# ---------------------------------------------------------------------------

def _fetch_composite(
    token: str,
    bbox: list[float],
    start: datetime,
    end: datetime,
) -> bytes | None:
    """Call the Sentinel Hub Process API and return raw GeoTIFF bytes."""
    import requests

    body = {
        "input": {
            "bounds": {
                "bbox":       bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    "mosaickingOrder":  "leastCC",
                    "maxCloudCoverage": _CLOUD_THRESHOLD,
                },
            }],
        },
        "output": {
            "width":  _OUTPUT_PX,
            "height": _OUTPUT_PX,
            "responses": [{
                "identifier": "default",
                "format":     {"type": "image/tiff"},
            }],
        },
        "evalscript": _EVALSCRIPT,
    }

    resp = requests.post(
        _PROCESS_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "Accept":        "image/tiff",
        },
        timeout=120,
    )

    if resp.status_code == 204:
        logger.debug("CDSE: no data for this bbox/window (204 No Content)")
        return None
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# Raster sampling
# ---------------------------------------------------------------------------

def _sample_tiff(tiff_bytes: bytes, h3_cells: list[str]) -> dict[str, tuple[float, float]]:
    """Sample the GeoTIFF at H3 cell centroids.

    Returns {h3_id: (ndvi, evi)} — cells with NaN/nodata are dropped.
    """
    import h3
    import rasterio
    from rasterio.io import MemoryFile

    coords = [(h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]) for c in h3_cells]

    with MemoryFile(tiff_bytes) as mf, mf.open() as ds:
        # rasterio.sample expects (x=lon, y=lat) pairs in the dataset CRS
        sampled = list(ds.sample(coords))

    out: dict[str, tuple[float, float]] = {}
    for cell, vals in zip(h3_cells, sampled):
        ndvi, evi = float(vals[0]), float(vals[1])
        if np.isnan(ndvi) or np.isnan(evi):
            continue
        out[cell] = (ndvi, evi)
    return out


# ---------------------------------------------------------------------------
# Index helpers (shared with output classification)
# ---------------------------------------------------------------------------

def _coverage_class(ndvi: float) -> str:
    if ndvi >= 0.6:  return "dense"
    if ndvi >= 0.4:  return "moderate"
    if ndvi >= 0.2:  return "sparse"
    return "bare"


def _change_category(delta: float) -> str:
    if delta < -0.15: return "significant_loss"
    if delta < -0.05: return "moderate_loss"
    if delta >  0.05: return "gain"
    return "stable"


# ---------------------------------------------------------------------------
# Public API  (same signature as gee_green.fetch_green_cover)
# ---------------------------------------------------------------------------

def fetch_green_cover(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,   # unused — kept for signature compatibility
    recent_days: int = 30,
    baseline_days: int = 365,
) -> dict[str, dict]:
    """Return {h3_id: green_cover_dict} using CDSE Sentinel Hub (no GEE required).

    Reads CDSE_CLIENT_ID and CDSE_CLIENT_SECRET from the environment.

    Output dict keys per cell:
      ndvi, evi, ndvi_baseline, ndvi_change, change_category,
      coverage_class, green_cover_change_index
    """
    if not h3_cells:
        return {}

    client_id     = os.environ.get("CDSE_CLIENT_ID",     "").strip()
    client_secret = os.environ.get("CDSE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.debug("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set — skipping green cover fetch")
        return {}

    try:
        import rasterio  # noqa: F401 — validate import early
    except ImportError:
        logger.error("rasterio not installed. Run: pip install rasterio")
        return {}

    bbox = [lon_min, lat_min, lon_max, lat_max]
    now  = datetime.now(timezone.utc)

    recent_end   = now
    recent_start = now - timedelta(days=recent_days)
    base_end     = now - timedelta(days=recent_days)
    base_start   = now - timedelta(days=baseline_days)

    try:
        token = _get_token(client_id, client_secret)
        logger.debug("CDSE token obtained")

        recent_tiff   = _fetch_composite(token, bbox, recent_start,   recent_end)
        baseline_tiff = _fetch_composite(token, bbox, base_start,     base_end)

        if recent_tiff is None:
            logger.warning("Green cover: no usable recent scenes from CDSE for bbox %s", bbox)
            return {}

        recent_vals   = _sample_tiff(recent_tiff,   h3_cells)
        baseline_vals = _sample_tiff(baseline_tiff, h3_cells) if baseline_tiff else {}

        result: dict[str, dict] = {}
        for h3_id, (ndvi, evi) in recent_vals.items():
            ndvi_baseline = baseline_vals[h3_id][0] if h3_id in baseline_vals else ndvi
            delta = round(ndvi - ndvi_baseline, 4)

            if ndvi < _VEG_THRESHOLD and abs(delta) < _CHANGE_THRESHOLD:
                continue

            gcci = round(float(np.clip(delta * 4, -1, 1)), 4)

            result[h3_id] = {
                "ndvi":                     round(ndvi, 4),
                "evi":                      round(evi,  4),
                "ndvi_baseline":            round(ndvi_baseline, 4),
                "ndvi_change":              delta,
                "change_category":          _change_category(delta),
                "coverage_class":           _coverage_class(ndvi),
                "green_cover_change_index": gcci,
            }

        logger.info(
            "Green cover (CDSE): %d vegetated cells, %d with change",
            len(result),
            sum(1 for v in result.values() if v["change_category"] != "stable"),
        )
        return result

    except Exception as exc:
        logger.warning("Green cover (CDSE) failed: %s", exc)
        return {}
