"""Sentinel-2 + Sentinel-5P waste site detection connector via CDSE Sentinel Hub.

Drop-in replacement for gee_waste.py — same output schema, no GEE dependency.

Two Process API requests per call:
  1. Sentinel-2 L2A  → NDVI   [1-band GeoTIFF, 512×512]
     NDVI < 0.15 in urban context = likely exposed waste / dump site
  2. Sentinel-5P L2  → CH4    [1-band GeoTIFF, 64×64]
     Elevation above ~1880 ppb background = landfill gas signal

Preserves the same two public functions as gee_waste.py so existing callers
(data_cache.py) need only an import swap.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from .cdse_core import get_credentials, get_token, fetch_tiff, sample_tiff

logger = logging.getLogger(__name__)

_CH4_BACKGROUND_PPB = 1880.0

_EVALSCRIPT_S2_NDVI = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["B04", "B08"], units: "REFLECTANCE"}],
    output: {bands: 1, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  var eps = 1e-10;
  return [(s.B08 - s.B04) / (s.B08 + s.B04 + eps)];
}
"""

_EVALSCRIPT_S5P_CH4 = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["CH4"]}],
    output: {bands: 1, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  return [isNaN(s.CH4) ? 0.0 : s.CH4];
}
"""


def _time_range(lookback_days: int) -> dict:
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    return {
        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fetch_ndvi_for_cells(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 10,
) -> dict[str, float]:
    """Return {h3_id: ndvi} from Sentinel-2 L2A via CDSE."""
    if not h3_cells:
        return {}

    creds = get_credentials()
    if not creds:
        logger.debug("CDSE credentials not set — skipping NDVI fetch")
        return {}

    bbox = [lon_min, lat_min, lon_max, lat_max]
    cfg  = {
        "type": "sentinel-2-l2a",
        "dataFilter": {
            "timeRange":        _time_range(lookback_days),
            "mosaickingOrder":  "leastCC",
            "maxCloudCoverage": 30,
        },
    }

    try:
        token = get_token(*creds)
        tiff  = fetch_tiff(token, bbox, cfg, _EVALSCRIPT_S2_NDVI)
        if tiff is None:
            return {}

        raw = sample_tiff(tiff, h3_cells)
        result = {h3_id: round(bands[0], 4) for h3_id, bands in raw.items()}
        logger.info("Sentinel-2 NDVI (CDSE): sampled %d / %d cells", len(result), len(h3_cells))
        return result

    except Exception as exc:
        logger.warning("NDVI fetch (CDSE) failed: %s", exc)
        return {}


def fetch_ch4_for_cells(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 10,
) -> dict[str, float]:
    """Return {h3_id: ch4_ppb} from Sentinel-5P TROPOMI via CDSE."""
    if not h3_cells:
        return {}

    creds = get_credentials()
    if not creds:
        logger.debug("CDSE credentials not set — skipping CH4 fetch")
        return {}

    bbox = [lon_min, lat_min, lon_max, lat_max]
    cfg  = {
        "type": "sentinel-5p-l2",
        "dataFilter": {
            "timeRange":  _time_range(lookback_days),
            "timeliness": "NRTI",
        },
    }

    try:
        token = get_token(*creds)
        tiff  = fetch_tiff(token, bbox, cfg, _EVALSCRIPT_S5P_CH4, px=64)
        if tiff is None:
            return {}

        raw = sample_tiff(tiff, h3_cells)
        result = {
            h3_id: round(bands[0], 2)
            for h3_id, bands in raw.items()
            if bands[0] > 0
        }
        logger.info("Sentinel-5P CH4 (CDSE): sampled %d / %d cells", len(result), len(h3_cells))
        return result

    except Exception as exc:
        logger.warning("CH4 fetch (CDSE) failed: %s", exc)
        return {}
