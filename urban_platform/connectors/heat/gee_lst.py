"""
Google Earth Engine connector for urban heat risk.

Fetches Land Surface Temperature (MODIS MOD11A1) and NDVI (Sentinel-2)
for a city bounding box and returns per-point observations compatible
with the heat pipeline's input format.

Requires:
  - earthengine-api installed  (pip install earthengine-api)
  - GEE authenticated          (run `earthengine authenticate` once, or
                                set GOOGLE_APPLICATION_CREDENTIALS)

LST source:  MODIS/061/MOD11A1  — 1 km, daily Terra overpass
NDVI source: COPERNICUS/S2_SR_HARMONIZED — 10 m, ~5 day revisit
             (used for green cover fraction; cloud-masked)

Heat risk score (0–1):
  lst_score  = clip((lst_c - 25) / 20, 0, 1)   # 25°C → 0, 45°C → 1
  ndvi_score = 1 - clip(ndvi, 0, 1)             # high NDVI = low heat risk
  heat_risk  = 0.7 * lst_score + 0.3 * ndvi_score
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "temperature_c", "apparent_temperature_c", "relative_humidity_pct",
    "lst_c", "ndvi", "heat_risk_score",
    "data_source", "quality_flag",
]

_LST_COLLECTION  = "MODIS/061/MOD11A1"
_S2_COLLECTION   = "COPERNICUS/S2_SR_HARMONIZED"
_LST_BAND        = "LST_Day_1km"
_LST_SCALE       = 0.02       # Kelvin scale factor
_LST_OFFSET      = -273.15    # K → °C

# Grid resolution: sample every ~1 km across the bbox
_SAMPLE_STEP_DEG = 0.009      # ~1 km at Indian latitudes


def _make_grid(lat_min, lon_min, lat_max, lon_max) -> list[tuple[float, float]]:
    lats = list(np.arange(lat_min, lat_max, _SAMPLE_STEP_DEG))
    lons = list(np.arange(lon_min, lon_max, _SAMPLE_STEP_DEG))
    return [(round(lat, 6), round(lon, 6)) for lat in lats for lon in lons]


def _heat_risk(lst_c: Optional[float], ndvi: Optional[float]) -> Optional[float]:
    if lst_c is None:
        return None
    lst_score = float(np.clip((lst_c - 25.0) / 20.0, 0.0, 1.0))
    if ndvi is not None:
        ndvi_score = float(1.0 - np.clip(ndvi, 0.0, 1.0))
        return round(0.7 * lst_score + 0.3 * ndvi_score, 4)
    return round(lst_score, 4)


def fetch_lst_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_days: int = 8,     # MODIS has ~1-day gap; 8 days ensures a clear pass
    project: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch LST + NDVI from GEE and return observations compatible with the
    heat pipeline's temperature_observation_feed contract.

    Parameters
    ----------
    city_name : str
        Used for logging.
    lat_min, lon_min, lat_max, lon_max : float
        City bounding box.
    lookback_days : int
        Days to look back for MODIS composite (default 8 to ensure a clear pass).
    project : str, optional
        GEE cloud project ID. If None, uses the authenticated default project.
    """
    empty = pd.DataFrame(columns=_COLUMNS)

    try:
        import ee
    except ImportError:
        logger.error("earthengine-api not installed — pip install earthengine-api")
        return empty

    try:
        try:
            ee.Initialize(project=project)
        except Exception:
            ee.Initialize()
    except Exception as exc:
        logger.error("GEE authentication failed: %s", exc)
        return empty

    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str   = end_dt.strftime("%Y-%m-%d")
    ts_label  = end_dt.strftime("%Y-%m-%dT%H:00:00Z")

    bbox = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

    # ── MODIS LST composite ────────────────────────────────────────────────
    try:
        lst_img = (
            ee.ImageCollection(_LST_COLLECTION)
            .filterDate(start_str, end_str)
            .filterBounds(bbox)
            .select(_LST_BAND)
            .mean()
            .multiply(_LST_SCALE)
            .add(_LST_OFFSET)
        )
    except Exception as exc:
        logger.error("GEE LST image build failed: %s", exc)
        return empty

    # ── Sentinel-2 NDVI composite ─────────────────────────────────────────
    try:
        def _add_ndvi(img):
            ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
            return img.addBands(ndvi)

        s2 = (
            ee.ImageCollection(_S2_COLLECTION)
            .filterDate(start_str, end_str)
            .filterBounds(bbox)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
            .map(_add_ndvi)
            .select("NDVI")
            .median()
        )
        has_ndvi = True
    except Exception as exc:
        logger.warning("GEE S2 NDVI build failed (continuing without): %s", exc)
        has_ndvi = False

    # ── Sample at grid points ─────────────────────────────────────────────
    points = _make_grid(lat_min, lon_min, lat_max, lon_max)
    if not points:
        logger.warning("GEE heat: empty grid for bbox")
        return empty

    # Build a FeatureCollection of sample points and extract values
    try:
        fc = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([lon, lat]), {"lat": lat, "lon": lon})
            for lat, lon in points
        ])

        combined = lst_img.rename("lst_c")
        if has_ndvi:
            combined = combined.addBands(s2.rename("ndvi"))

        sampled = combined.sampleRegions(
            collection=fc,
            scale=1000,        # 1 km — matches MODIS resolution
            geometries=True,
        )
        features = sampled.getInfo()["features"]
    except Exception as exc:
        logger.error("GEE sampling failed: %s", exc)
        return empty

    rows = []
    for feat in features:
        props = feat.get("properties", {})
        lat   = props.get("lat")
        lon   = props.get("lon")
        lst_c = props.get("lst_c")
        ndvi  = props.get("ndvi") if has_ndvi else None

        if lat is None or lon is None:
            continue

        rows.append({
            "station_id":              f"gee_lst_{round(lat, 4)}_{round(lon, 4)}",
            "latitude":                lat,
            "longitude":               lon,
            "timestamp":               ts_label,
            "temperature_c":           round(lst_c, 2) if lst_c is not None else None,
            "apparent_temperature_c":  None,   # not available from MODIS
            "relative_humidity_pct":   None,
            "lst_c":                   round(lst_c, 2) if lst_c is not None else None,
            "ndvi":                    round(ndvi, 4) if ndvi is not None else None,
            "heat_risk_score":         _heat_risk(lst_c, ndvi),
            "data_source":             "gee_modis_s2",
            "quality_flag":            "real",
        })

    if not rows:
        logger.warning("GEE heat: no usable samples returned for city '%s'", city_name)
        return empty

    df = pd.DataFrame(rows)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = None

    logger.info(
        "GEE heat: %d sample points for city '%s' (LST+%s)",
        len(df), city_name, "NDVI" if has_ndvi else "no NDVI",
    )
    return df[_COLUMNS]
