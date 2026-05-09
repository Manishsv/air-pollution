from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from urban_platform.models.sklearn_pm25 import predict_latest as _legacy_predict_latest
from urban_platform.models.sklearn_pm25 import train_models as _legacy_train_models


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _station_holdout(
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
    """
    if stations_hourly.empty:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: no station data",
        }

    st = stations_hourly.copy()
    st["station_source_type"] = np.where(
        st.get("data_source", "").astype(str).str.contains("synthetic"), "synthetic", "real"
    )
    real = st[st["station_source_type"] == "real"].copy()
    if real["station_id"].nunique() < min_real_stations:
        return {
            "spatial_validation_performed": False,
            "spatial_validation_note": "Spatial validation skipped: insufficient real stations",
        }

    station_ids = sorted(real["station_id"].astype(str).unique().tolist())
    if holdout_station_id and str(holdout_station_id) in station_ids:
        hid = str(holdout_station_id)
    else:
        tmp = real.copy()
        tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], utc=True).dt.floor("h")
        n_by_t = tmp.groupby("timestamp")["station_id"].nunique()
        need = int(max(2, min_other_stations)) + 1
        good_hours = set(n_by_t[n_by_t >= need].index)
        if not good_hours:
            return {
                "spatial_validation_performed": False,
                "spatial_validation_note": (
                    f"Spatial validation skipped: no hours with >={need} simultaneous real stations"
                ),
            }
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
    d = meta.apply(
        lambda r: _haversine_km(lat_h, lon_h, float(r["latitude"]), float(r["longitude"])), axis=1
    ).values
    d = np.maximum(d.astype(float), 0.05)
    w = 1.0 / np.power(d, float(idw_power))

    held = held[["timestamp", "pm25"]].copy()
    held["timestamp"] = pd.to_datetime(held["timestamp"], utc=True).dt.floor("h")
    held = held.groupby("timestamp", as_index=False)["pm25"].mean()

    others["timestamp"] = pd.to_datetime(others["timestamp"], utc=True).dt.floor("h")
    errors = []
    for row in held.itertuples(index=False):
        t = row.timestamp
        y = float(row.pm25)
        o = others[others["timestamp"] == t]
        if o.empty:
            continue
        vals = np.full(len(meta), np.nan, dtype=float)
        for i, mrow in meta.iterrows():
            v = o.loc[o["station_id"] == mrow["station_id"], "pm25"]
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


@dataclass(frozen=True)
class ForecastArtifacts:
    model_name: str
    model_path: Path
    metrics: Dict


def train_forecast_model(
    feature_table: pd.DataFrame,
    *,
    target_col: str,
    outputs_dir: Path,
    test_fraction: float,
    force_model: str | None,
    rf_params: dict,
) -> tuple[ForecastArtifacts, Dict]:
    artifacts, metrics_all = _legacy_train_models(
        feature_table,
        target_col=target_col,
        outputs_dir=outputs_dir,
        test_fraction=test_fraction,
        force_model=force_model,
        rf_params=rf_params,
    )
    return ForecastArtifacts(model_name=artifacts.model_name, model_path=artifacts.model_path, metrics=artifacts.metrics), metrics_all


def predict_forecast(model: ForecastArtifacts, feature_table: pd.DataFrame, *, target_col: str) -> pd.DataFrame:
    return _legacy_predict_latest(dataset=feature_table, model_path=model.model_path, target_col=target_col)


def run_spatial_cross_validation(
    dataset: pd.DataFrame,
    station_ids,
    model,
    n_splits: int | None = None,
) -> dict:
    """
    Platform-level spatial validation helper.

    Note: The current air-quality reference pipeline does not carry station-level rows
    through the ML dataset. Therefore this function implements leave-one-station-out
    spatial validation over the **station network** using the existing IDW reconstruction
    diagnostic (scientifically defensible and auditable under sparse coverage).

    - If >=5 real stations: run leave-one-station-out (or capped by n_splits).
    - Else: fall back to single-station holdout validation.
    """
    _ = model  # reserved for future model-aware CV; intentionally unused for now
    if dataset is None or dataset.empty:
        return {
            "spatial_cv_station_count": 0,
            "spatial_cv_method": "leave_one_station_out",
            "spatial_cv_performed": False,
            "spatial_cv_note": "Spatial CV skipped: empty station dataset",
        }

    st = dataset.copy()
    if isinstance(station_ids, str) and station_ids in st.columns:
        sid = st[station_ids]
    else:
        sid = station_ids
    st["station_id"] = pd.Series(sid).astype(str).values

    # Determine count of real stations (ignore synthetic)
    st["station_source_type"] = np.where(st.get("data_source", "").astype(str).str.contains("synthetic"), "synthetic", "real")
    real = st[st["station_source_type"] == "real"].copy()
    uniq = sorted(real["station_id"].dropna().astype(str).unique().tolist())
    station_count = int(len(uniq))

    if station_count < 5:
        base = _station_holdout(
            stations_hourly=st,
            lookback_days=7,
            idw_power=2.0,
            min_real_stations=4,
        )
        return {
            "spatial_cv_station_count": station_count,
            "spatial_cv_method": "single_holdout_fallback",
            "spatial_cv_performed": bool(base.get("spatial_validation_performed", False)),
            "spatial_cv_mean_mae": base.get("spatial_validation_mae"),
            "spatial_cv_mean_rmse": base.get("spatial_validation_rmse"),
            "spatial_cv_max_rmse": base.get("spatial_validation_rmse"),
            "spatial_cv_note": "Fallback to single-station holdout (insufficient stations for leave-one-out)",
        }

    if n_splits is not None:
        uniq = uniq[: int(n_splits)]

    maes = []
    rmses = []
    for holdout in uniq:
        res = _station_holdout(
            stations_hourly=st,
            lookback_days=7,
            idw_power=2.0,
            min_real_stations=4,
            holdout_station_id=str(holdout),
        )
        if not bool(res.get("spatial_validation_performed", False)):
            continue
        try:
            maes.append(float(res.get("spatial_validation_mae")))
            rmses.append(float(res.get("spatial_validation_rmse")))
        except Exception:
            continue

    if not rmses:
        return {
            "spatial_cv_station_count": station_count,
            "spatial_cv_method": "leave_one_station_out",
            "spatial_cv_performed": False,
            "spatial_cv_note": "Spatial CV skipped: insufficient overlapping timestamps across folds",
        }

    return {
        "spatial_cv_station_count": station_count,
        "spatial_cv_method": "leave_one_station_out",
        "spatial_cv_performed": True,
        "spatial_cv_mean_mae": float(np.mean(maes)),
        "spatial_cv_mean_rmse": float(np.mean(rmses)),
        "spatial_cv_max_rmse": float(np.max(rmses)),
    }
