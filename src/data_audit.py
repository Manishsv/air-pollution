from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from .provenance import ensure_provenance_columns


logger = logging.getLogger(__name__)


def audit_data_coverage(
    *,
    grid_gdf: gpd.GeoDataFrame,
    aq_stations_hourly: pd.DataFrame,
    aq_panel: pd.DataFrame,
    model_dataset: pd.DataFrame,
    h3_resolution: int,
    quality_gates: dict,
) -> Dict[str, Any]:
    """
    Audits provenance + coverage before modelling.
    Returns JSON-serializable dict.
    """
    aq_panel = ensure_provenance_columns(aq_panel)
    model_dataset = ensure_provenance_columns(model_dataset)

    # Station counts by source
    st = aq_stations_hourly.copy()
    if "data_source" in st.columns:
        st["aq_station_source_type"] = np.where(st["data_source"].astype(str).str.contains("synthetic"), "synthetic", "real")
    else:
        st["aq_station_source_type"] = "unavailable"

    number_of_real_aq_stations = int(st[st["aq_station_source_type"] == "real"]["station_id"].nunique()) if "station_id" in st.columns else 0
    number_of_synthetic_aq_stations = int(st[st["aq_station_source_type"] == "synthetic"]["station_id"].nunique()) if "station_id" in st.columns else 0

    aq_observation_count = int(aq_panel.shape[0])
    expected = int(grid_gdf.shape[0]) * int(aq_panel["timestamp"].nunique() if "timestamp" in aq_panel.columns else 0)
    aq_completeness_ratio = float(aq_observation_count / expected) if expected > 0 else 0.0

    # Cell-level mix
    latest_ts = pd.to_datetime(aq_panel["timestamp"], utc=True).max() if "timestamp" in aq_panel.columns else None
    latest = aq_panel[aq_panel["timestamp"] == latest_ts].copy() if latest_ts is not None else aq_panel.copy()

    percent_cells_with_observed_aq = float((latest["aq_source_type"] == "real").mean() * 100.0) if not latest.empty else 0.0
    percent_cells_interpolated = float((latest["aq_source_type"] == "interpolated").mean() * 100.0) if not latest.empty else 0.0
    percent_cells_synthetic = float((latest["aq_source_type"] == "synthetic").mean() * 100.0) if not latest.empty else 0.0

    # Distances
    d = pd.to_numeric(latest.get("nearest_station_distance_km", pd.Series(dtype=float)), errors="coerce")
    avg_nearest_station_distance_km = float(np.nanmean(d)) if len(d) else float("nan")
    max_nearest_station_distance_km = float(np.nanmax(d)) if len(d) else float("nan")

    # Source counts
    weather_source_type_counts = model_dataset.get("weather_source_type", pd.Series(dtype=str)).fillna("unavailable").astype(str).value_counts().to_dict()
    fire_source_type_counts = model_dataset.get("fire_source_type", pd.Series(dtype=str)).fillna("unavailable").astype(str).value_counts().to_dict()

    osm_feature_counts = {
        "grid_cells": int(grid_gdf.shape[0]),
    }

    avg_h3_cell_area_sqkm = float(pd.to_numeric(grid_gdf.get("area_sqkm"), errors="coerce").mean())

    warning_flags = []
    if number_of_real_aq_stations < int(quality_gates.get("min_real_stations_required", 3)):
        warning_flags.append("LOW_CONFIDENCE: insufficient real AQ stations")
    if np.isfinite(avg_nearest_station_distance_km) and avg_nearest_station_distance_km > float(quality_gates.get("max_avg_station_distance_km", 10)):
        warning_flags.append("LOW_CONFIDENCE: stations too far from grid cells on average")

    # Recommendation allowed decision
    block_if_synth = bool(quality_gates.get("block_recommendations_if_synthetic", True))
    max_synth_ratio = float(quality_gates.get("max_synthetic_aq_ratio_for_recommendations", 0.0))
    synth_ratio = float((latest["aq_source_type"] == "synthetic").mean()) if not latest.empty else 1.0
    recommendation_allowed = True
    recommendation_block_reason = ""
    if block_if_synth and synth_ratio > 0:
        recommendation_allowed = False
        recommendation_block_reason = "Synthetic AQ data used"
    elif synth_ratio > max_synth_ratio:
        recommendation_allowed = False
        recommendation_block_reason = f"Synthetic AQ ratio {synth_ratio:.2f} exceeds gate {max_synth_ratio:.2f}"

    return {
        "number_of_real_aq_stations": number_of_real_aq_stations,
        "number_of_synthetic_aq_stations": number_of_synthetic_aq_stations,
        "aq_observation_count": aq_observation_count,
        "aq_completeness_ratio": aq_completeness_ratio,
        "percent_cells_with_observed_aq": percent_cells_with_observed_aq,
        "percent_cells_interpolated": percent_cells_interpolated,
        "percent_cells_synthetic": percent_cells_synthetic,
        "avg_nearest_station_distance_km": avg_nearest_station_distance_km,
        "max_nearest_station_distance_km": max_nearest_station_distance_km,
        "weather_source_type_counts": weather_source_type_counts,
        "fire_source_type_counts": fire_source_type_counts,
        "osm_feature_counts": osm_feature_counts,
        "h3_resolution": int(h3_resolution),
        "avg_h3_cell_area_sqkm": avg_h3_cell_area_sqkm,
        "warning_flags": warning_flags,
        "recommendation_allowed": recommendation_allowed,
        "recommendation_block_reason": recommendation_block_reason,
    }


def print_audit_summary(audit: Dict[str, Any]) -> None:
    msg = (
        f"DATA AUDIT | real_stations={audit.get('number_of_real_aq_stations')} "
        f"synthetic_stations={audit.get('number_of_synthetic_aq_stations')} "
        f"observed_cells%={audit.get('percent_cells_with_observed_aq'):.1f} "
        f"interpolated_cells%={audit.get('percent_cells_interpolated'):.1f} "
        f"synthetic_cells%={audit.get('percent_cells_synthetic'):.1f} "
        f"avg_station_dist_km={audit.get('avg_nearest_station_distance_km'):.2f} "
        f"recommendation_allowed={audit.get('recommendation_allowed')} "
        f"block_reason={audit.get('recommendation_block_reason')}"
    )
    logger.warning(msg)
    flags = audit.get("warning_flags") or []
    for f in flags:
        logger.warning("DATA AUDIT FLAG: %s", f)

