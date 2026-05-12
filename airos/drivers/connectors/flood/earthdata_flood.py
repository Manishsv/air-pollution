"""GPM IMERG precipitation connector via NASA Earthdata.

Drop-in replacement for gee_precipitation.py — same output schema, no GEE dependency.

Data sources
------------
  Rainfall : NASA GPM GPM_3IMERGHH v07 (0.1°, half-hourly)
             Downloaded via earthaccess; read from HDF5 Grid/precipitationCal.
  Elevation: Open-Elevation API (SRTM 90m) — best-effort; defaults to 0 if unavailable.
  JRC Water: Omitted (static layer; high-rain + low-elevation sufficient proxy).

Authentication
--------------
  EARTHDATA_TOKEN  — NASA Earthdata token from urs.earthdata.nasa.gov

Flood risk formula (0–1)
------------------------
  rain_score    = clip(accum_mm / 50, 0, 1)     # 0 mm → 0, ≥50 mm → 1
  terrain_score = clip(1 - elev_m / 200, 0, 1)  # sea level → 1, ≥200 m → 0
  flood_risk    = 0.6 × rain_score + 0.4 × terrain_score
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm",
    "elevation_m", "jrc_water_occurrence",
    "flood_risk_score", "data_source", "quality_flag",
]

_SAMPLE_STEP = 0.1   # match GPM 0.1° native resolution


def _make_grid(lat_min, lon_min, lat_max, lon_max):
    lats = list(np.arange(lat_min, lat_max + _SAMPLE_STEP, _SAMPLE_STEP))
    lons = list(np.arange(lon_min, lon_max + _SAMPLE_STEP, _SAMPLE_STEP))
    return [(round(lat, 4), round(lon, 4)) for lat in lats for lon in lons]


def _flood_risk(accum_mm: float, elev_m: float) -> float:
    rain_score    = float(np.clip(accum_mm / 50.0, 0.0, 1.0))
    terrain_score = float(np.clip(1.0 - elev_m / 200.0, 0.0, 1.0))
    return round(0.6 * rain_score + 0.4 * terrain_score, 4)


def _fetch_elevations(points: list[tuple[float, float]]) -> dict[tuple[float, float], float]:
    """Query Open-Elevation for a batch of (lat, lon) points. Best-effort."""
    try:
        import requests
        payload = {"locations": [{"latitude": lat, "longitude": lon} for lat, lon in points]}
        resp = requests.post(
            "https://api.open-elevation.com/api/v1/lookup",
            json=payload,
            timeout=15,
        )
        if resp.status_code != 200:
            return {}
        results = resp.json().get("results", [])
        return {
            (round(r["latitude"], 4), round(r["longitude"], 4)): max(0.0, float(r["elevation"]))
            for r in results
        }
    except Exception as exc:
        logger.debug("Open-Elevation query failed (non-critical): %s", exc)
        return {}


def _fetch_gpm_imerg(
    lat_min, lon_min, lat_max, lon_max,
    start: datetime, end: datetime,
    lookback_hours: int,
) -> dict[tuple[float, float], dict]:
    """Download GPM_3IMERGHH granules and return {(lat,lon): {intensity, accum}} ."""
    try:
        import earthaccess
        import h5py
    except ImportError:
        logger.error("earthaccess or h5py not installed — pip install earthaccess h5py")
        return {}

    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        return {}

    try:
        earthaccess.login(strategy="environment")

        # Request enough granules to cover the lookback window (half-hourly → 2/hr)
        n_granules = max(1, lookback_hours * 2)
        results = earthaccess.search_data(
            short_name="GPM_3IMERGHH",
            version="07",
            bounding_box=(lon_min, lat_min, lon_max, lat_max),
            temporal=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            count=n_granules,
        )
        if not results:
            logger.debug("No GPM IMERG granules found for bbox/window")
            return {}

        grid = _make_grid(lat_min, lon_min, lat_max, lon_max)

        # Accumulate precipitation across all downloaded granules
        accum: dict[tuple[float, float], list[float]] = {pt: [] for pt in grid}

        files = earthaccess.open(results)
        for fobj in files:
            try:
                with h5py.File(fobj, "r") as f:
                    precip = f["Grid"]["precipitationCal"][0]   # shape (lon, lat) after squeeze
                    lons_arr = f["Grid"]["lon"][:]
                    lats_arr = f["Grid"]["lat"][:]

                    # Find nearest grid cell for each sample point
                    for (lat, lon) in grid:
                        i_lat = int(np.argmin(np.abs(lats_arr - lat)))
                        i_lon = int(np.argmin(np.abs(lons_arr - lon)))
                        val = float(precip[i_lon, i_lat])
                        if not np.isnan(val) and val >= 0:
                            accum[(lat, lon)].append(val)
            except Exception as exc:
                logger.debug("GPM granule read error (skipped): %s", exc)

        # Convert to output: intensity = mean half-hour rate (mm/hr), accum = sum × 0.5 hr
        out: dict[tuple[float, float], dict] = {}
        for pt, vals in accum.items():
            if not vals:
                continue
            intensity = round(float(np.mean(vals)), 3)
            total     = round(float(np.sum(vals)) * 0.5, 3)  # each half-hour in mm/hr → mm
            out[pt] = {"intensity": intensity, "accum": total}

        logger.info("GPM IMERG: %d grid points with rain data", len(out))
        return out

    except Exception as exc:
        logger.warning("GPM IMERG fetch failed: %s", exc)
        return {}


def fetch_rainfall_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 3,
    project: str | None = None,   # unused — kept for signature compatibility
) -> pd.DataFrame:
    """Fetch GPM IMERG precipitation + Open-Elevation terrain for a city bbox.

    Returns a DataFrame matching the flood pipeline's rainfall_observation_feed
    contract. Returns empty DataFrame if EARTHDATA_TOKEN is unset or no
    granules are available.
    """
    empty = pd.DataFrame(columns=_COLUMNS)

    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        logger.debug("EARTHDATA_TOKEN not set — skipping GPM IMERG fetch")
        return empty

    now   = datetime.now(timezone.utc)
    start = now - timedelta(hours=lookback_hours + 1)  # +1 for granule boundary
    ts    = now.strftime("%Y-%m-%dT%H:00:00Z")

    rain_map = _fetch_gpm_imerg(lat_min, lon_min, lat_max, lon_max, start, now, lookback_hours)
    if not rain_map:
        return empty

    # Elevation — query only the points that have rain data
    pts      = list(rain_map.keys())
    elev_map = _fetch_elevations(pts)

    rows = []
    for (lat, lon), rain in rain_map.items():
        elev = elev_map.get((lat, lon), 0.0)
        rows.append({
            "station_id":                  f"gpm_imerg_{lat}_{lon}",
            "latitude":                    lat,
            "longitude":                   lon,
            "timestamp":                   ts,
            "rainfall_intensity_mm_per_hr": rain["intensity"],
            "rainfall_accumulation_3h_mm":  rain["accum"],
            "elevation_m":                 elev,
            "jrc_water_occurrence":        None,
            "flood_risk_score":            _flood_risk(rain["accum"], elev),
            "data_source":                 "gpm_imerg_earthdata",
            "quality_flag":                "real",
        })

    if not rows:
        return empty

    df = pd.DataFrame(rows)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = None

    logger.info(
        "GPM IMERG (%s): %d points, max accum %.1f mm",
        city_name, len(df),
        df["rainfall_accumulation_3h_mm"].max() or 0,
    )
    return df[_COLUMNS]
