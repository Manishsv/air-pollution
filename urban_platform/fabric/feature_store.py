from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd

from src.provenance import compute_data_quality_score


FEATURE_STORE_COLUMNS = [
    "grid_id",
    "timestamp",
    "feature_name",
    "value",
    "unit",
    "source",
    "confidence",
    "quality_flag",
    "provenance",
]


def _json_dumps_safe(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        return "{}"


def _add_rows(
    rows: list[dict],
    *,
    grid_id: str,
    timestamp: Optional[pd.Timestamp],
    feature_name: str,
    value: Any,
    unit: str,
    source: str,
    confidence: float,
    quality_flag: str,
    provenance: Dict[str, Any],
) -> None:
    rows.append(
        {
            "grid_id": str(grid_id),
            "timestamp": timestamp,
            "feature_name": str(feature_name),
            # Parquet requires consistent column types; store as string and coerce on pivot.
            "value": None if value is None else str(value),
            "unit": str(unit),
            "source": str(source),
            "confidence": float(confidence),
            "quality_flag": str(quality_flag),
            "provenance": _json_dumps_safe(provenance),
        }
    )


def _iter_feature_cols(df: pd.DataFrame, exclude: Iterable[str]) -> list[str]:
    exc = set(exclude)
    return [c for c in df.columns if c not in exc]


def build_feature_store(
    static_features,
    aq_panel: pd.DataFrame,
    weather_hourly: pd.DataFrame,
    fire_features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build canonical long-form feature store supporting multiple urban domains.

    Canonical schema:
      grid_id, timestamp, feature_name, value, unit, source, confidence, quality_flag, provenance

    Rules:
    - Static features stored with timestamp = null
    - Dynamic features carry timestamps
    - Provenance fields preserved (stored in `provenance` JSON, and also as features
      for backward-compatible pivots where needed)
    """
    rows: list[dict] = []

    # Determine grid ids
    grid_ids: list[str] = []
    if static_features is not None and len(static_features) > 0 and "h3_id" in getattr(static_features, "columns", []):
        grid_ids = static_features["h3_id"].astype(str).tolist()
    elif aq_panel is not None and not aq_panel.empty and "h3_id" in aq_panel.columns:
        grid_ids = sorted(aq_panel["h3_id"].astype(str).unique().tolist())

    # 1) Static features (timestamp = null)
    if static_features is not None and len(static_features) > 0:
        sf = static_features.copy()
        if "h3_id" in sf.columns:
            sf = sf.rename(columns={"h3_id": "grid_id"})
        if "grid_id" not in sf.columns:
            raise ValueError("static_features must include h3_id/grid_id")
        for row in sf.itertuples(index=False):
            gid = str(getattr(row, "grid_id"))
            for col in _iter_feature_cols(sf, exclude={"grid_id", "geometry", "geometry_projected_wkt"}):
                val = getattr(row, col)
                # Keep even string provenance columns (e.g., osm_source_type) so pivot can recreate legacy schema.
                _add_rows(
                    rows,
                    grid_id=gid,
                    timestamp=None,
                    feature_name=col,
                    value=val,
                    unit="",
                    source="static",
                    confidence=0.85,
                    quality_flag="ok",
                    provenance={"layer": "static_features"},
                )

    # 2) AQ panel dynamic features
    if aq_panel is not None and not aq_panel.empty:
        aq = aq_panel.copy()
        aq["timestamp"] = pd.to_datetime(aq["timestamp"], utc=True, errors="coerce")
        for row in aq.itertuples(index=False):
            gid = str(getattr(row, "h3_id"))
            ts = pd.to_datetime(getattr(row, "timestamp"), utc=True, errors="coerce")
            prov = {"layer": "aq_panel"}
            for col in _iter_feature_cols(aq, exclude={"h3_id", "timestamp"}):
                _add_rows(
                    rows,
                    grid_id=gid,
                    timestamp=ts,
                    feature_name=col,
                    value=getattr(row, col),
                    unit="",
                    source="aq",
                    confidence=0.8,
                    quality_flag="synthetic" if str(getattr(row, "aq_source_type", "")).lower() == "synthetic" else "ok",
                    provenance=prov,
                )

    # 3) Weather dynamic features (broadcast to all grid_ids)
    if weather_hourly is not None and not weather_hourly.empty:
        wx = weather_hourly.copy()
        wx["timestamp"] = pd.to_datetime(wx["timestamp"], utc=True, errors="coerce")
        vars_cols = _iter_feature_cols(wx, exclude={"timestamp"})
        for row in wx.itertuples(index=False):
            ts = pd.to_datetime(getattr(row, "timestamp"), utc=True, errors="coerce")
            qf = "synthetic" if "synthetic" in str(getattr(row, "weather_source_type", "")).lower() else "ok"
            for gid in (grid_ids or ["__unassigned__"]):
                prov = {"layer": "weather_hourly"}
                for col in vars_cols:
                    _add_rows(
                        rows,
                        grid_id=str(gid),
                        timestamp=ts,
                        feature_name=col,
                        value=getattr(row, col),
                        unit="",
                        source="weather",
                        confidence=0.8 if qf == "ok" else 0.4,
                        quality_flag=qf,
                        provenance=prov,
                    )

    # 4) Fire features (optional)
    if fire_features is not None and not fire_features.empty:
        ff = fire_features.copy()
        if "timestamp" in ff.columns:
            ff["timestamp"] = pd.to_datetime(ff["timestamp"], utc=True, errors="coerce")
        for row in ff.itertuples(index=False):
            gid = str(getattr(row, "h3_id"))
            ts = pd.to_datetime(getattr(row, "timestamp"), utc=True, errors="coerce")
            qf = "synthetic" if "synthetic" in str(getattr(row, "fire_source_type", "")).lower() else "ok"
            prov = {"layer": "fire_features"}
            for col in _iter_feature_cols(ff, exclude={"h3_id", "timestamp"}):
                _add_rows(
                    rows,
                    grid_id=gid,
                    timestamp=ts,
                    feature_name=col,
                    value=getattr(row, col),
                    unit="",
                    source="fire",
                    confidence=0.7 if qf == "ok" else 0.4,
                    quality_flag=qf,
                    provenance=prov,
                )

    out = pd.DataFrame(rows, columns=FEATURE_STORE_COLUMNS)
    if not out.empty:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out["value"] = out["value"].astype("string")
    return out


def pivot_feature_store_for_model(feature_store: pd.DataFrame, *, target_variable: str = "pm25", horizon_hours: int = 12) -> pd.DataFrame:
    """
    Pivot canonical feature store into a wide model table matching legacy `model_dataset.csv`.
    """
    if feature_store is None or feature_store.empty:
        return pd.DataFrame()

    fs = feature_store.copy()
    fs["timestamp"] = pd.to_datetime(fs["timestamp"], utc=True, errors="coerce")

    static = fs[fs["timestamp"].isna()].copy()
    dyn = fs[fs["timestamp"].notna()].copy()

    static_wide = pd.DataFrame()
    if not static.empty:
        static_wide = static.pivot_table(index=["grid_id"], columns="feature_name", values="value", aggfunc="first").reset_index()

    dyn_wide = dyn.pivot_table(index=["grid_id", "timestamp"], columns="feature_name", values="value", aggfunc="first").reset_index()

    # Join static features
    if not static_wide.empty:
        dyn_wide = dyn_wide.merge(static_wide, on="grid_id", how="left")

    # Map grid_id -> h3_id for backward compatibility
    df = dyn_wide.rename(columns={"grid_id": "h3_id"}).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    # Legacy expectations: ensure provenance string columns exist
    provenance_string_cols = [
        "aq_source_type",
        "weather_source_type",
        "fire_source_type",
        "osm_source_type",
        "interpolation_method",
        "warning_flags",
        "fire_warning_flags",
    ]
    for c in provenance_string_cols:
        if c not in df.columns:
            df[c] = "unavailable" if c.endswith("_type") or c.endswith("_source_type") else ""

    # Fire defaults if absent
    if "fire_count_nearby" not in df.columns:
        df["fire_count_nearby"] = 0
    if "distance_to_nearest_fire_km" not in df.columns:
        df["distance_to_nearest_fire_km"] = np.nan
    if "fire_source_type" not in df.columns:
        df["fire_source_type"] = "unavailable"
    if "fire_warning_flags" not in df.columns:
        df["fire_warning_flags"] = "FIRE_DATA_UNAVAILABLE"

    # Normalize source type columns as strings
    for c in ["aq_source_type", "weather_source_type", "fire_source_type", "osm_source_type"]:
        df[c] = df[c].fillna("unavailable").astype(str)
    df["warning_flags"] = df.get("warning_flags", "").fillna("").astype(str)

    # Coerce numeric columns back from string storage.
    protected = set(["h3_id", "timestamp", *provenance_string_cols])
    for c in list(df.columns):
        if c in protected:
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Ensure key numeric columns exist
    if "current_pm25" not in df.columns:
        df["current_pm25"] = np.nan
    df["current_pm25"] = pd.to_numeric(df["current_pm25"], errors="coerce")

    # Legacy dataset backbone is AQ panel rows; drop weather-only timestamps
    # to avoid creating "latest timestamp" rows with no PM2.5.
    df = df.dropna(subset=["current_pm25"]).copy()

    df = df.sort_values(["h3_id", "timestamp"]).reset_index(drop=True)

    # Lags per cell (match legacy lags)
    for lag_h in [1, 3, 24]:
        df[f"pm25_lag_{lag_h}h"] = df.groupby("h3_id")["current_pm25"].shift(lag_h)

    # Time features
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["hour"] = ts.dt.hour.astype(int)
    df["day_of_week"] = ts.dt.dayofweek.astype(int)
    df["month"] = ts.dt.month.astype(int)

    # Target
    h = int(horizon_hours)
    df[f"{target_variable}_t_plus_{h}h"] = df.groupby("h3_id")["current_pm25"].shift(-h)

    # Quality score
    if "nearest_station_distance_km" in df.columns:
        df["nearest_station_distance_km"] = pd.to_numeric(df["nearest_station_distance_km"], errors="coerce")
    else:
        df["nearest_station_distance_km"] = np.nan
    if "station_count_used" in df.columns:
        df["station_count_used"] = pd.to_numeric(df["station_count_used"], errors="coerce")
    else:
        df["station_count_used"] = np.nan

    df["data_quality_score"] = df.apply(
        lambda r: compute_data_quality_score(
            aq_source_type=str(r.get("aq_source_type")),
            weather_source_type=str(r.get("weather_source_type")),
            fire_source_type=str(r.get("fire_source_type")),
            nearest_station_distance_km=float(r.get("nearest_station_distance_km")) if pd.notna(r.get("nearest_station_distance_km")) else None,
            station_count_used=int(r.get("station_count_used")) if pd.notna(r.get("station_count_used")) else None,
        ),
        axis=1,
    )

    return df

