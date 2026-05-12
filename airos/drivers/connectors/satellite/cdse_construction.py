"""Sentinel-2 + Sentinel-5P construction activity connector via CDSE Sentinel Hub.

Drop-in replacement for gee_construction.py — same output schema, no GEE dependency.

Two Process API requests per call:
  1. Sentinel-2 L2A  → BSI (Bare Soil Index) + NDVI  [2-band GeoTIFF, 512×512]
  2. Sentinel-5P L2  → NO2 tropospheric column        [1-band GeoTIFF, 64×64]

CRI (Construction Risk Index) = (BSI_score × 0.6 + NO2_score × 0.4) × NDVI_damping_factor.
Only cells with BSI > 0.05 are returned.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from .cdse_core import get_credentials, get_token, fetch_tiff, sample_tiff

logger = logging.getLogger(__name__)

_BSI_THRESHOLD  = 0.05
_CLOUD_THRESHOLD = 30
_NO2_BACKGROUND  = 3.5e-5   # mol/m² — typical South Asian urban background
_NO2_HIGH        = 1.5e-4   # mol/m² — heavy construction / traffic

_EVALSCRIPT_S2 = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["B02", "B04", "B08", "B11"], units: "REFLECTANCE"}],
    output: {bands: 2, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  var eps  = 1e-10;
  var bsi  = ((s.B11 + s.B04) - (s.B08 + s.B02))
           / ((s.B11 + s.B04) + (s.B08 + s.B02) + eps);
  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + eps);
  return [bsi, ndvi];
}
"""

_EVALSCRIPT_S5P_NO2 = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["NO2"]}],
    output: {bands: 1, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  return [isNaN(s.NO2) ? 0.0 : s.NO2];
}
"""


def fetch_construction_signals(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,   # unused — kept for signature compatibility
    lookback_days: int = 20,
) -> dict[str, dict]:
    """Return {h3_id: construction_signal_dict} for cells with BSI > 0.05.

    Output keys: bsi, ndvi, no2_mol_m2, bsi_score, no2_score,
                 ndvi_factor, construction_risk_index.
    """
    if not h3_cells:
        return {}

    creds = get_credentials()
    if not creds:
        logger.debug("CDSE credentials not set — skipping construction signals fetch")
        return {}

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    bbox  = [lon_min, lat_min, lon_max, lat_max]

    time_range = {
        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    s2_config = {
        "type": "sentinel-2-l2a",
        "dataFilter": {
            "timeRange":        time_range,
            "mosaickingOrder":  "leastCC",
            "maxCloudCoverage": _CLOUD_THRESHOLD,
        },
    }
    s5p_config = {
        "type": "sentinel-5p-l2",
        "dataFilter": {
            "timeRange":  time_range,
            "timeliness": "NRTI",
        },
    }

    try:
        token = get_token(*creds)

        s2_tiff  = fetch_tiff(token, bbox, s2_config,  _EVALSCRIPT_S2,       px=512)
        s5p_tiff = fetch_tiff(token, bbox, s5p_config, _EVALSCRIPT_S5P_NO2,  px=64)

        if s2_tiff is None:
            logger.warning("Construction: no CDSE S2 data for bbox %s", bbox)
            return {}

        s2_vals  = sample_tiff(s2_tiff,  h3_cells)
        no2_vals = sample_tiff(s5p_tiff, h3_cells) if s5p_tiff else {}

        result: dict[str, dict] = {}
        for h3_id, bands in s2_vals.items():
            bsi, ndvi = bands[0], bands[1]

            if bsi <= _BSI_THRESHOLD:
                continue

            no2 = no2_vals[h3_id][0] if h3_id in no2_vals else _NO2_BACKGROUND
            if np.isnan(no2) or no2 <= 0:
                no2 = _NO2_BACKGROUND

            bsi_score = float(np.clip(
                (bsi  - _BSI_THRESHOLD)  / (0.5 - _BSI_THRESHOLD), 0, 1))
            no2_score = float(np.clip(
                (no2  - _NO2_BACKGROUND) / (_NO2_HIGH - _NO2_BACKGROUND), 0, 1))

            ndvi_factor = max(0.3, 1.0 - max(0.0, ndvi))
            cri = float(np.clip((bsi_score * 0.6 + no2_score * 0.4) * ndvi_factor, 0, 1))

            result[h3_id] = {
                "bsi":                     round(bsi,        4),
                "ndvi":                    round(ndvi,       4),
                "no2_mol_m2":              round(no2,        8),
                "bsi_score":               round(bsi_score,  3),
                "no2_score":               round(no2_score,  3),
                "ndvi_factor":             round(ndvi_factor,3),
                "construction_risk_index": round(cri,        4),
            }

        logger.info("Construction signals (CDSE): %d active cells", len(result))
        return result

    except Exception as exc:
        logger.warning("Construction signals (CDSE) failed: %s", exc)
        return {}
