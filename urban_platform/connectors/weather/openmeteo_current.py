"""Open-Meteo Forecast API — current weather conditions.

Fetches the most recent hourly observation for a lat/lon point:
  - temperature_2m        (°C)
  - relative_humidity_2m  (%)
  - wind_speed_10m        (km/h)
  - wind_direction_10m    (degrees, 0=N 90=E 180=S 270=W)
  - surface_pressure      (hPa)
  - precipitation         (mm in the last hour)

No API key required. Free-tier rate limit is generous for city-centroid polling.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_CURRENT_VARS = (
    "temperature_2m,"
    "relative_humidity_2m,"
    "wind_speed_10m,"
    "wind_direction_10m,"
    "surface_pressure,"
    "precipitation"
)


def fetch_current_weather(
    latitude: float,
    longitude: float,
    *,
    timeout: int = 20,
) -> dict[str, Any]:
    """Return the latest-available hourly weather snapshot for a lat/lon.

    Returns a dict with keys:
        observed_at       ISO-8601 UTC string of the reading
        temperature_c     float | None
        humidity_pct      float | None
        wind_speed_kmh    float | None
        wind_direction_deg float | None  (0–360, meteorological)
        pressure_hpa      float | None
        precipitation_mm  float | None
        source            "openmeteo_forecast"
    """
    params = {
        "latitude":  latitude,
        "longitude": longitude,
        "current":   _CURRENT_VARS,
        "timezone":  "UTC",
    }
    try:
        r = requests.get(_FORECAST_URL, params=params, timeout=timeout)
        r.raise_for_status()
        js = r.json()
        cur = js.get("current") or {}

        ts_raw = cur.get("time")
        if ts_raw:
            # Open-Meteo returns "2024-01-15T12:00" — append Z for UTC
            observed_at = ts_raw.replace(" ", "T")
            if not observed_at.endswith("Z"):
                observed_at += "Z"
        else:
            observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "observed_at":       observed_at,
            "temperature_c":     _safe_float(cur.get("temperature_2m")),
            "humidity_pct":      _safe_float(cur.get("relative_humidity_2m")),
            "wind_speed_kmh":    _safe_float(cur.get("wind_speed_10m")),
            "wind_direction_deg":_safe_float(cur.get("wind_direction_10m")),
            "pressure_hpa":      _safe_float(cur.get("surface_pressure")),
            "precipitation_mm":  _safe_float(cur.get("precipitation")),
            "source":            "openmeteo_forecast",
        }

    except Exception as exc:
        logger.warning("Open-Meteo current-weather fetch failed (%.4f, %.4f): %s",
                       latitude, longitude, exc)
        return {
            "observed_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temperature_c":      None,
            "humidity_pct":       None,
            "wind_speed_kmh":     None,
            "wind_direction_deg": None,
            "pressure_hpa":       None,
            "precipitation_mm":   None,
            "source":             "openmeteo_forecast",
            "error":              str(exc),
        }


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
