from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from src.model import predict_latest as _legacy_predict_latest
from src.model import train_models as _legacy_train_models
import numpy as np

from src.aq_data import spatial_station_holdout_validation as _station_holdout


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
