"""
OpenMeteo Air Quality connector.

Fetches hourly PM2.5, PM10, and European AQI for a 3×3 grid of points
spanning a city bounding box. No API key required.

Returns a DataFrame matching the air_quality_observation_feed provider contract.
"""
from __future__ import annotations
import logging
from typing import Optional
import pandas as pd
import requests

logger = logging.getLogger(__name__)

_AQ_API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "pm25_ugm3", "pm10_ugm3", "european_aqi",
    "data_source", "quality_flag",
]


def _grid_points(lat_min, lon_min, lat_max, lon_max, n=3):
    lats = [lat_min + i * (lat_max - lat_min) / (n - 1) for i in range(n)]
    lons = [lon_min + i * (lon_max - lon_min) / (n - 1) for i in range(n)]
    return [(round(lat, 5), round(lon, 5)) for lat in lats for lon in lons]


def _fetch_point(lat, lon, lookback_hours=24, session=None):
    """Fetch latest AQ reading for one grid point. Returns [] on error."""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "pm2_5,pm10,european_aqi",
        "past_days": max(1, lookback_hours // 24),
        "forecast_days": 0,
        "timezone": "UTC",
    }
    try:
        http = session or requests
        resp = http.get(_AQ_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("OpenMeteo AQ fetch failed (%s, %s): %s", lat, lon, exc)
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    pm25_vals = hourly.get("pm2_5", [])
    pm10_vals = hourly.get("pm10", [])
    eaqi_vals = hourly.get("european_aqi", [])

    if not times:
        return []

    # Take lookback_hours worth of readings, use latest non-null pm25 as intensity
    n_look = min(lookback_hours, len(times))
    recent_pm25 = [v for v in pm25_vals[-n_look:] if v is not None]
    recent_pm10 = [v for v in pm10_vals[-n_look:] if v is not None]
    recent_eaqi = [v for v in eaqi_vals[-n_look:] if v is not None]

    pm25 = recent_pm25[-1] if recent_pm25 else None
    pm10 = recent_pm10[-1] if recent_pm10 else None
    eaqi = recent_eaqi[-1] if recent_eaqi else None

    if pm25 is None and pm10 is None:
        return []

    return [{
        "station_id": f"openmeteo_aq_{lat}_{lon}",
        "latitude": lat,
        "longitude": lon,
        "timestamp": (times[-1] if times[-1].endswith("Z") else times[-1] + ":00Z"),
        "pm25_ugm3": pm25,
        "pm10_ugm3": pm10,
        "european_aqi": eaqi,
        "data_source": "openmeteo_aq",
        "quality_flag": "real",
    }]


def fetch_air_quality_observations(
    city_name: str,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    lookback_hours: int = 24,
    session=None,
) -> pd.DataFrame:
    """
    Fetch PM2.5/PM10/AQI for a 3×3 grid over the bounding box.
    Returns empty DataFrame (with correct columns) on complete failure.
    """
    points = _grid_points(lat_min, lon_min, lat_max, lon_max)
    rows = []
    for lat, lon in points:
        rows.extend(_fetch_point(lat, lon, lookback_hours=lookback_hours, session=session))

    if not rows:
        return pd.DataFrame(columns=_COLUMNS)

    df = pd.DataFrame(rows)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[_COLUMNS]
