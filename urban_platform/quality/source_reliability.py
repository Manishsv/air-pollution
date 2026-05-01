from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _flatline_detected(values: pd.Series, *, run_len: int = 6) -> bool:
    if values.empty:
        return False
    v = values.dropna()
    if len(v) < run_len:
        return False
    # consecutive identical values
    same = v.eq(v.shift(1))
    # compute longest run of True (plus first element)
    run = 0
    best = 0
    for x in same.fillna(False).tolist():
        if x:
            run += 1
        else:
            run = 0
        best = max(best, run)
    # best counts "matches to previous", so 5 means 6 identical in a row
    return best >= (run_len - 1)


def _impossible_value(variable: str, v: float) -> bool:
    var = (variable or "").lower()
    if not np.isfinite(v):
        return False
    if var == "pm25":
        return v < 0 or v > 1000
    if var == "relative_humidity_2m":
        return v < 0 or v > 100
    if var == "wind_speed_10m":
        return v < 0 or v > 75
    if var == "temperature_2m":
        return v < -60 or v > 60
    if var == "precipitation":
        return v < 0
    return False


def _spike_detected(variable: str, df: pd.DataFrame) -> bool:
    var = (variable or "").lower()
    if df.empty:
        return False
    s = pd.to_numeric(df["value"], errors="coerce").dropna()
    if len(s) < 2:
        return False
    d = s.diff().abs()
    if var == "pm25":
        return bool((d > 150).any())
    if var == "temperature_2m":
        return bool((d > 15).any())
    if var == "relative_humidity_2m":
        return bool((d > 50).any())
    if var == "wind_speed_10m":
        return bool((d > 30).any())
    return False


def assess_source_reliability(
    observation_store_df: pd.DataFrame,
    *,
    expected_frequency_minutes: int = 60,
    lookback_hours: int = 72,
    current_time: Optional[datetime] = None,
    peer_distance_km: float = 5.0,
) -> pd.DataFrame:
    """
    Return one row per entity_id + variable with transparent reliability fields.
    """
    if observation_store_df is None or observation_store_df.empty:
        return pd.DataFrame(
            columns=[
                "entity_id",
                "entity_type",
                "variable",
                "source",
                "status",
                "reliability_score",
                "last_seen",
                "observation_count",
                "expected_observation_count",
                "completeness_ratio",
                "stale_hours",
                "flatline_detected",
                "impossible_value_detected",
                "spike_detected",
                "duplicate_timestamp_ratio",
                "peer_disagreement_score",
                "reliability_issues",
                "point_lat",
                "point_lon",
            ]
        )

    now = pd.to_datetime(current_time, utc=True) if current_time is not None else _utc_now()
    lookback_start = now - pd.Timedelta(hours=int(lookback_hours))

    df = observation_store_df.copy()
    # Normalize columns
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df[df["timestamp"].notna()].copy()
    df = df[df["timestamp"] >= lookback_start].copy()
    if df.empty:
        return pd.DataFrame()

    expected_count = float(int(lookback_hours) * 60.0 / float(expected_frequency_minutes))

    out_rows = []

    # Precompute peer latest values for peer disagreement (variable-wise)
    # We'll compute on demand but keep latest per entity+variable.
    latest = (
        df.sort_values("timestamp")
        .groupby(["entity_id", "variable"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )

    for (entity_id, variable), g in df.groupby(["entity_id", "variable"]):
        g = g.sort_values("timestamp")
        entity_type = str(g["entity_type"].iloc[0]) if "entity_type" in g.columns else "unknown"
        source = str(g["source"].iloc[0]) if "source" in g.columns else "unknown"
        lat = pd.to_numeric(g.get("point_lat"), errors="coerce").dropna()
        lon = pd.to_numeric(g.get("point_lon"), errors="coerce").dropna()
        point_lat = float(lat.iloc[0]) if len(lat) else np.nan
        point_lon = float(lon.iloc[0]) if len(lon) else np.nan

        observation_count = int(len(g))
        last_seen = pd.to_datetime(g["timestamp"].max(), utc=True)
        stale_hours = float((now - last_seen) / pd.Timedelta(hours=1)) if pd.notna(last_seen) else float("inf")

        # Completeness
        completeness_ratio = float(observation_count / expected_count) if expected_count > 0 else 0.0
        completeness_ratio = float(max(0.0, min(1.0, completeness_ratio)))

        # Duplicate timestamps
        dup_ratio = float(g["timestamp"].duplicated().mean()) if observation_count > 0 else 0.0

        # Flatline
        flatline = _flatline_detected(pd.to_numeric(g["value"], errors="coerce"))

        # Impossible values
        vals = pd.to_numeric(g["value"], errors="coerce").dropna()
        impossible = bool(vals.apply(lambda v: _impossible_value(str(variable), float(v))).any()) if len(vals) else False

        # Spike
        spike = _spike_detected(str(variable), g[["timestamp", "value"]])

        # Peer disagreement (latest reading vs peer median)
        peer_disagreement_score = 0.0
        peer_issue = False
        if np.isfinite(point_lat) and np.isfinite(point_lon):
            try:
                lv = latest[(latest["variable"] == variable)].copy()
                lv = lv.dropna(subset=["entity_id"])
                if "point_lat" in lv.columns and "point_lon" in lv.columns:
                    lv["point_lat"] = pd.to_numeric(lv["point_lat"], errors="coerce")
                    lv["point_lon"] = pd.to_numeric(lv["point_lon"], errors="coerce")
                else:
                    lv["point_lat"] = np.nan
                    lv["point_lon"] = np.nan

                lv = lv.dropna(subset=["point_lat", "point_lon"]).copy()
                lv = lv[lv["entity_id"].astype(str) != str(entity_id)].copy()
                if not lv.empty:
                    lv["dist_km"] = lv.apply(lambda r: _haversine_km(point_lat, point_lon, float(r["point_lat"]), float(r["point_lon"])), axis=1)
                    peers = lv[lv["dist_km"] <= float(peer_distance_km)].copy()
                    if not peers.empty:
                        # compare latest values
                        my_latest = latest[(latest["entity_id"].astype(str) == str(entity_id)) & (latest["variable"] == variable)]
                        my_val = pd.to_numeric(my_latest["value"], errors="coerce").dropna()
                        peer_vals = pd.to_numeric(peers["value"], errors="coerce").dropna()
                        if len(my_val) and len(peer_vals):
                            med = float(peer_vals.median())
                            mine = float(my_val.iloc[0])
                            dev = abs(mine - med)
                            if str(variable).lower() == "pm25":
                                if med > 0 and dev > 50 and mine > 2 * med:
                                    peer_issue = True
                                    peer_disagreement_score = min(1.0, dev / 200.0)
                            else:
                                # generic light check
                                if med > 0 and dev > 3 * (abs(med) + 1e-6):
                                    peer_issue = True
                                    peer_disagreement_score = 0.5
            except Exception:
                peer_issue = False
                peer_disagreement_score = 0.0

        issues = []
        score = 1.0

        # Incomplete data penalty up to 0.25
        score -= 0.25 * (1.0 - completeness_ratio)
        if completeness_ratio < 0.8:
            issues.append("incomplete_data")

        # Stale/offline
        if stale_hours > (3.0 * float(expected_frequency_minutes) / 60.0):
            score -= 0.20
            issues.append("stale_data")
        if stale_hours > 24.0 or observation_count == 0:
            score -= 0.50
            issues.append("offline")

        if flatline:
            score -= 0.25
            issues.append("flatline_detected")
        if impossible:
            score -= 0.40
            issues.append("impossible_value_detected")
        if spike:
            score -= 0.15
            issues.append("spike_detected")
        if dup_ratio > 0.05:
            score -= 0.10
            issues.append("duplicate_timestamps")
        if peer_issue:
            score -= 0.20
            issues.append("peer_disagreement")

        score = float(max(0.0, min(1.0, score)))

        # Status assignment
        status = "unknown"
        if observation_count == 0:
            status = "offline"
        elif stale_hours > 24.0:
            status = "offline"
        elif impossible or peer_issue:
            status = "suspect"
        elif score < 0.7 or flatline or spike or ("stale_data" in issues) or ("incomplete_data" in issues):
            status = "degraded"
        elif score >= 0.85 and not (flatline or spike or impossible or peer_issue or ("stale_data" in issues)):
            status = "healthy"

        out_rows.append(
            {
                "entity_id": str(entity_id),
                "entity_type": str(entity_type),
                "variable": str(variable),
                "source": str(source),
                "status": status,
                "reliability_score": score,
                "last_seen": str(last_seen) if pd.notna(last_seen) else None,
                "observation_count": observation_count,
                "expected_observation_count": expected_count,
                "completeness_ratio": completeness_ratio,
                "stale_hours": stale_hours,
                "flatline_detected": bool(flatline),
                "impossible_value_detected": bool(impossible),
                "spike_detected": bool(spike),
                "duplicate_timestamp_ratio": dup_ratio,
                "peer_disagreement_score": float(peer_disagreement_score),
                "reliability_issues": "; ".join(sorted(set(issues))),
                "point_lat": point_lat,
                "point_lon": point_lon,
            }
        )

    return pd.DataFrame(out_rows)

