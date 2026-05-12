"""MODIS MOD11A1 Land Surface Temperature connector via NASA Earthdata.

Drop-in replacement for gee_lst.py — same output schema, no GEE dependency.

Data sources
------------
  LST   : MODIS MOD11A1 v6.1 (1 km, daily Terra overpass)
           Downloaded via earthaccess; read from HDF4 subdataset with rasterio.
  NDVI  : Sentinel-2 L2A via CDSE Sentinel Hub (when CDSE credentials are set).
           Falls back to None (heat_risk uses LST-only score) if unavailable.

Authentication
--------------
  EARTHDATA_TOKEN  — NASA Earthdata token from urs.earthdata.nasa.gov
                     (same token used for VIIRS night lights)

Heat risk formula (0–1)
-----------------------
  lst_score  = clip((lst_c − 25) / 20, 0, 1)    # 25°C → 0, 45°C → 1
  ndvi_score = 1 − clip(ndvi, 0, 1)             # high NDVI = lower risk
  heat_risk  = 0.7 × lst_score + 0.3 × ndvi_score
"""
from __future__ import annotations

import logging
import os
import tempfile
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

_LST_SCALE      = 0.02      # MODIS LST DN scale factor (K)
_LST_OFFSET     = -273.15   # K → °C
_SAMPLE_STEP    = 0.009     # ~1 km sampling grid


def _make_grid(lat_min, lon_min, lat_max, lon_max):
    lats = list(np.arange(lat_min, lat_max, _SAMPLE_STEP))
    lons = list(np.arange(lon_min, lon_max, _SAMPLE_STEP))
    return [(round(lat, 6), round(lon, 6)) for lat in lats for lon in lons]


def _heat_risk(lst_c: Optional[float], ndvi: Optional[float]) -> Optional[float]:
    if lst_c is None:
        return None
    lst_score = float(np.clip((lst_c - 25.0) / 20.0, 0.0, 1.0))
    if ndvi is not None:
        ndvi_score = float(1.0 - np.clip(ndvi, 0.0, 1.0))
        return round(0.7 * lst_score + 0.3 * ndvi_score, 4)
    return round(lst_score, 4)


def _fetch_ndvi_from_cdse(
    lat_min, lon_min, lat_max, lon_max,
    start: datetime, end: datetime,
) -> dict[tuple[float, float], float]:
    """Return {(lat, lon): ndvi} sampled on the same ~1km grid. Best-effort."""
    try:
        from airos.drivers.connectors.satellite.cdse_core import (
            get_credentials, get_token, fetch_tiff, sample_tiff,
        )
        import h3

        creds = get_credentials()
        if not creds:
            return {}

        evalscript = """
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
        cfg = {
            "type": "sentinel-2-l2a",
            "dataFilter": {
                "timeRange": {
                    "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "mosaickingOrder":  "leastCC",
                "maxCloudCoverage": 30,
            },
        }

        token = get_token(*creds)
        tiff  = fetch_tiff(token, [lon_min, lat_min, lon_max, lat_max], cfg, evalscript)
        if tiff is None:
            return {}

        # Build pseudo-h3 cells for the 1km grid to reuse sample_tiff
        # (sample_tiff expects h3 cells; we'll use direct rasterio sampling instead)
        import rasterio
        from rasterio.io import MemoryFile

        grid = _make_grid(lat_min, lon_min, lat_max, lon_max)
        coords = [(lon, lat) for lat, lon in grid]
        result: dict[tuple[float, float], float] = {}
        with MemoryFile(tiff) as mf, mf.open() as ds:
            for (lat, lon), vals in zip(grid, ds.sample(coords)):
                v = float(vals[0])
                if not np.isnan(v):
                    result[(lat, lon)] = round(v, 4)
        return result
    except Exception as exc:
        logger.debug("CDSE NDVI for heat failed (non-critical): %s", exc)
        return {}


def _fetch_modis_lst(
    lat_min, lon_min, lat_max, lon_max,
    start: datetime, end: datetime,
) -> dict[tuple[float, float], float]:
    """Download one MODIS MOD11A1 granule and return {(lat,lon): lst_celsius}."""
    try:
        import earthaccess
        import rasterio
    except ImportError:
        logger.error("earthaccess or rasterio not installed — pip install earthaccess rasterio")
        return {}

    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        return {}

    try:
        earthaccess.login(strategy="environment")

        results = earthaccess.search_data(
            short_name="MOD11A1",
            version="061",
            bounding_box=(lon_min, lat_min, lon_max, lat_max),
            temporal=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            count=3,
        )
        if not results:
            logger.debug("No MODIS MOD11A1 granules found for bbox/window")
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            files = earthaccess.download(results[:1], local_path=tmp)
            if not files:
                return {}

            local_file = files[0]
            subdataset = (
                f"HDF4_EOS:EOS_GRID:{local_file}"
                f":MODIS_Grid_Daily_1km_LST:LST_Day_1km"
            )

            grid   = _make_grid(lat_min, lon_min, lat_max, lon_max)
            coords = [(lon, lat) for lat, lon in grid]
            out: dict[tuple[float, float], float] = {}

            with rasterio.open(subdataset) as src:
                for (lat, lon), vals in zip(grid, src.sample(coords)):
                    raw = float(vals[0])
                    if raw == 0 or raw == 65535:   # MODIS fill values
                        continue
                    lst_c = raw * _LST_SCALE + _LST_OFFSET
                    if 10 <= lst_c <= 70:           # plausible range
                        out[(lat, lon)] = round(lst_c, 2)

            logger.info("MODIS LST: sampled %d grid points", len(out))
            return out

    except Exception as exc:
        logger.warning("MODIS LST fetch failed: %s", exc)
        return {}


def fetch_lst_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_days: int = 8,
    project: str | None = None,   # unused — kept for signature compatibility
) -> pd.DataFrame:
    """Fetch MODIS LST + optional CDSE NDVI for a city bbox.

    Returns a DataFrame with columns matching the heat pipeline's
    temperature_observation_feed contract. Returns empty DataFrame if
    EARTHDATA_TOKEN is unset or no granules are available.
    """
    empty = pd.DataFrame(columns=_COLUMNS)

    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        logger.debug("EARTHDATA_TOKEN not set — skipping MODIS LST fetch")
        return empty

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)
    ts    = now.strftime("%Y-%m-%dT%H:00:00Z")

    lst_map  = _fetch_modis_lst(lat_min, lon_min, lat_max, lon_max, start, now)
    if not lst_map:
        return empty

    ndvi_map = _fetch_ndvi_from_cdse(lat_min, lon_min, lat_max, lon_max, start, now)

    rows = []
    for (lat, lon), lst_c in lst_map.items():
        ndvi = ndvi_map.get((lat, lon))
        rows.append({
            "station_id":             f"modis_lst_{round(lat,4)}_{round(lon,4)}",
            "latitude":               lat,
            "longitude":              lon,
            "timestamp":              ts,
            "temperature_c":          lst_c,
            "apparent_temperature_c": None,
            "relative_humidity_pct":  None,
            "lst_c":                  lst_c,
            "ndvi":                   ndvi,
            "heat_risk_score":        _heat_risk(lst_c, ndvi),
            "data_source":            "modis_lst" + ("_cdse_ndvi" if ndvi is not None else ""),
            "quality_flag":           "real",
        })

    if not rows:
        return empty

    df = pd.DataFrame(rows)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = None

    logger.info(
        "MODIS LST (%s): %d points, max LST %.1f°C",
        city_name, len(df),
        df["lst_c"].max() or 0,
    )
    return df[_COLUMNS]
