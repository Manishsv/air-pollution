from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests


logger = logging.getLogger(__name__)


def _utc_now_hour() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def fetch_open_meteo_hourly(
    *,
    latitude: float,
    longitude: float,
    lookback_days: int,
) -> pd.DataFrame:
    """
    Fetch hourly weather for the past lookback days using Open-Meteo archive API.
    Returns columns:
      timestamp, temperature_2m, relative_humidity_2m, wind_speed_10m,
      wind_direction_10m, precipitation, wind_direction_sin, wind_direction_cos
    """
    end = _utc_now_hour().date()
    start = (datetime.now(timezone.utc) - timedelta(days=int(lookback_days))).date()
    url = "https://archive-api.open-meteo.com/v1/archive"
    hourly = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": hourly,
        "timezone": "UTC",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        h = js.get("hourly") or {}
        t = h.get("time")
        if not t:
            return pd.DataFrame()
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(t, utc=True),
                "temperature_2m": h.get("temperature_2m"),
                "relative_humidity_2m": h.get("relative_humidity_2m"),
                "wind_speed_10m": h.get("wind_speed_10m"),
                "wind_direction_10m": h.get("wind_direction_10m"),
                "precipitation": h.get("precipitation"),
            }
        )
        df = df.dropna(subset=["timestamp"]).copy()
        df["wind_direction_10m"] = df["wind_direction_10m"].astype(float)
        rad = np.deg2rad(df["wind_direction_10m"].values)
        df["wind_direction_sin"] = np.sin(rad)
        df["wind_direction_cos"] = np.cos(rad)
        return df
    except Exception as e:
        logger.warning("Open-Meteo fetch failed: %s", e)
        return pd.DataFrame()


def generate_synthetic_weather(lookback_days: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = _utc_now_hour()
    start = end - timedelta(days=int(lookback_days))
    hours = pd.date_range(start=start, end=end, freq="H", tz="UTC")
    # Bengaluru-like ranges
    base_temp = 26 + 4 * np.sin(2 * np.pi * (hours.hour.values / 24.0) - 1.2)
    temp = base_temp + rng.normal(0, 0.8, size=len(hours))
    rh = np.clip(60 + 15 * np.cos(2 * np.pi * (hours.hour.values / 24.0)) + rng.normal(0, 5, size=len(hours)), 25, 95)
    wind = np.clip(2.2 + 1.5 * np.sin(2 * np.pi * (hours.hour.values / 24.0) - 0.2) + rng.normal(0, 0.6, size=len(hours)), 0.1, 10)
    wdir = (180 + 40 * np.sin(np.linspace(0, 2 * np.pi, len(hours))) + rng.normal(0, 25, size=len(hours))) % 360
    precip = np.clip(rng.gamma(0.6, 0.8, size=len(hours)) - 0.6, 0, None)
    rad = np.deg2rad(wdir)
    return pd.DataFrame(
        {
            "timestamp": hours,
            "temperature_2m": temp.astype(float),
            "relative_humidity_2m": rh.astype(float),
            "wind_speed_10m": wind.astype(float),
            "wind_direction_10m": wdir.astype(float),
            "precipitation": precip.astype(float),
            "wind_direction_sin": np.sin(rad).astype(float),
            "wind_direction_cos": np.cos(rad).astype(float),
        }
    )

