from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


ACTIONS = {
    "traffic_proxy": "Traffic signal optimization, congestion management, public transport priority, parking enforcement.",
    "built_environment_proxy": "Dust suppression, mechanized road sweeping, construction inspection.",
    "industrial_proxy": "Inspect industrial units, verify fuel use and emissions compliance.",
    "green_deficit_proxy": "Prioritize greening, dust buffers, and long-term land-use mitigation.",
    "weather_dispersion": "Public advisory, pre-emptive restrictions, avoid high-emission activities.",
    "fire_influence": "Field verification and enforcement for burning event.",
    "unknown": "Routine monitoring and field verification.",
}


def classify_hotspot(pm25: float, thresholds: Dict[str, float]) -> str:
    low = float(thresholds.get("low", 30))
    moderate = float(thresholds.get("moderate", 60))
    high = float(thresholds.get("high", 90))
    severe = float(thresholds.get("severe", 120))
    if pm25 >= severe:
        return "severe"
    if pm25 >= high:
        return "high"
    if pm25 >= moderate:
        return "moderate"
    return "low"


def dominant_driver_rules(row: pd.Series) -> str:
    # Simple interpretable fallback rules (robust even without model importances)
    if row.get("fire_count_nearby", 0) and row.get("fire_count_nearby", 0) > 0:
        return "fire_influence"
    if row.get("wind_speed_10m", 999) < 1.5:
        return "weather_dispersion"
    if row.get("industrial_landuse_area_sqm", 0.0) > 50_000:
        return "industrial_proxy"
    if row.get("road_density_km_per_sqkm", 0.0) > 8:
        return "traffic_proxy"
    if row.get("built_up_ratio", 0.0) > 0.25:
        return "built_environment_proxy"
    if row.get("green_area_sqm", 0.0) < 10_000 and row.get("forecast_pm25", 0.0) > 60:
        return "green_deficit_proxy"
    return "unknown"


def attach_recommendations(
    latest_predictions: pd.DataFrame,
    thresholds: Dict[str, float],
) -> pd.DataFrame:
    df = latest_predictions.copy()
    df["hotspot_level"] = df["forecast_pm25"].apply(lambda v: classify_hotspot(float(v), thresholds))
    df["dominant_driver"] = df.apply(dominant_driver_rules, axis=1)
    df["recommended_action"] = df["dominant_driver"].map(ACTIONS).fillna(ACTIONS["unknown"])
    return df

