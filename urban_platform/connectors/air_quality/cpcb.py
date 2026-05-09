"""
CPCB real-time AQI connector (data.gov.in).

Fetches PM2.5, PM10, NO2, SO2, CO, O3 readings from CPCB monitoring stations
for a given city. API key is read from the CPCB_API_KEY environment variable.

Returns a DataFrame matching the air_quality_observation_feed provider contract —
same columns as openmeteo_aq.py so the air pipeline can use either connector.

Resource ID: 3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69
"""
from __future__ import annotations

import logging
import os

import json
import subprocess

import pandas as pd

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
_PAGE_LIMIT = 500

# CPCB uses inconsistent city spellings; map canonical names → CPCB names to try
_CITY_ALIASES: dict[str, list[str]] = {
    "bangalore":  ["Bengaluru", "Bangalore", "Bengaluru City"],
    "delhi":      ["Delhi", "New Delhi"],
    "mumbai":     ["Mumbai", "Navi Mumbai"],
    "hyderabad":  ["Hyderabad"],
    "chennai":    ["Chennai"],
    "kolkata":    ["Kolkata"],
    "pune":       ["Pune"],
}

# Columns we emit (matches openmeteo_aq.py output)
_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "pm25_ugm3", "pm10_ugm3", "european_aqi",
    "data_source", "quality_flag",
]

# Indian AQI sub-index for PM2.5 (µg/m³) breakpoints — CPCB 2014 standard
_PM25_BREAKPOINTS = [
    (0,   30,   0,   50),
    (30,  60,   51,  100),
    (60,  90,   101, 200),
    (90,  120,  201, 300),
    (120, 250,  301, 400),
    (250, 500,  401, 500),
]


def _pm25_to_aqi(pm25: float) -> float:
    """Convert PM2.5 (µg/m³) to Indian AQI sub-index (0–500)."""
    for c_lo, c_hi, i_lo, i_hi in _PM25_BREAKPOINTS:
        if c_lo <= pm25 <= c_hi:
            return i_lo + (pm25 - c_lo) * (i_hi - i_lo) / (c_hi - c_lo)
    return 500.0


def _curl_get(url: str, params: dict) -> dict:
    """Use curl (IPv4-forced) to bypass Python SSL/IPv6 issues with api.data.gov.in."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"
    result = subprocess.run(
        ["curl", "-s", "--max-time", "20", "-4", full_url],
        capture_output=True, text=True, timeout=25,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _fetch_page(offset: int, api_key: str) -> dict:
    return _curl_get(_BASE_URL, {
        "api-key": api_key,
        "format":  "json",
        "limit":   _PAGE_LIMIT,
        "offset":  offset,
    })


def _fetch_all_records(city_name: str, api_key: str, session=None) -> list[dict]:
    """Fetch all CPCB records via curl (bypasses IPv6 timeout), filter client-side."""
    aliases = {a.lower() for a in _CITY_ALIASES.get(city_name.lower(), [city_name])}

    try:
        first = _fetch_page(0, api_key)
        total = int(first.get("total", 0))
        records = list(first.get("records", []))

        offset = _PAGE_LIMIT
        while offset < total:
            page = _fetch_page(offset, api_key)
            records.extend(page.get("records", []))
            offset += _PAGE_LIMIT

        matched = [r for r in records if (r.get("city") or "").strip().lower() in aliases]
        logger.info("CPCB: fetched %d total, %d matched for city '%s'", len(records), len(matched), city_name)
        return matched

    except Exception as exc:
        logger.warning("CPCB fetch failed: %s", exc)
        return []


def _pivot_to_stations(records: list[dict]) -> pd.DataFrame:
    """
    Pivot from one-row-per-pollutant to one-row-per-station with pollutant columns.
    Keeps only stations that have lat/lon and at least PM2.5 or PM10.
    """
    rows: dict[str, dict] = {}

    for r in records:
        station = r.get("station", "")
        if not station:
            continue

        lat_str = r.get("latitude", "")
        lon_str = r.get("longitude", "")
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except (TypeError, ValueError):
            continue

        if station not in rows:
            rows[station] = {
                "station_id":  f"cpcb_{station.lower().replace(' ', '_').replace(',', '')}",
                "station_name": station,
                "latitude":    lat,
                "longitude":   lon,
                "timestamp":   r.get("last_update", ""),
                "pm25_ugm3":   None,
                "pm10_ugm3":   None,
                "no2_ugm3":    None,
                "so2_ugm3":    None,
                "co_mgm3":     None,
                "o3_ugm3":     None,
            }

        pollutant = (r.get("pollutant_id") or "").strip().upper()
        try:
            avg = float(r.get("avg_value", "") or "")
        except (TypeError, ValueError):
            avg = None

        if pollutant == "PM2.5":
            rows[station]["pm25_ugm3"] = avg
        elif pollutant == "PM10":
            rows[station]["pm10_ugm3"] = avg
        elif pollutant == "NO2":
            rows[station]["no2_ugm3"] = avg
        elif pollutant == "SO2":
            rows[station]["so2_ugm3"] = avg
        elif pollutant in ("CO", "CO (mg/m3)"):
            rows[station]["co_mgm3"] = avg
        elif pollutant in ("OZONE", "O3"):
            rows[station]["o3_ugm3"] = avg

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows.values())
    # Keep only stations with at least one concentration value
    return df[df["pm25_ugm3"].notna() | df["pm10_ugm3"].notna()].copy()


def fetch_air_quality_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 24,   # unused — CPCB returns current hourly snapshot
    session=None,
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch real-time AQI observations from CPCB for a city.

    Stations outside the bounding box are filtered out. Returns a DataFrame
    with columns matching the air_quality_observation_feed contract. Returns
    an empty DataFrame (correct columns) on any failure.

    Parameters
    ----------
    city_name : str
        Canonical city name — see _CITY_ALIASES for supported values.
    lat_min, lon_min, lat_max, lon_max : float
        Bounding box; stations outside are dropped.
    lookback_hours : int
        Accepted for API compatibility; CPCB returns current snapshot only.
    session : requests.Session, optional
        Injectable for testing.
    api_key : str, optional
        Override; defaults to CPCB_API_KEY environment variable.
    """
    empty = pd.DataFrame(columns=_COLUMNS)

    key = api_key or os.environ.get("CPCB_API_KEY", "")
    if not key:
        logger.error("CPCB_API_KEY not set — skipping CPCB connector")
        return empty

    http = session  # kept for test injection; production uses curl internally
    records = _fetch_all_records(city_name, key, http)
    if not records:
        logger.warning("CPCB: no records returned for city '%s'", city_name)
        return empty

    stations = _pivot_to_stations(records)
    if stations.empty:
        return empty

    # Filter to bounding box
    in_bbox = (
        stations["latitude"].between(lat_min, lat_max) &
        stations["longitude"].between(lon_min, lon_max)
    )
    stations = stations[in_bbox].copy()
    if stations.empty:
        logger.warning("CPCB: no stations within bbox for city '%s'", city_name)
        return empty

    # Compute Indian AQI from PM2.5 (fall back to PM10-proxy if PM2.5 missing)
    def _aqi(row):
        if row["pm25_ugm3"] is not None:
            return round(_pm25_to_aqi(row["pm25_ugm3"]), 1)
        if row["pm10_ugm3"] is not None:
            # PM10 rough proxy: AQI ≈ PM10 / 2
            return round(min(row["pm10_ugm3"] / 2.0, 500), 1)
        return None

    stations["european_aqi"] = stations.apply(_aqi, axis=1)
    stations["data_source"]  = "cpcb"
    stations["quality_flag"] = "real"

    out = stations.rename(columns={})[
        ["station_id", "latitude", "longitude", "timestamp",
         "pm25_ugm3", "pm10_ugm3", "european_aqi",
         "data_source", "quality_flag"]
    ].copy()

    logger.info(
        "CPCB: %d stations within bbox for city '%s'",
        len(out), city_name,
    )
    return out
