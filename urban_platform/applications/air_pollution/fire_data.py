from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests


logger = logging.getLogger(__name__)


def _utc_now_hour() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def fetch_firms_fire_events(
    *,
    bbox: tuple[float, float, float, float],  # south,north,west,east
    lookback_days: int,
    api_key: str,
) -> pd.DataFrame:
    """
    Best-effort NASA FIRMS (VIIRS SNPP) CSV fetch.
    Returns columns: latitude, longitude, acq_datetime_utc
    """
    # FIRMS API endpoints vary; keep this optional and non-blocking.
    # If this fails, caller should fallback to empty.
    # FIRMS Area API (CSV) format (see https://firms.modaps.eosdis.nasa.gov/api/area/):
    #   /api/area/csv/{MAP_KEY}/{SOURCE}/{WEST,SOUTH,EAST,NORTH}/{DAY_RANGE}
    # DAY_RANGE is limited (typically 1..5). For longer lookbacks, caller should
    # either accept truncation or implement paging by date.
    south, north, west, east = bbox
    day_range = int(max(1, min(int(lookback_days), 5)))
    source = "VIIRS_SNPP_NRT"
    area = f"{west},{south},{east},{north}"

    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{source}/{area}/{day_range}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    # If it is CSV, pandas can read from text
    from io import StringIO

    df = pd.read_csv(StringIO(r.text))
    # normalize
    lat_col = "latitude" if "latitude" in df.columns else None
    lon_col = "longitude" if "longitude" in df.columns else None
    if lat_col is None or lon_col is None:
        return pd.DataFrame()
    df = df.rename(columns={lat_col: "latitude", lon_col: "longitude"})
    # FIRMS commonly provides acquisition date/time columns; best effort parse
    if "acq_date" in df.columns and "acq_time" in df.columns:
        # acq_time like 1230
        t = df["acq_time"].astype(str).str.zfill(4)
        dt = pd.to_datetime(df["acq_date"] + " " + t.str.slice(0, 2) + ":" + t.str.slice(2, 4), utc=True, errors="coerce")
        df["acq_datetime_utc"] = dt
    else:
        df["acq_datetime_utc"] = pd.NaT
    return df[["latitude", "longitude", "acq_datetime_utc"]].dropna(subset=["latitude", "longitude"])


def build_fire_features_panel(
    *,
    h3_grid: pd.DataFrame,  # h3_id, centroid_lat, centroid_lon
    lookback_days: int,
    bbox_south_north_west_east: Optional[tuple[float, float, float, float]],
) -> pd.DataFrame:
    """
    Returns per-cell per-hour features:
      h3_id, timestamp, fire_count_nearby, distance_to_nearest_fire_km
    If FIRMS_API_KEY missing, returns zeros.
    """
    api_key = os.getenv("FIRMS_API_KEY", "").strip()
    end = _utc_now_hour()
    start = end - timedelta(days=int(lookback_days))
    hours = pd.date_range(start=start, end=end, freq="1h", tz="UTC")

    if not api_key or bbox_south_north_west_east is None:
        logger.info("Fire data disabled (missing FIRMS_API_KEY or bbox).")
        base = pd.MultiIndex.from_product([h3_grid["h3_id"].values, hours], names=["h3_id", "timestamp"]).to_frame(index=False)
        base["fire_count_nearby"] = 0
        base["distance_to_nearest_fire_km"] = np.nan
        base["fire_source_type"] = "unavailable"
        base["fire_warning_flags"] = "FIRE_DATA_UNAVAILABLE"
        return base

    try:
        fires = fetch_firms_fire_events(bbox=bbox_south_north_west_east, lookback_days=lookback_days, api_key=api_key)
    except Exception as e:
        logger.warning("FIRMS fetch failed; disabling fire features: %s", e)
        base = pd.MultiIndex.from_product([h3_grid["h3_id"].values, hours], names=["h3_id", "timestamp"]).to_frame(index=False)
        base["fire_count_nearby"] = 0
        base["distance_to_nearest_fire_km"] = np.nan
        base["fire_source_type"] = "unavailable"
        base["fire_warning_flags"] = "FIRE_DATA_UNAVAILABLE"
        return base

    if fires.empty:
        base = pd.MultiIndex.from_product([h3_grid["h3_id"].values, hours], names=["h3_id", "timestamp"]).to_frame(index=False)
        base["fire_count_nearby"] = 0
        base["distance_to_nearest_fire_km"] = np.nan
        base["fire_source_type"] = "real"
        base["fire_warning_flags"] = "NO_FIRES_DETECTED"
        return base

    # Very simple: treat all fires as static over range; compute nearest distance per cell.
    # Count nearby within 10km.
    fire_lat = fires["latitude"].astype(float).values
    fire_lon = fires["longitude"].astype(float).values

    def haversine_km(lat1, lon1, lat2, lon2):
        import math

        R = 6371.0088
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
        return 2 * R * math.asin(math.sqrt(a))

    nearest_km = []
    nearby_cnt = []
    for _, row in h3_grid.iterrows():
        d = np.array([haversine_km(row["centroid_lat"], row["centroid_lon"], la, lo) for la, lo in zip(fire_lat, fire_lon)])
        nearest_km.append(float(np.min(d)))
        nearby_cnt.append(int(np.sum(d <= 10.0)))

    per_cell = pd.DataFrame({"h3_id": h3_grid["h3_id"].values, "distance_to_nearest_fire_km": nearest_km, "fire_count_nearby": nearby_cnt})
    base = pd.MultiIndex.from_product([h3_grid["h3_id"].values, hours], names=["h3_id", "timestamp"]).to_frame(index=False)
    out = base.merge(per_cell, on="h3_id", how="left")
    out["fire_source_type"] = "real"
    out["fire_warning_flags"] = ""
    return out

