"""
OpenMeteo forecast connector — weather + air quality, next 48 h.

No API key required.  Two endpoints:
  - https://api.open-meteo.com/v1/forecast       — weather
  - https://air-quality-api.open-meteo.com/v1/air-quality  — AQ (forecast_days=2)

Returns a compact dict suitable for injecting into the H3 Expert Agent context.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds

# Compass rose — 16 points, each covers 22.5°
_COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _deg_to_compass(deg: float) -> str:
    idx = round(deg / 22.5) % 16
    return _COMPASS[idx]


def _bucket_hours(times: list[str], values: list[float | None], bucket_h: int = 6) -> list[dict]:
    """Aggregate hourly values into N-hour buckets from now."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets: dict[int, list[float]] = {}
    for t_str, v in zip(times, values):
        if v is None:
            continue
        try:
            # OpenMeteo returns ISO strings like "2026-05-10T12:00"
            t = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta_h = (t - now).total_seconds() / 3600
        if delta_h < 0 or delta_h > 48:
            continue
        bucket_idx = int(delta_h // bucket_h) * bucket_h
        buckets.setdefault(bucket_idx, []).append(v)

    result = []
    for start_h in sorted(buckets):
        vals = buckets[start_h]
        result.append({
            "offset_h": start_h,
            "label": f"+{start_h}h–+{start_h + bucket_h}h",
            "mean": round(sum(vals) / len(vals), 2),
            "max": round(max(vals), 2),
            "n": len(vals),
        })
    return result


def _bucket_wind(times: list[str], speeds: list[float | None],
                 dirs: list[float | None], bucket_h: int = 6) -> list[dict]:
    """Aggregate wind speed + direction into buckets."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets: dict[int, list[tuple[float, float]]] = {}
    for t_str, spd, d in zip(times, speeds, dirs):
        if spd is None or d is None:
            continue
        try:
            t = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta_h = (t - now).total_seconds() / 3600
        if delta_h < 0 or delta_h > 48:
            continue
        bucket_idx = int(delta_h // bucket_h) * bucket_h
        buckets.setdefault(bucket_idx, []).append((spd, d))

    result = []
    for start_h in sorted(buckets):
        pairs = buckets[start_h]
        speeds_b = [p[0] for p in pairs]
        # Vector-average direction
        import math
        sin_sum = sum(math.sin(math.radians(p[1])) for p in pairs)
        cos_sum = sum(math.cos(math.radians(p[1])) for p in pairs)
        avg_dir = math.degrees(math.atan2(sin_sum / len(pairs), cos_sum / len(pairs))) % 360
        result.append({
            "offset_h": start_h,
            "label": f"+{start_h}h–+{start_h + bucket_h}h",
            "speed_mean": round(sum(speeds_b) / len(speeds_b), 1),
            "speed_max": round(max(speeds_b), 1),
            "direction_deg": round(avg_dir),
            "direction_compass": _deg_to_compass(avg_dir),
        })
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_weather_forecast(lat: float, lon: float, hours: int = 48) -> dict[str, Any]:
    """
    Fetch weather forecast for the next `hours` hours at (lat, lon).
    Returns a dict with keys: wind, precipitation, temperature, humidity.
    Each value is a list of 6-hour-bucket dicts.
    Returns {} on any failure (non-blocking).
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "wind_direction_10m",
            "precipitation_probability",
            "precipitation",
        ]),
        "forecast_days": max(2, hours // 24 + 1),
        "timezone": "UTC",
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        h = data.get("hourly", {})
        times = h.get("time", [])
        return {
            "wind": _bucket_wind(
                times,
                h.get("wind_speed_10m", []),
                h.get("wind_direction_10m", []),
            ),
            "precipitation_prob": _bucket_hours(times, h.get("precipitation_probability", [])),
            "precipitation_mm": _bucket_hours(times, h.get("precipitation", [])),
            "temperature_c": _bucket_hours(times, h.get("temperature_2m", [])),
            "humidity_pct": _bucket_hours(times, h.get("relative_humidity_2m", [])),
        }
    except Exception as exc:
        logger.debug("Weather forecast fetch failed: %s", exc)
        return {}


def fetch_aq_forecast(lat: float, lon: float, hours: int = 48) -> dict[str, Any]:
    """
    Fetch AQ forecast for the next `hours` hours at (lat, lon).
    Returns a dict with keys: pm2_5, pm10, ozone, no2.
    Each value is a list of 6-hour-bucket dicts.
    Returns {} on any failure (non-blocking).
    """
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pm2_5,pm10,ozone,nitrogen_dioxide",
        "forecast_days": max(2, hours // 24 + 1),
        "timezone": "UTC",
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        h = data.get("hourly", {})
        times = h.get("time", [])
        result = {}
        for key in ("pm2_5", "pm10", "ozone", "nitrogen_dioxide"):
            vals = h.get(key, [])
            if any(v is not None for v in vals):
                result[key] = _bucket_hours(times, vals)
        return result
    except Exception as exc:
        logger.debug("AQ forecast fetch failed: %s", exc)
        return {}


def fetch_cell_forecast(lat: float, lon: float, hours: int = 48) -> dict[str, Any]:
    """
    Convenience wrapper — fetches both weather and AQ forecast for an H3 cell centroid.
    Returns {"weather": {...}, "aq": {...}} — either sub-dict may be empty on failure.
    """
    return {
        "weather": fetch_weather_forecast(lat, lon, hours),
        "aq": fetch_aq_forecast(lat, lon, hours),
    }
