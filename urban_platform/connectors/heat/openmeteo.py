"""
OpenMeteo connector for urban heat risk temperature observations.

Fetches hourly temperature_2m, apparent_temperature, and relative_humidity_2m
for a 3x3 grid of points spanning a city bounding box. Returns a DataFrame
matching the temperature_observation_feed provider contract.

No API key required — OpenMeteo is free and keyless.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_API_URL = "https://api.open-meteo.com/v1/forecast"
_VARIABLES = "temperature_2m,apparent_temperature,relative_humidity_2m"
_HOURLY = "hourly"


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
    lookback_days: int,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """Fetch hourly records for one grid point. Returns empty list on any error."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": _VARIABLES,
        "past_days": lookback_days,
        "forecast_days": 0,
        "timezone": "UTC",
    }
    try:
        http = session or requests
        resp = http.get(_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("OpenMeteo fetch failed for (%s, %s): %s", lat, lon, exc)
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    app_temps = hourly.get("apparent_temperature", [])
    humidities = hourly.get("relative_humidity_2m", [])

    records = []
    station_id = f"openmeteo_{lat}_{lon}"
    for i, ts in enumerate(times):
        records.append({
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "timestamp": ts if ts.endswith("Z") else ts + ":00Z",
            "temperature_c": temps[i] if i < len(temps) else None,
            "apparent_temperature_c": app_temps[i] if i < len(app_temps) else None,
            "relative_humidity_pct": float(humidities[i]) if i < len(humidities) and humidities[i] is not None else None,
            "data_source": "openmeteo",
            "quality_flag": "real",
        })
    return records


def fetch_temperature_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_days: int = 1,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Fetch temperature observations for a city bounding box from OpenMeteo.

    Samples a 3×3 grid of points across the bbox. Returns a DataFrame with
    columns matching the temperature_observation_feed provider contract.
    On any network or parse error, returns an empty DataFrame (no exception raised).

    Parameters
    ----------
    city_name : str
        Used for logging context only.
    lat_min, lon_min, lat_max, lon_max : float
        Bounding box coordinates.
    lookback_days : int
        Number of past days to fetch (default 1).
    session : requests.Session, optional
        Injectable for testing.
    """
    columns = [
        "station_id", "latitude", "longitude", "timestamp",
        "temperature_c", "apparent_temperature_c", "relative_humidity_pct",
        "data_source", "quality_flag",
    ]
    empty = pd.DataFrame(columns=columns)

    points = _grid_points(lat_min, lon_min, lat_max, lon_max)
    all_records: list[dict] = []

    for lat, lon in points:
        records = _fetch_point(lat, lon, lookback_days, session=session)
        all_records.extend(records)

    if not all_records:
        logger.warning("OpenMeteo returned no records for city '%s'", city_name)
        return empty

    df = pd.DataFrame(all_records, columns=columns)
    logger.info(
        "OpenMeteo fetched %d records for city '%s' (%d grid points)",
        len(df), city_name, len(points),
    )
    return df
