from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


ACTION_LIBRARY = {
    "traffic_proxy": "Traffic signal optimization, congestion management, public transport priority, parking enforcement.",
    "built_environment_proxy": "Dust suppression, mechanized road sweeping, construction inspection.",
    "industrial_proxy": "Inspect industrial units, verify fuel use and emissions compliance.",
    "green_deficit_proxy": "Prioritize greening, dust buffers, and long-term land-use mitigation.",
    "weather_dispersion_proxy": "Public advisory, pre-emptive restrictions, avoid high-emission activities.",
    "fire_signal_proxy": "Field verification and enforcement for burning event.",
    "insufficient_evidence": "Field verification recommended before action.",
}


def pm25_category_india(pm25: float, categories: Dict[str, Tuple[float, float]]) -> str:
    v = float(pm25)
    for name, (lo, hi) in categories.items():
        if v >= float(lo) and v <= float(hi):
            return str(name)
    # fallback
    return "unknown"


def likely_contributing_factors_rules(row: pd.Series) -> Tuple[str, str, str]:
    """
    Returns:
      likely_contributing_factors (semicolon-separated),
      driver_confidence (low|medium|high),
      driver_method (rule_based_proxy|unavailable)
    """
    # If AQ is synthetic, do not pretend to infer factors.
    if str(row.get("aq_source_type", "")).lower() == "synthetic":
        return "insufficient_evidence", "low", "unavailable"

    factors: List[str] = []
    # Fire proxy only if fire data is real
    if str(row.get("fire_source_type", "")).lower() == "real" and float(row.get("fire_count_nearby", 0) or 0) > 0:
        factors.append("fire_signal_proxy")
    # Weather dispersion proxy
    if float(row.get("wind_speed_10m", 999) or 999) < 1.5:
        factors.append("weather_dispersion_proxy")
    if float(row.get("industrial_landuse_area_sqm", 0.0) or 0.0) > 50_000:
        factors.append("industrial_proxy")
    if float(row.get("road_density_km_per_sqkm", 0.0) or 0.0) > 8:
        factors.append("traffic_proxy")
    if float(row.get("built_up_ratio", 0.0) or 0.0) > 0.25:
        factors.append("built_environment_proxy")
    if float(row.get("green_area_sqm", 0.0) or 0.0) < 10_000 and float(row.get("forecast_pm25_mean", 0.0) or 0.0) > 60:
        factors.append("green_deficit_proxy")

    if not factors:
        return "insufficient_evidence", "low", "rule_based_proxy"

    # Confidence heuristics
    dq = float(row.get("data_quality_score", 0.0) or 0.0)
    band = float(row.get("uncertainty_band", 0.0) or 0.0)
    if dq >= 0.75 and band <= 25:
        conf = "high"
    elif dq >= 0.5 and band <= 50:
        conf = "medium"
    else:
        conf = "low"

    return "; ".join(factors), conf, "rule_based_proxy"


def attach_recommendations(
    latest_predictions: pd.DataFrame,
    pm25_categories: Dict[str, Tuple[float, float]],
    *,
    recommendation_allowed: bool,
    recommendation_block_reason: str,
    model_warning_flags: str = "",
) -> pd.DataFrame:
    df = latest_predictions.copy()

    df["pm25_category_india"] = df["forecast_pm25_mean"].apply(lambda v: pm25_category_india(float(v), pm25_categories))

    factors = df.apply(likely_contributing_factors_rules, axis=1, result_type="expand")
    factors.columns = ["likely_contributing_factors", "driver_confidence", "driver_method"]
    df = pd.concat([df, factors], axis=1)

    # Default recommendation text (cautious)
    def choose_action(row: pd.Series) -> str:
        if not recommendation_allowed:
            return f"No operational recommendation: {recommendation_block_reason}"
        # If ML model warning exists, avoid strong actions
        if model_warning_flags:
            return "Field verification recommended before action (model experimental / low confidence)."
        if float(row.get("data_quality_score", 0.0) or 0.0) < 0.5:
            return "Field verification recommended before action (low data quality)."
        if float(row.get("uncertainty_band", 0.0) or 0.0) > 60:
            return "Field verification recommended before action (high forecast uncertainty)."
        # Pick first factor action if available
        f = str(row.get("likely_contributing_factors") or "insufficient_evidence").split(";")[0].strip()
        return ACTION_LIBRARY.get(f, ACTION_LIBRARY["insufficient_evidence"])

    df["recommendation_allowed"] = bool(recommendation_allowed)
    df["recommendation_block_reason"] = recommendation_block_reason if not recommendation_allowed else ""
    df["recommended_action"] = df.apply(choose_action, axis=1)

    # Merge warning flags
    if "warning_flags" not in df.columns:
        df["warning_flags"] = ""
    if model_warning_flags:
        df["warning_flags"] = df["warning_flags"].astype(str).apply(lambda s: (s + "; " if s else "") + model_warning_flags)
    return df

