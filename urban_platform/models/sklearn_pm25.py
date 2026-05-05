from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    *,
    test_fraction: float = 0.2,
    force_model: Optional[str] = None,  # random_forest | xgboost | None
    rf_params: Optional[dict] = None,
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
    train, test = _time_split(df, test_fraction=float(test_fraction))

    X_train = train[feature_cols].fillna(0.0).values
    y_train = train[target_col].values.astype(float)
    X_test = test[feature_cols].fillna(0.0).values
    y_test = test[target_col].values.astype(float)

    metrics_all: Dict[str, Dict[str, float]] = {}

    # 1) Persistence baseline
    y_pred_persist = test["current_pm25"].values.astype(float)
    metrics_all["persistence"] = evaluate_regression(y_test, y_pred_persist)

    # 2) RandomForest
    rf_params = rf_params or {}
    rf = RandomForestRegressor(
        n_estimators=int(rf_params.get("n_estimators", 250)),
        random_state=int(rf_params.get("random_state", 42)),
        n_jobs=-1,
        max_depth=None,
        min_samples_leaf=int(rf_params.get("min_samples_leaf", 2)),
    )
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    metrics_all["random_forest"] = evaluate_regression(y_test, y_pred_rf)

    best_name = "random_forest"
    best_model = rf
    best_rmse = metrics_all[best_name]["RMSE"]
    xgb_model = None

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
        xgb_model = xgb
        y_pred_xgb = xgb.predict(X_test)
        metrics_all["xgboost"] = evaluate_regression(y_test, y_pred_xgb)
        if metrics_all["xgboost"]["RMSE"] < best_rmse:
            best_name = "xgboost"
            best_model = xgb
            best_rmse = metrics_all["xgboost"]["RMSE"]
    except Exception as e:
        logger.info("XGBoost unavailable or failed; continuing with RF. (%s)", e)

    # Improvement vs persistence for each ML model
    persist_rmse = metrics_all["persistence"]["RMSE"]
    for k in list(metrics_all.keys()):
        if k == "persistence":
            continue
        metrics_all[k]["RMSE_improvement_vs_persistence"] = float(persist_rmse - metrics_all[k]["RMSE"])
        metrics_all[k]["MAE_improvement_vs_persistence"] = float(metrics_all["persistence"]["MAE"] - metrics_all[k]["MAE"])

    # Optional override
    if force_model:
        fm = str(force_model).strip().lower()
        if fm in {"random_forest", "xgboost"}:
            if fm == "xgboost" and xgb_model is None:
                logger.warning("force_model=xgboost requested but xgboost unavailable; using random_forest.")
                best_name = "random_forest"
                best_model = rf
            else:
                best_name = fm
                best_model = rf if fm == "random_forest" else xgb_model
            best_rmse = float(metrics_all.get(best_name, {}).get("RMSE", best_rmse))
        else:
            logger.warning("Unknown force_model=%s; ignoring.", force_model)

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
    # Probabilistic outputs where possible
    pred = model.predict(X).astype(float)
    latest["forecast_pm25_mean"] = pred
    latest["forecast_pm25_p50"] = pred
    latest["forecast_pm25_p10"] = np.nan
    latest["forecast_pm25_p90"] = np.nan
    latest["forecast_pm25_std"] = np.nan

    # RandomForest: tree-level distribution
    if hasattr(model, "estimators_"):
        try:
            tree_preds = np.stack([est.predict(X).astype(float) for est in model.estimators_], axis=0)  # (n_trees, n)
            latest["forecast_pm25_mean"] = tree_preds.mean(axis=0)
            latest["forecast_pm25_std"] = tree_preds.std(axis=0)
            latest["forecast_pm25_p10"] = np.quantile(tree_preds, 0.10, axis=0)
            latest["forecast_pm25_p50"] = np.quantile(tree_preds, 0.50, axis=0)
            latest["forecast_pm25_p90"] = np.quantile(tree_preds, 0.90, axis=0)
        except Exception:
            pass

    latest["uncertainty_band"] = (latest["forecast_pm25_p90"] - latest["forecast_pm25_p10"]).astype(float)
    latest["model_name"] = model_name
    return latest

