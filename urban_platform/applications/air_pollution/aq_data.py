from __future__ import annotations

import logging
import math
import os
import time
import hashlib
from pathlib import Path
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
    return pd.date_range(start=start, end=end_utc, freq="1h", tz="UTC")


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
        df["timestamp"] = df["timestamp"].dt.floor("h")
        df = (
            df.groupby(["station_id", "station_name", "latitude", "longitude", "timestamp"], as_index=False)["pm25"]
            .mean()
            .assign(data_source="openaq")
        )
        return df
    except Exception as e:
        logger.warning("OpenAQ fetch failed for %s: %s", city_name, e)
        return pd.DataFrame()


def _openaq_headers() -> dict:
    key = os.getenv("OPENAQ_API_KEY", "").strip()
    if key:
        return {"X-API-Key": key}
    return {}


def _cache_valid(path: Path, ttl_days: int) -> bool:
    if not path.exists():
        return False
    if ttl_days <= 0:
        return True
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= ttl_days * 86400


def _openaq_cache_dir(cache_dir: Optional[Path]) -> Optional[Path]:
    if cache_dir is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _hash_key(*parts: str) -> str:
    s = "|".join(parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def fetch_openaq_pm25_v3(
    *,
    bbox_west_south_east_north: tuple[float, float, float, float],
    lookback_days: int,
    max_locations: int = 100,
    max_sensors: int = 80,
    cache_dir: Optional[Path] = None,
    cache_ttl_days: int = 7,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    OpenAQ v3 best-effort fetch using bbox.
    Returns station-hourly records with:
      station_id, station_name, latitude, longitude, timestamp, pm25, data_source

    v3 approach:
      - GET /v3/locations?bbox=...&parameters_id=2  (pm25)
      - For each location, take pm25 sensors
      - GET /v3/sensors/{id}/hours?datetime_from=...&datetime_to=...
    """
    west, south, east, north = bbox_west_south_east_north
    end = _utc_now_hour()
    start = end - timedelta(days=int(lookback_days))

    base = "https://api.openaq.org/v3"
    loc_url = f"{base}/locations"
    # bbox is "minX,minY,maxX,maxY" in WGS84, 4dp precision recommended by docs
    bbox_str = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
    cache_dir = _openaq_cache_dir(cache_dir)
    params_bbox = {
        "bbox": bbox_str,
        "parameters_id": "2",  # pm25
        "limit": min(int(max_locations), 100),
        "page": 1,
        "sort_order": "asc",
    }
    # Alternative search if bbox returns 0: centroid + radius (max 25km per docs)
    center_lat = (south + north) / 2.0
    center_lon = (west + east) / 2.0
    params_radius = {
        "coordinates": f"{center_lat:.4f},{center_lon:.4f}",
        "radius": 25000,
        "parameters_id": "2",
        "limit": min(int(max_locations), 100),
        "page": 1,
        "sort_order": "asc",
    }

    try:
        def _to_list(x):
            if x is None:
                return []
            if isinstance(x, list):
                return x
            try:
                return list(x)
            except Exception:
                return []

        # Cache locations response (query is bbox or radius)
        locs = []
        if cache_dir is not None:
            loc_key = _hash_key("locs_bbox", bbox_str, str(max_locations), str(max_sensors))
            loc_path = cache_dir / f"openaqv3_{loc_key}_locations.parquet"
            if (not force_refresh) and _cache_valid(loc_path, cache_ttl_days):
                try:
                    loc_df = pd.read_parquet(loc_path)
                    locs = loc_df.to_dict(orient="records")
                except Exception:
                    locs = []
        if len(locs) == 0:
            r = requests.get(loc_url, params=params_bbox, headers=_openaq_headers(), timeout=30)
            r.raise_for_status()
            js = r.json()
            locs = _to_list(js.get("results", []) or [])
            if cache_dir is not None and len(locs) > 0:
                pd.DataFrame(locs).to_parquet(loc_path, index=False)
        else:
            locs = _to_list(locs)

        if len(locs) == 0:
            # Try centroid+radius search (useful when bbox is too tight or data coverage sparse)
            if cache_dir is not None:
                loc_key2 = _hash_key("locs_radius", f"{center_lat:.4f},{center_lon:.4f}", "25000", str(max_locations), str(max_sensors))
                loc_path2 = cache_dir / f"openaqv3_{loc_key2}_locations.parquet"
                if (not force_refresh) and _cache_valid(loc_path2, cache_ttl_days):
                    try:
                        loc_df = pd.read_parquet(loc_path2)
                        locs = loc_df.to_dict(orient="records")
                    except Exception:
                        locs = []
            if len(locs) == 0:
                r = requests.get(loc_url, params=params_radius, headers=_openaq_headers(), timeout=30)
                r.raise_for_status()
                js = r.json()
                locs = _to_list(js.get("results", []) or [])
                if cache_dir is not None and len(locs) > 0:
                    pd.DataFrame(locs).to_parquet(loc_path2, index=False)
            else:
                locs = _to_list(locs)

        if len(locs) == 0:
            logger.warning("OpenAQ v3 returned 0 locations for bbox=%s (and radius fallback).", bbox_str)
            return pd.DataFrame()

        # Collect pm25 sensors
        sensors = []
        for loc in locs[:max_locations]:
            coords = loc.get("coordinates") or {}
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            if lat is None or lon is None:
                continue
            loc_id = loc.get("id")
            loc_name = loc.get("name") or f"location_{loc_id}"
            sensors_list = _to_list(loc.get("sensors", []))
            for s in sensors_list:
                p = (s.get("parameter") or {}).get("name")
                if str(p).lower() != "pm25":
                    continue
                sensors.append(
                    {
                        "sensor_id": int(s.get("id")),
                        "location_id": int(loc_id) if loc_id is not None else None,
                        "station_name": str(loc_name),
                        "latitude": float(lat),
                        "longitude": float(lon),
                    }
                )
                if len(sensors) >= max_sensors:
                    break
            if len(sensors) >= max_sensors:
                break

        if not sensors:
            logger.warning("OpenAQ v3 locations found but 0 pm25 sensors (bbox=%s).", bbox_str)
            return pd.DataFrame()

        rows = []
        dt_from = start.isoformat().replace("+00:00", "Z")
        dt_to = end.isoformat().replace("+00:00", "Z")

        for s in sensors:
            sid = s["sensor_id"]
            hours_url = f"{base}/sensors/{sid}/hours"
            # Cache each sensor-hours pull (same bbox/time window often repeated)
            sensor_rows = None
            if cache_dir is not None:
                h_key = _hash_key("hours", str(sid), dt_from, dt_to)
                h_path = cache_dir / f"openaqv3_{h_key}_sensorhours.parquet"
                if (not force_refresh) and _cache_valid(h_path, cache_ttl_days):
                    try:
                        sensor_rows = pd.read_parquet(h_path)
                    except Exception:
                        sensor_rows = None

            if sensor_rows is not None and not sensor_rows.empty:
                rows.extend(sensor_rows.to_dict(orient="records"))
                continue

            try:
                page = 1
                sensor_accum = []
                while True:
                    pr = {
                        "datetime_from": dt_from,
                        "datetime_to": dt_to,
                        "limit": 1000,
                        "page": page,
                    }
                    resp = requests.get(hours_url, params=pr, headers=_openaq_headers(), timeout=30)
                    if resp.status_code == 429:
                        logger.warning("OpenAQ v3 rate-limited (429).")
                        break
                    if resp.status_code >= 500:
                        logger.warning("OpenAQ v3 server error for sensor_id=%s (status=%s). Skipping sensor.", sid, resp.status_code)
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", []) or []
                    if not results:
                        break
                    for it in results:
                        val = it.get("value")
                        period = it.get("period") or {}
                        dt_utc = ((period.get("datetimeFrom") or {}) or {}).get("utc")
                        if val is None or dt_utc is None:
                            continue
                        rec = {
                            "station_id": str(sid),
                            "station_name": s["station_name"],
                            "latitude": s["latitude"],
                            "longitude": s["longitude"],
                            "timestamp": pd.to_datetime(dt_utc, utc=True).floor("h"),
                            "pm25": float(val),
                            "data_source": "openaq_v3",
                        }
                        rows.append(rec)
                        sensor_accum.append(rec)
                    # pagination stop: if less than limit returned, no more pages
                    if len(results) < 1000:
                        break
                    page += 1

                if cache_dir is not None and len(sensor_accum) > 0:
                    pd.DataFrame(sensor_accum).to_parquet(h_path, index=False)
            except Exception as e:
                logger.warning("OpenAQ v3 sensor-hours failed for sensor_id=%s; skipping. (%s)", sid, e)
                continue

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = (
            df.groupby(["station_id", "station_name", "latitude", "longitude", "timestamp"], as_index=False)["pm25"]
            .mean()
            .assign(data_source="openaq_v3")
        )
        return df
    except Exception as e:
        # Include traceback for debugging intermittent cache/type issues.
        logger.exception("OpenAQ v3 fetch failed (bbox=%s): %s", bbox_str, e)
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

    # Station coords + source
    st_meta_cols = ["station_id", "latitude", "longitude"]
    if "data_source" in stations_hourly.columns:
        st_meta_cols.append("data_source")
    st_meta = stations_hourly[st_meta_cols].drop_duplicates()
    st_meta = st_meta.reset_index(drop=True)
    if "data_source" in st_meta.columns:
        st_meta["station_source_type"] = np.where(st_meta["data_source"].astype(str).str.contains("synthetic"), "synthetic", "real")
    else:
        st_meta["station_source_type"] = "unavailable"

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
        obs_source = None
        if "data_source" in st_t.columns:
            # mark observed cells as synthetic if their station readings are synthetic
            ssrc = st_t.groupby("h3_id")["data_source"].apply(lambda x: "synthetic" if x.astype(str).str.contains("synthetic").any() else "real")
            obs_source = ssrc

        # IDW for all cells using stations available at time t
        st_t_meta = st_t.merge(st_meta, on=["station_id", "latitude", "longitude"], how="inner")
        station_ids_available = st_t_meta["station_id"].unique().tolist()
        if len(station_ids_available) < min_stations:
            # fallback: forward-fill by using obs or NaN
            idw_vals = np.full(len(h3_cells), np.nan, dtype=float)
            station_count_used = len(station_ids_available)
            # still compute nearest distance to any available station(s) (honesty for sparse coverage)
            if station_count_used > 0:
                # map station ids to st_meta indices
                idxs = [int(st_meta.index[st_meta["station_id"] == sid][0]) for sid in station_ids_available if (st_meta["station_id"] == sid).any()]
                nearest_km = np.min(dist[:, idxs], axis=1) if idxs else np.full(len(h3_cells), np.nan, dtype=float)
            else:
                nearest_km = np.full(len(h3_cells), np.nan, dtype=float)
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
            station_count_used = int(np.sum(valid))
            # nearest distance to any station with a value at this time
            nearest_km = np.min(dist[:, valid], axis=1) if station_count_used > 0 else np.full(len(h3_cells), np.nan, dtype=float)

        all_available_sources = None
        if "data_source" in st_t.columns:
            all_available_sources = "synthetic" if st_t["data_source"].astype(str).str.contains("synthetic").all() else "real"

        out = pd.DataFrame(
            {
                "h3_id": h3_cells["h3_id"].values,
                "timestamp": pd.to_datetime(t, utc=True),
                "current_pm25": idw_vals,
                "pm25_observed_flag": 0,
                "pm25_interpolated_flag": 1,
                "aq_source_type": "interpolated",
                "interpolation_method": f"idw(power={float(idw_power):.2f})",
                "nearest_station_distance_km": nearest_km,
                "station_count_used": station_count_used,
                "warning_flags": "",
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
                out.loc[idx, "aq_source_type"] = "real"
                out.loc[idx, "interpolation_method"] = ""
                out.loc[idx, "nearest_station_distance_km"] = 0.0
                if obs_source is not None:
                    out.loc[idx, "aq_source_type"] = obs_source.loc[idx].values
            out = out.reset_index()

        # If all available stations are synthetic, label all cells as synthetic (even if "interpolated")
        if all_available_sources == "synthetic":
            out["aq_source_type"] = "synthetic"
            out["warning_flags"] = out["warning_flags"].apply(lambda s: (s + "; " if s else "") + "SYNTHETIC_AQ_USED")

        # Warnings for sparse / far stations
        if station_count_used < 3:
            out["warning_flags"] = out["warning_flags"].apply(lambda s: (s + "; " if s else "") + "FEW_STATIONS_USED")
        out.loc[out["nearest_station_distance_km"] > 10, "warning_flags"] = out.loc[out["nearest_station_distance_km"] > 10, "warning_flags"].apply(
            lambda s: (s + "; " if s else "") + "FAR_FROM_STATIONS"
        )

        panels.append(out)

    panel = pd.concat(panels, ignore_index=True)
    panel["current_pm25"] = panel["current_pm25"].astype(float).clip(lower=0)
    return panel


def spatial_station_holdout_validation(
    *,
    stations_hourly: pd.DataFrame,
    lookback_days: int,
    idw_power: float = 2.0,
    min_real_stations: int = 4,
    min_other_stations: int = 2,
    holdout_station_id: Optional[str] = None,
) -> dict:
    """
    Simple spatial diagnostic:
    Hold out one REAL station and evaluate IDW reconstruction from remaining stations.
    This does NOT validate the full grid+model pipeline, but provides a sanity check under sparse coverage.
    """
    if stations_hourly.empty:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: no station data",
        }

    st = stations_hourly.copy()
    st["station_source_type"] = np.where(st.get("data_source", "").astype(str).str.contains("synthetic"), "synthetic", "real")
    real = st[st["station_source_type"] == "real"].copy()
    if real["station_id"].nunique() < min_real_stations:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: insufficient real stations",
        }

    # Pick holdout station. If not provided, pick the station with the most
    # overlap hours where at least 3 other stations have readings (so the IDW
    # reconstruction is actually evaluable).
    station_ids = sorted(real["station_id"].astype(str).unique().tolist())
    if holdout_station_id and str(holdout_station_id) in station_ids:
        hid = str(holdout_station_id)
    else:
        tmp = real.copy()
        tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], utc=True).dt.floor("h")
        # For each hour, how many distinct stations report?
        n_by_t = tmp.groupby("timestamp")["station_id"].nunique()
        # Candidate hours where at least (1 holdout + N others) stations report.
        # We default N=2 to keep this diagnostic usable under sparse/patchy coverage.
        need = int(max(2, min_other_stations)) + 1
        good_hours = set(n_by_t[n_by_t >= need].index)
        if not good_hours:
            return {
                "spatial_validation_performed": False,
                "spatial_validation_note": f"Spatial validation skipped: no hours with >={need} simultaneous real stations",
            }
        # Score each station by number of good_hours it appears in
        score = (
            tmp[tmp["timestamp"].isin(good_hours)]
            .groupby("station_id")["timestamp"]
            .nunique()
            .sort_values(ascending=False)
        )
        hid = str(score.index[0]) if len(score) else station_ids[0]

    held = real[real["station_id"].astype(str) == hid].copy()
    others = real[real["station_id"].astype(str) != hid].copy()
    if others["station_id"].nunique() < 3:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: <3 remaining stations after holdout",
        }

    lat_h = float(held["latitude"].iloc[0])
    lon_h = float(held["longitude"].iloc[0])

    meta = others[["station_id", "latitude", "longitude"]].drop_duplicates().reset_index(drop=True)
    d = meta.apply(lambda r: _haversine_km(lat_h, lon_h, float(r["latitude"]), float(r["longitude"])), axis=1).values
    d = np.maximum(d.astype(float), 0.05)
    w = 1.0 / np.power(d, float(idw_power))

    # hourly compare
    held = held[["timestamp", "pm25"]].copy()
    held["timestamp"] = pd.to_datetime(held["timestamp"], utc=True).dt.floor("h")
    held = held.groupby("timestamp", as_index=False)["pm25"].mean()

    others["timestamp"] = pd.to_datetime(others["timestamp"], utc=True).dt.floor("h")
    errors = []
    for row in held.itertuples(index=False):
        t = row.timestamp  # pandas Timestamp (tz-aware)
        y = float(row.pm25)
        o = others[others["timestamp"] == t]
        if o.empty:
            continue
        # align station values to meta
        vals = np.full(len(meta), np.nan, dtype=float)
        for i, row in meta.iterrows():
            v = o.loc[o["station_id"] == row["station_id"], "pm25"]
            if len(v) > 0:
                vals[i] = float(v.mean())
        valid = ~np.isnan(vals)
        if valid.sum() < int(max(2, min_other_stations)):
            continue
        pred = float((w[valid] * vals[valid]).sum() / w[valid].sum())
        errors.append((float(y), pred))

    if not errors:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: insufficient overlapping timestamps",
        }

    yt = np.array([e[0] for e in errors], dtype=float)
    yp = np.array([e[1] for e in errors], dtype=float)
    mae = float(np.mean(np.abs(yt - yp)))
    rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
    return {
        "spatial_validation_performed": True,
        "spatial_validation_holdout_station_id": hid,
        "spatial_validation_mae": mae,
        "spatial_validation_rmse": rmse,
        "spatial_validation_note": "IDW reconstruction error at one held-out real station",
    }

