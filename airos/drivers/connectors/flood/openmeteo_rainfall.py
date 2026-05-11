"""
OpenMeteo connector for flood risk rainfall observations.

Fetches hourly precipitation for a 3×3 grid of points spanning a city
bounding box. Returns a DataFrame compatible with the pipeline's rainfall
input.  No API key required — OpenMeteo is free and keyless.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_API_URL = "https://api.open-meteo.com/v1/forecast"
_VARIABLES = "precipitation,rain"

_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm",
    "data_source", "quality_flag",
]


def _grid_points(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    n: int = 3,
) -> list[tuple[float, float]]:
    """Return an n×n grid of (lat, lon) points spanning the bounding box."""
    lats = [lat_min + i * (lat_max - lat_min) / (n - 1) for i in range(n)]
    lons = [lon_min + i * (lon_max - lon_min) / (n - 1) for i in range(n)]
    return [(round(lat, 5), round(lon, 5)) for lat in lats for lon in lons]


def _fetch_point(
    lat: float,
    lon: float,
    lookback_hours: int,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Fetch latest rainfall for one grid point.  Returns empty list on any error.

    OpenMeteo returns hourly precipitation in mm.  We report the most recent
    hour's value as rainfall_intensity_mm_per_hr and sum the last N hours for
    the 3-hour accumulation threshold used in the flood domain spec.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": _VARIABLES,
        "past_days": 1,
        "forecast_days": 0,
        "timezone": "UTC",
    }
    try:
        http = session or requests
        resp = http.get(_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("OpenMeteo rainfall fetch failed (%s, %s): %s", lat, lon, exc)
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])

    # Keep only non-null records; take last `lookback_hours` entries
    valid = [(t, p) for t, p in zip(times, precip) if p is not None]
    if not valid:
        return []

    recent = valid[-lookback_hours:]
    latest_ts, latest_mm = recent[-1]
    accum_3h = sum(p for _, p in recent[-3:])

    return [{
        "station_id": f"openmeteo_{lat}_{lon}",
        "latitude": lat,
        "longitude": lon,
        "timestamp": latest_ts if latest_ts.endswith("Z") else latest_ts + ":00Z",
        "rainfall_intensity_mm_per_hr": round(latest_mm, 2),
        "rainfall_accumulation_3h_mm": round(accum_3h, 2),
        "data_source": "openmeteo",
        "quality_flag": "real",
    }]


def fetch_rainfall_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 3,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Fetch rainfall observations for a city bounding box from OpenMeteo.

    Samples a 3×3 grid across the bbox (same pattern as the temperature
    connector).  Returns a DataFrame with one row per grid point, or an
    empty DataFrame on any network or parse failure.

    Parameters
    ----------
    city_name : str
        Used for logging context only.
    lat_min, lon_min, lat_max, lon_max : float
        Bounding box coordinates.
    lookback_hours : int
        How many trailing hours to include in the 3h accumulation window.
    session : requests.Session, optional
        Injectable HTTP session for testing.
    """
    empty = pd.DataFrame(columns=_COLUMNS)
    points = _grid_points(lat_min, lon_min, lat_max, lon_max)
    all_records: list[dict] = []

    for lat, lon in points:
        all_records.extend(_fetch_point(lat, lon, lookback_hours, session=session))

    if not all_records:
        logger.warning("OpenMeteo rainfall: no records for city '%s'", city_name)
        return empty

    df = pd.DataFrame(all_records, columns=_COLUMNS)
    logger.info(
        "OpenMeteo rainfall: %d records for city '%s' (%d grid points)",
        len(df), city_name, len(points),
    )
    return df
