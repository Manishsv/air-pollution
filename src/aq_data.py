from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import requests
import h3


logger = logging.getLogger(__name__)


def _utc_now_hour() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _date_range_hours(end_utc: datetime, lookback_days: int) -> pd.DatetimeIndex:
    start = end_utc - timedelta(days=int(lookback_days))
    return pd.date_range(start=start, end=end_utc, freq="H", tz="UTC")


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def fetch_openaq_pm25(city_name: str, lookback_days: int) -> pd.DataFrame:
    """
    Best-effort OpenAQ fetch. Returns station-hourly records with:
      station_id, station_name, latitude, longitude, timestamp, pm25, data_source
    """
    end = _utc_now_hour()
    start = end - timedelta(days=int(lookback_days))

    # OpenAQ v2 historically used api.openaq.org; access can be flaky/rate-limited.
    base = "https://api.openaq.org/v2/measurements"
    params = {
        "city": city_name,
        "parameter": "pm25",
        "date_from": start.isoformat().replace("+00:00", "Z"),
        "date_to": end.isoformat().replace("+00:00", "Z"),
        "limit": 10000,
        "sort": "desc",
    }
    try:
        r = requests.get(base, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        results = js.get("results", [])
        if not results:
            return pd.DataFrame()

        rows = []
        for it in results:
            coords = it.get("coordinates") or {}
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            dt_utc = (it.get("date") or {}).get("utc")
            val = it.get("value")
            if lat is None or lon is None or dt_utc is None or val is None:
                continue
            rows.append(
                {
                    "station_id": str(it.get("location") or "unknown"),
                    "station_name": str(it.get("location") or "unknown"),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "timestamp": pd.to_datetime(dt_utc, utc=True),
                    "pm25": float(val),
                    "data_source": "openaq",
                }
            )
        df = pd.DataFrame(rows)
        if df.empty:
            return df

        # Hourly aggregate (OpenAQ can have sub-hourly readings)
        df["timestamp"] = df["timestamp"].dt.floor("H")
        df = (
            df.groupby(["station_id", "station_name", "latitude", "longitude", "timestamp"], as_index=False)["pm25"]
            .mean()
            .assign(data_source="openaq")
        )
        return df
    except Exception as e:
        logger.warning("OpenAQ fetch failed for %s: %s", city_name, e)
        return pd.DataFrame()


def generate_synthetic_station_pm25(
    *,
    boundary_wgs84_polygon,
    lookback_days: int,
    n_stations: int = 6,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Fallback synthetic station data (documented) so pipeline runs end-to-end.
    """
    rng = np.random.default_rng(seed)
    end = _utc_now_hour()
    hours = _date_range_hours(end, lookback_days)

    minx, miny, maxx, maxy = boundary_wgs84_polygon.bounds  # lon,lat
    stations = []
    for i in range(n_stations):
        lat = float(rng.uniform(miny, maxy))
        lon = float(rng.uniform(minx, maxx))
        stations.append((f"syn_{i+1}", f"Synthetic Station {i+1}", lat, lon))

    rows = []
    for sid, sname, lat, lon in stations:
        base = rng.uniform(35, 75)  # typical urban baseline
        amp = rng.uniform(10, 35)  # diurnal variation amplitude
        noise = rng.normal(0, 8, size=len(hours))
        # A mild weekly cycle
        weekly = 5 * np.sin(np.linspace(0, 2 * np.pi, len(hours)))
        diurnal = amp * np.sin(2 * np.pi * (hours.hour.values / 24.0) - 1.2) + amp * 0.2 * np.cos(
            2 * np.pi * (hours.hour.values / 24.0)
        )
        pm = np.clip(base + weekly + diurnal + noise, 5, 250)
        for t, v in zip(hours, pm):
            rows.append(
                {
                    "station_id": sid,
                    "station_name": sname,
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": pd.to_datetime(t, utc=True),
                    "pm25": float(v),
                    "data_source": "synthetic",
                }
            )
    return pd.DataFrame(rows)


def assign_stations_to_h3(df_stations: pd.DataFrame, h3_resolution: int) -> pd.DataFrame:
    df = df_stations.copy()
    df["h3_id"] = df.apply(lambda r: h3.latlng_to_cell(float(r["latitude"]), float(r["longitude"]), int(h3_resolution)), axis=1)
    return df


def build_aq_panel(
    *,
    h3_grid: pd.DataFrame,  # h3_id, centroid_lat, centroid_lon
    stations_hourly: pd.DataFrame,
    lookback_days: int,
    h3_resolution: int,
    idw_power: float = 2.0,
    min_stations: int = 3,
) -> pd.DataFrame:
    """
    Returns panel with columns:
      h3_id, timestamp, current_pm25, pm25_observed_flag, pm25_interpolated_flag
    """
    if stations_hourly.empty:
        raise ValueError("stations_hourly is empty; cannot build AQ panel.")

    stations_hourly = assign_stations_to_h3(stations_hourly, h3_resolution)

    end = _utc_now_hour()
    hours = _date_range_hours(end, lookback_days)
    h3_cells = h3_grid[["h3_id", "centroid_lat", "centroid_lon"]].copy()

    # Station coords
    st_meta = stations_hourly[["station_id", "latitude", "longitude"]].drop_duplicates()
    st_meta = st_meta.reset_index(drop=True)

    # Precompute distances from each cell centroid to each station
    dist = np.zeros((len(h3_cells), len(st_meta)), dtype=float)
    for i, row in h3_cells.iterrows():
        for j, st in st_meta.iterrows():
            dist[i, j] = _haversine_km(row["centroid_lat"], row["centroid_lon"], st["latitude"], st["longitude"])
    dist = np.maximum(dist, 0.05)  # avoid zero division
    weights = 1.0 / np.power(dist, idw_power)

    panels = []
    # Aggregate station readings per timestamp
    for t in hours:
        st_t = stations_hourly[stations_hourly["timestamp"] == t]
        if st_t.empty:
            continue

        # Observed mean per cell for cells containing stations
        obs_by_cell = st_t.groupby("h3_id")["pm25"].mean()

        # IDW for all cells using stations available at time t
        st_t_meta = st_t.merge(st_meta, on=["station_id", "latitude", "longitude"], how="inner")
        if len(st_t_meta["station_id"].unique()) < min_stations:
            # fallback: forward-fill by using obs or NaN
            idw_vals = np.full(len(h3_cells), np.nan, dtype=float)
        else:
            # Build vector of station values aligned to st_meta order
            vals = np.full(len(st_meta), np.nan, dtype=float)
            for j, st in st_meta.iterrows():
                v = st_t_meta.loc[st_t_meta["station_id"] == st["station_id"], "pm25"]
                if len(v) > 0:
                    vals[j] = float(v.mean())
            valid = ~np.isnan(vals)
            w = weights[:, valid]
            v = vals[valid]
            idw_vals = (w @ v) / np.sum(w, axis=1)

        out = pd.DataFrame(
            {
                "h3_id": h3_cells["h3_id"].values,
                "timestamp": pd.to_datetime(t, utc=True),
                "current_pm25": idw_vals,
                "pm25_observed_flag": 0,
                "pm25_interpolated_flag": 1,
            }
        )
        if not obs_by_cell.empty:
            # overwrite with observed where available
            out = out.set_index("h3_id")
            idx = obs_by_cell.index.intersection(out.index)
            if len(idx) > 0:
                out.loc[idx, "current_pm25"] = obs_by_cell.loc[idx].values
                out.loc[idx, "pm25_observed_flag"] = 1
                out.loc[idx, "pm25_interpolated_flag"] = 0
            out = out.reset_index()

        panels.append(out)

    panel = pd.concat(panels, ignore_index=True)
    panel["current_pm25"] = panel["current_pm25"].astype(float).clip(lower=0)
    return panel

