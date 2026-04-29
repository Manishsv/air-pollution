from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelArtifacts:
    model_name: str
    model_path: Path
    metrics: Dict[str, float]
    feature_names: List[str]


def _time_split(df: pd.DataFrame, test_fraction: float = 0.2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("timestamp")
    unique_ts = df["timestamp"].dropna().sort_values().unique()
    if len(unique_ts) < 10:
        raise ValueError("Not enough timestamps for time split.")
    cutoff_idx = int(len(unique_ts) * (1 - test_fraction))
    cutoff = unique_ts[cutoff_idx]
    train = df[df["timestamp"] < cutoff].copy()
    test = df[df["timestamp"] >= cutoff].copy()
    return train, test


def evaluate_regression(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(mean_squared_error(y_true, y_pred, squared=False))
    r2 = float(r2_score(y_true, y_pred))
    return {"MAE": mae, "RMSE": rmse, "R2": r2}


def train_models(
    dataset: pd.DataFrame,
    target_col: str,
    outputs_dir: Path,
) -> Tuple[ModelArtifacts, Dict[str, Dict[str, float]]]:
    """
    Trains:
      - persistence baseline
      - RandomForestRegressor (reliable dependency)
      - XGBoostRegressor if available
    Saves best (by RMSE) to outputs_dir/pm25_model.joblib
    """
    df = dataset.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Select numeric features
    drop_cols = {
        "timestamp",
        "data_source",
        "pm25_observed_flag",
        "pm25_interpolated_flag",
        target_col,
    }
    feature_cols = [c for c in df.columns if c not in drop_cols and c not in {"h3_id"}]
    # Keep only numeric
    feature_cols = [c for c in feature_cols if pd.api.types.is_numeric_dtype(df[c])]

    # Drop rows without target and core lags
    df = df.dropna(subset=[target_col, "current_pm25", "pm25_lag_1h", "pm25_lag_3h"]).copy()
    train, test = _time_split(df)

    X_train = train[feature_cols].fillna(0.0).values
    y_train = train[target_col].values.astype(float)
    X_test = test[feature_cols].fillna(0.0).values
    y_test = test[target_col].values.astype(float)

    metrics_all: Dict[str, Dict[str, float]] = {}

    # 1) Persistence baseline
    y_pred_persist = test["current_pm25"].values.astype(float)
    metrics_all["persistence"] = evaluate_regression(y_test, y_pred_persist)

    # 2) RandomForest
    rf = RandomForestRegressor(
        n_estimators=250,
        random_state=42,
        n_jobs=-1,
        max_depth=None,
        min_samples_leaf=2,
    )
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    metrics_all["random_forest"] = evaluate_regression(y_test, y_pred_rf)

    best_name = "random_forest"
    best_model = rf
    best_rmse = metrics_all[best_name]["RMSE"]

    # 3) XGBoost (optional)
    try:
        from xgboost import XGBRegressor  # type: ignore

        xgb = XGBRegressor(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
        )
        xgb.fit(X_train, y_train)
        y_pred_xgb = xgb.predict(X_test)
        metrics_all["xgboost"] = evaluate_regression(y_test, y_pred_xgb)
        if metrics_all["xgboost"]["RMSE"] < best_rmse:
            best_name = "xgboost"
            best_model = xgb
            best_rmse = metrics_all["xgboost"]["RMSE"]
    except Exception as e:
        logger.info("XGBoost unavailable or failed; continuing with RF. (%s)", e)

    outputs_dir.mkdir(parents=True, exist_ok=True)
    model_path = outputs_dir / "pm25_model.joblib"
    joblib.dump(
        {
            "model_name": best_name,
            "model": best_model,
            "feature_cols": feature_cols,
        },
        model_path,
    )

    best_metrics = metrics_all[best_name]
    return ModelArtifacts(model_name=best_name, model_path=model_path, metrics=best_metrics, feature_names=feature_cols), metrics_all


def load_model(model_path: Path):
    obj = joblib.load(model_path)
    return obj["model"], obj["feature_cols"], obj.get("model_name", "model")


def predict_latest(
    *,
    dataset: pd.DataFrame,
    model_path: Path,
    target_col: str,
) -> pd.DataFrame:
    model, feature_cols, model_name = load_model(model_path)
    df = dataset.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    latest_ts = df["timestamp"].max()
    latest = df[df["timestamp"] == latest_ts].copy()
    latest = latest.dropna(subset=["current_pm25"]).copy()
    X = latest[feature_cols].fillna(0.0).values
    pred = model.predict(X)
    latest["forecast_pm25"] = pred.astype(float)
    latest["model_name"] = model_name
    return latest

