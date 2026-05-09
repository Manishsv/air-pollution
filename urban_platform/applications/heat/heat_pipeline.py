"""
Urban heat risk scoring pipeline.

Combines temperature observations (IDW-interpolated to H3 grid) with
OSM-derived green cover to produce:
  - Per-H3-cell heat risk grid (heat_risk_dashboard consumer contract)
  - Ranked intervention candidates (heat_intervention_candidates consumer contract)

All outputs are **indicative** (IDW-interpolated, OSM-proxied) and require
human review before any operational or public-facing action.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from urban_platform.rules import rules as _rules

logger = logging.getLogger(__name__)

_INTERVENTION_TOP_N = 10


# ── IDW temperature interpolation ─────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def _idw_interpolate(
    cell_lat: float,
    cell_lon: float,
    obs_lats: np.ndarray,
    obs_lons: np.ndarray,
    obs_vals: np.ndarray,
    power: float = 2.0,
) -> float:
    """IDW estimate for a cell from station observations. Returns NaN if no valid obs."""
    dists = np.array([
        _haversine_km(cell_lat, cell_lon, lat, lon)
        for lat, lon in zip(obs_lats, obs_lons)
    ])
    dists = np.maximum(dists, 0.05)
    weights = 1.0 / np.power(dists, power)
    total_w = weights.sum()
    if total_w == 0:
        return float("nan")
    return float(np.dot(weights, obs_vals) / total_w)


def _compute_cell_heat_index(
    temperature_df: pd.DataFrame,
    h3_grid: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute per-H3-cell heat index via IDW from latest temperature observations.

    Uses the most recent timestamp per station in temperature_df.
    Returns a DataFrame with columns: h3_id, heat_index_c, data_source.
    """
    if temperature_df.empty:
        return pd.DataFrame(columns=["h3_id", "heat_index_c", "data_source"])

    # Use latest obs per station
    latest = (
        temperature_df
        .sort_values("timestamp")
        .groupby("station_id")
        .last()
        .reset_index()
    )
    valid = latest[latest["temperature_c"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["h3_id", "heat_index_c", "data_source"])

    obs_lats = valid["latitude"].values
    obs_lons = valid["longitude"].values
    obs_vals = valid["temperature_c"].values
    data_source = "synthetic" if (valid.get("quality_flag", pd.Series(["real"])) == "synthetic").any() else "real"

    rows = []
    for _, cell in h3_grid.iterrows():
        hi = _idw_interpolate(cell["centroid_lat"], cell["centroid_lon"], obs_lats, obs_lons, obs_vals)
        rows.append({
            "h3_id": cell["h3_id"],
            "heat_index_c": hi,
            "data_source": data_source,
        })
    return pd.DataFrame(rows)


# ── H3 grid helpers ───────────────────────────────────────────────────────

def build_h3_grid_from_bbox(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    h3_resolution: int,
) -> pd.DataFrame:
    """Return DataFrame with columns h3_id, centroid_lat, centroid_lon."""
    import h3

    bbox_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min], [lon_max, lat_min],
            [lon_max, lat_max], [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }
    cell_ids = list(h3.geo_to_cells(bbox_geojson, h3_resolution))
    rows = []
    for cid in cell_ids:
        lat, lon = h3.cell_to_latlng(cid)
        rows.append({"h3_id": cid, "centroid_lat": lat, "centroid_lon": lon})
    return pd.DataFrame(rows)


# ── Core pipeline ─────────────────────────────────────────────────────────

def run_heat_pipeline(
    temperature_df: pd.DataFrame,
    green_cover_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
) -> dict[str, Any]:
    """
    Build the full heat risk dataset for a city.

    Parameters
    ----------
    temperature_df : DataFrame from OpenMeteo connector.
    green_cover_df : DataFrame from OSM green cover connector.
    h3_resolution : H3 grid resolution.
    city_id : Identifier string for the city.
    lat_min, lon_min, lat_max, lon_max : City bounding box (used if green_cover_df
        does not already define the H3 grid extent).

    Returns a dict with:
        heat_cells: DataFrame with per-H3-cell risk fields
        data_quality_flag: "real" | "synthetic" | "mixed" | "unavailable"
    """
    # Determine H3 grid from green cover if available, else from bbox
    if not green_cover_df.empty and "h3_id" in green_cover_df.columns:
        h3_ids = green_cover_df["h3_id"].unique().tolist()
        import h3 as _h3
        rows = []
        for cid in h3_ids:
            lat, lon = _h3.cell_to_latlng(cid)
            rows.append({"h3_id": cid, "centroid_lat": lat, "centroid_lon": lon})
        h3_grid = pd.DataFrame(rows)
    else:
        h3_grid = build_h3_grid_from_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)

    if h3_grid.empty:
        logger.warning("No H3 cells for city '%s'", city_id)
        return {"heat_cells": pd.DataFrame(), "data_quality_flag": "unavailable"}

    # Compute heat index via IDW
    heat_index_df = _compute_cell_heat_index(temperature_df, h3_grid)

    # Merge with green cover
    merged = h3_grid.merge(heat_index_df, on="h3_id", how="left")
    if not green_cover_df.empty and "h3_id" in green_cover_df.columns:
        merged = merged.merge(green_cover_df, on="h3_id", how="left")
    else:
        merged["green_cover_fraction"] = 0.0
        merged["water_proximity_score"] = 0.0

    merged["green_cover_fraction"] = merged["green_cover_fraction"].fillna(0.0)
    merged["water_proximity_score"] = merged["water_proximity_score"].fillna(0.0)

    # UHI intensity = cell heat index minus city-wide median
    valid_hi = merged["heat_index_c"].dropna()
    city_median = float(valid_hi.median()) if not valid_hi.empty else float("nan")
    merged["uhi_intensity"] = merged["heat_index_c"] - city_median

    # Normalize UHI intensity to [0, 1]
    uhi_vals = merged["uhi_intensity"].dropna()
    uhi_min = float(uhi_vals.min()) if not uhi_vals.empty else 0.0
    uhi_max = float(uhi_vals.max()) if not uhi_vals.empty else 1.0
    uhi_range = uhi_max - uhi_min if uhi_max != uhi_min else 1.0
    merged["uhi_norm"] = ((merged["uhi_intensity"] - uhi_min) / uhi_range).clip(0.0, 1.0)

    # Green deficit
    merged["green_deficit"] = (1.0 - merged["green_cover_fraction"]).clip(0.0, 1.0)

    # Heat risk score: UHI weight + green deficit weight (configurable)
    _hw = _rules.get("heat", "score_weights", default={"uhi_norm": 0.6, "green_deficit": 0.4})
    merged["heat_risk_score"] = (_hw["uhi_norm"] * merged["uhi_norm"] + _hw["green_deficit"] * merged["green_deficit"]).clip(0.0, 1.0)
    merged["heat_risk_score"] = merged["heat_risk_score"].fillna(merged["green_deficit"])

    # Data quality flag
    ds_col = merged.get("data_source")
    if temperature_df.empty:
        dq_flag = "unavailable"
    elif ds_col is not None and (ds_col == "synthetic").any():
        dq_flag = "synthetic"
    else:
        dq_flag = "real"

    if not merged.empty:
        try:
            from urban_platform.feature_store.writer import FeatureStoreWriter
            with FeatureStoreWriter() as fsw:
                fsw.write_heat_features(merged, city_id=city_id, data_quality_flag=dq_flag)
        except Exception as _fse:
            logger.warning("feature_store write skipped: %s", _fse)

    return {
        "heat_cells": merged,
        "data_quality_flag": dq_flag,
        "city_median_temperature_c": city_median,
    }


# ── Consumer contract builders ────────────────────────────────────────────

def build_heat_risk_dashboard(
    temperature_df: pd.DataFrame,
    green_cover_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    **bbox_kwargs: float,
) -> dict[str, Any]:
    """
    Return a dict conforming to heat_risk_dashboard.v1.schema.json.

    Parameters
    ----------
    temperature_df, green_cover_df : connector DataFrames.
    h3_resolution : H3 grid resolution.
    city_id : City identifier.
    **bbox_kwargs : lat_min, lon_min, lat_max, lon_max (used if green_cover_df is empty).
    """
    pipeline = run_heat_pipeline(
        temperature_df=temperature_df,
        green_cover_df=green_cover_df,
        h3_resolution=h3_resolution,
        city_id=city_id,
        **bbox_kwargs,
    )

    heat_cells_df: pd.DataFrame = pipeline["heat_cells"]
    dq_flag: str = pipeline["data_quality_flag"]
    city_median: float = pipeline.get("city_median_temperature_c", float("nan"))

    heat_cells_list = []
    for _, row in heat_cells_df.iterrows():
        heat_cells_list.append({
            "h3_id": row["h3_id"],
            "heat_index_c": None if pd.isna(row.get("heat_index_c")) else round(float(row["heat_index_c"]), 2),
            "uhi_intensity": None if pd.isna(row.get("uhi_intensity")) else round(float(row["uhi_intensity"]), 3),
            "green_cover_fraction": round(float(row.get("green_cover_fraction", 0.0)), 4),
            "water_proximity_score": round(float(row.get("water_proximity_score", 0.0)), 4),
            "heat_risk_score": round(float(row.get("heat_risk_score", 0.0)), 4),
        })

    _hr_thr = _rules.get("heat", "high_risk_threshold", default=0.66)
    high_risk_count = int((heat_cells_df["heat_risk_score"] >= _hr_thr).sum()) if not heat_cells_df.empty else 0

    warnings = []
    if not temperature_df.empty:
        warnings.append({
            "warning_id": "idw_interpolation_in_use",
            "severity": "info",
            "message": "Heat index values are IDW-interpolated from sparse grid points; not direct measurements.",
        })
    if dq_flag == "synthetic":
        warnings.append({
            "warning_id": "synthetic_temperature_data",
            "severity": "warning",
            "message": "Temperature data is synthetic (demo fallback). Do not use for operational heat response.",
        })

    sources = []
    if not temperature_df.empty:
        sources.append("openmeteo")
    if not green_cover_df.empty:
        sources.append("osm_via_osmnx")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "city_id": city_id,
        "h3_resolution": h3_resolution,
        "data_quality_flag": dq_flag,
        "summary": {
            "city_median_temperature_c": None if (city_median != city_median) else round(city_median, 2),
            "max_heat_risk_score": round(float(heat_cells_df["heat_risk_score"].max()), 4) if not heat_cells_df.empty else None,
            "high_risk_cell_count": high_risk_count,
            "total_cells": len(heat_cells_list),
        },
        "heat_cells": heat_cells_list,
        "active_warnings": warnings,
        "provenance_summary": {
            "sources": sources,
            "synthetic_used": dq_flag == "synthetic",
        },
    }


def build_intervention_candidates(
    temperature_df: pd.DataFrame,
    green_cover_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    top_n: int = _INTERVENTION_TOP_N,
    **bbox_kwargs: float,
) -> dict[str, Any]:
    """
    Return a dict conforming to heat_intervention_candidates.v1.schema.json.

    Top-N cells ranked by heat_risk_score descending.
    """
    pipeline = run_heat_pipeline(
        temperature_df=temperature_df,
        green_cover_df=green_cover_df,
        h3_resolution=h3_resolution,
        city_id=city_id,
        **bbox_kwargs,
    )

    heat_cells_df: pd.DataFrame = pipeline["heat_cells"]
    dq_flag: str = pipeline["data_quality_flag"]

    top_cells = (
        heat_cells_df
        .sort_values("heat_risk_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )

    candidates = []
    for _, row in top_cells.iterrows():
        risk_score = float(row.get("heat_risk_score", 0.0))
        green_deficit = float(row.get("green_deficit", 1.0 - float(row.get("green_cover_fraction", 0.0))))
        _ithr = _rules.get("heat", "intervention_thresholds", default={
            "tree_planting_min_deficit": 0.7,
            "green_roofs_min_deficit": 0.5,
            "cool_pavement_max_water_prox": 0.2,
        })
        suggestions = []
        if green_deficit > _ithr["tree_planting_min_deficit"]:
            suggestions.append("tree_planting")
            suggestions.append("shade_structures")
        if green_deficit > _ithr["green_roofs_min_deficit"]:
            suggestions.append("green_roofs")
        if float(row.get("water_proximity_score", 0.0)) < _ithr["cool_pavement_max_water_prox"]:
            suggestions.append("cool_pavement")

        candidates.append({
            "h3_id": row["h3_id"],
            "risk_score": round(risk_score, 4),
            "green_deficit": round(green_deficit, 4),
            "heat_index_c": None if pd.isna(row.get("heat_index_c")) else round(float(row["heat_index_c"]), 2),
            "uhi_intensity": None if pd.isna(row.get("uhi_intensity")) else round(float(row["uhi_intensity"]), 3),
            "water_proximity_score": round(float(row.get("water_proximity_score", 0.0)), 4),
            "suggested_interventions": suggestions,
        })

    sources = []
    if not temperature_df.empty:
        sources.append("openmeteo")
    if not green_cover_df.empty:
        sources.append("osm_via_osmnx")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "city_id": city_id,
        "h3_resolution": h3_resolution,
        "data_quality_flag": dq_flag,
        "candidates": candidates,
        "provenance_summary": {
            "sources": sources,
            "synthetic_used": dq_flag == "synthetic",
        },
    }
