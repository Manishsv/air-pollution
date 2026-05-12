"""Sentinel-2 water quality connector via CDSE Sentinel Hub.

Drop-in replacement for gee_water.py — same output schema, no GEE dependency.

Indices computed (server-side via evalscript):
  MNDWI  (Green − SWIR1) / (Green + SWIR1)   water body presence (> 0 = water)
  NDTI   (Red − Green) / (Red + Green)         turbidity / suspended sediment
  CI     Red-Edge / Red                         chlorophyll index (algal bloom)
  FAI    B08 − [B04 + (B11−B04) × slope]       floating algae / surface scum

Only cells where MNDWI > 0 are returned.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from .cdse_core import get_credentials, get_token, fetch_tiff, sample_tiff

logger = logging.getLogger(__name__)

_WATER_THRESHOLD = 0.0
_CLOUD_THRESHOLD = 30
_FAI_SLOPE       = (833 - 665) / (1610 - 665)

_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input:  [{bands: ["B03", "B04", "B05", "B08", "B11"], units: "REFLECTANCE"}],
    output: {bands: 4, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  var eps = 1e-10;
  var mndwi = (s.B03 - s.B11) / (s.B03 + s.B11 + eps);
  var ndti  = (s.B04 - s.B03) / (s.B04 + s.B03 + eps);
  var ci    = s.B05 / (s.B04 + eps);
  var fai   = s.B08 - (s.B04 + (s.B11 - s.B04) * """ + str(_FAI_SLOPE) + """);
  return [mndwi, ndti, ci, fai];
}
"""

_DATA_CONFIG = {
    "type": "sentinel-2-l2a",
    "dataFilter": {
        "mosaickingOrder":  "leastCC",
        "maxCloudCoverage": _CLOUD_THRESHOLD,
    },
}


def fetch_water_quality(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,   # unused — kept for signature compatibility
    lookback_days: int = 10,
) -> dict[str, dict]:
    """Return {h3_id: water_quality_dict} for cells where MNDWI > 0.

    Output keys: mndwi, ndti, ci, fai, water_quality_index,
                 turbidity_score, algal_score, foam_score.
    """
    if not h3_cells:
        return {}

    creds = get_credentials()
    if not creds:
        logger.debug("CDSE credentials not set — skipping water quality fetch")
        return {}

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    bbox  = [lon_min, lat_min, lon_max, lat_max]

    cfg = {**_DATA_CONFIG, "dataFilter": {
        **_DATA_CONFIG["dataFilter"],
        "timeRange": {
            "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }}

    try:
        token = get_token(*creds)
        tiff  = fetch_tiff(token, bbox, cfg, _EVALSCRIPT)
        if tiff is None:
            logger.warning("Water quality: no CDSE data for bbox %s", bbox)
            return {}

        raw = sample_tiff(tiff, h3_cells)

        result: dict[str, dict] = {}
        for h3_id, bands in raw.items():
            mndwi, ndti, ci, fai = bands[0], bands[1], bands[2], bands[3]

            if mndwi <= _WATER_THRESHOLD:
                continue  # not a water cell

            turb_score  = float(np.clip((ndti  + 0.2) / 0.6,  0, 1))
            algal_score = float(np.clip((ci    - 1.0) / 2.0,  0, 1))
            foam_score  = float(np.clip(fai          / 0.05,  0, 1))

            wqi = min(1.0,
                      max(turb_score * 0.4 + algal_score * 0.4 + foam_score * 0.2,
                          turb_score, algal_score, foam_score * 0.8))

            result[h3_id] = {
                "mndwi":               round(mndwi,      4),
                "ndti":                round(ndti,       4),
                "ci":                  round(ci,         4),
                "fai":                 round(fai,        6),
                "water_quality_index": round(wqi,        4),
                "turbidity_score":     round(turb_score, 3),
                "algal_score":         round(algal_score,3),
                "foam_score":          round(foam_score, 3),
            }

        logger.info("Water quality (CDSE): %d water cells found", len(result))
        return result

    except Exception as exc:
        logger.warning("Water quality (CDSE) failed: %s", exc)
        return {}
