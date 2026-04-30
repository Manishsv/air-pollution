from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from . import cache as cache_mod
from .config import AppConfig

logger = logging.getLogger(__name__)

DEMO_LOW_CONFIDENCE_WARNING = (
    "Sensor siting based on low-confidence/synthetic data. Use only for demonstration."
)


def _haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = np.radians(lat2.astype(float))
    dphi = np.radians(lat2.astype(float) - lat1)
    dl = np.radians(lon2.astype(float) - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dl / 2.0) ** 2
    return 2 * R * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def _normalize_01(series: pd.Series) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce").astype(float)
    lo, hi = float(x.min()), float(x.max())
    if hi <= lo or np.isnan(lo) or np.isnan(hi):
        return pd.Series(0.5, index=x.index)
    return ((x - lo) / (hi - lo)).clip(0.0, 1.0)


def _nearest_real_station_km(lat: float, lon: float, st_meta: pd.DataFrame) -> float:
    d = _haversine_km(lat, lon, st_meta["latitude"].values, st_meta["longitude"].values)
    return float(np.min(d))


def _load_real_station_meta(cfg: AppConfig) -> Tuple[Optional[pd.DataFrame], str]:
    bbox_t = None
    if cfg.bbox is not None:
        bbox_t = (cfg.bbox.south, cfg.bbox.north, cfg.bbox.west, cfg.bbox.east)
    if bbox_t is None:
        return None, "station_coords_unavailable_no_bbox_for_cache_lookup"

    pq = cache_mod.cache_path(
        cfg.data_processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "aq_stations",
        bbox=bbox_t,
        poly_hash=None,
        ext="parquet",
    )
    if not pq.exists():
        logger.warning("AQ stations cache missing for redundancy: %s", pq)
        return None, "station_cache_missing"

    df = pd.read_parquet(pq)
    if df.empty:
        return None, "station_cache_empty"

    src = df.get("data_source", pd.Series("", index=df.index)).astype(str)
    real_mask = ~(src.str.contains("synthetic", case=False, na=False))
    df = df.loc[real_mask]
    meta = df[["latitude", "longitude"]].drop_duplicates().dropna().reset_index(drop=True)
    if meta.empty:
        return None, "station_meta_no_real_stations"

    return meta, ""


def _neighbor_interpolation_fraction(h3_ids: pd.Series, interp_by_h3: Dict[str, bool]) -> pd.Series:
    gid_set = set(h3_ids.astype(str))

    def one(hid: str) -> float:
        try:
            disk = list(h3.grid_disk(str(hid), 1))
        except Exception:
            return 0.5
        near = [str(c) for c in disk if str(c) in gid_set and str(c) != str(hid)]
        if not near:
            return 0.5
        frac = np.mean([1.0 if interp_by_h3.get(c, True) else 0.0 for c in near])
        return float(np.clip(frac, 0.0, 1.0))

    return h3_ids.astype(str).map(one)


def _apply_redundancy_penalty(score: pd.Series, min_km_to_station_center: pd.Series, enabled: bool) -> pd.Series:
    if not enabled:
        return score.astype(float).copy()

    s = score.astype(float).copy()
    d = pd.to_numeric(min_km_to_station_center, errors="coerce")
    mul = np.ones(len(s), dtype=float)
    mul = np.where(d < 0.5, 0.2, mul)
    mul = np.where((d >= 0.5) & (d < 1.0), np.minimum(mul, 0.5), mul)
    return s * mul


def merge_sensor_siting_into_metrics(metrics_path: Path, summary: Dict[str, Any]) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict):
            m = {}
    else:
        m = {}

    prev = m.get("sensor_siting_summary") or {}
    if not isinstance(prev, dict):
        prev = {}
    prev.update(summary)
    m["sensor_siting_summary"] = prev
    cache_mod.save_json(m, metrics_path)


def compute_sensor_candidates(
    *,
    cfg: AppConfig,
    mode: str,
    h3_geo: gpd.GeoDataFrame,
    hotspots: pd.DataFrame,
    audit: Dict[str, Any],
    static_gdf: Optional[gpd.GeoDataFrame],
    st_meta: Optional[pd.DataFrame],
    st_meta_warning: str,
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    ss = cfg.sensor_siting

    geo = h3_geo.to_crs("EPSG:4326").drop_duplicates(subset=["h3_id"]).copy()
    gh = hotspots.copy()

    required = {"h3_id", "nearest_station_distance_km", "uncertainty_band", "forecast_pm25_mean"}
    missing_req = sorted(required.difference(set(gh.columns)))
    if missing_req:
        raise ValueError(f"hotspot rows missing columns: {missing_req}")

    g = geo.merge(gh, on="h3_id", how="left")

    if static_gdf is not None and not static_gdf.empty and "h3_id" in static_gdf.columns:
        st_cols = [c for c in static_gdf.columns if c not in ("geometry",) and not c.endswith("_sf_dup")]
        g = g.merge(static_gdf[st_cols], on="h3_id", how="left", suffixes=("", "_sf_dup"))

    aq_col = "current_pm25_source_type"
    if aq_col not in g.columns:
        aq_col = "aq_source_type" if "aq_source_type" in g.columns else None

    aq_str = g[aq_col].fillna("unavailable").astype(str).str.lower() if aq_col else pd.Series("unavailable", index=g.index)

    interp_by_h3 = dict(zip(g["h3_id"].astype(str), aq_str.ne("real")))
    pct_near_frac = pd.Series(_neighbor_interpolation_fraction(g["h3_id"], interp_by_h3), index=g.index)

    pct_near_n = _normalize_01(pct_near_frac)
    dist_raw = pd.to_numeric(g["nearest_station_distance_km"], errors="coerce").fillna(0.0)
    dist_raw = dist_raw.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    dist_n = _normalize_01(dist_raw.replace([np.inf, -np.inf], np.nan))
    unc_raw = pd.to_numeric(g["uncertainty_band"], errors="coerce").fillna(0.0)
    unc_n = _normalize_01(unc_raw)
    fc_mean = pd.to_numeric(g["forecast_pm25_mean"], errors="coerce").fillna(0.0)
    fc_n = _normalize_01(fc_mean)

    bd_n = _normalize_01(pd.to_numeric(g.get("built_up_ratio"), errors="coerce").fillna(0.0))
    poi_n = _normalize_01(pd.to_numeric(g.get("poi_count"), errors="coerce").fillna(0.0))
    road_n = _normalize_01(pd.to_numeric(g.get("road_density_km_per_sqkm"), errors="coerce").fillna(0.0))
    green_raw = pd.to_numeric(g.get("green_area_sqm"), errors="coerce").fillna(0.0)
    green_n = _normalize_01(green_raw)
    low_green_n = (1.0 - green_n).clip(0.0, 1.0)

    mk_vals: List[float] = []
    if st_meta is not None and not st_meta.empty:
        for _, r in g.iterrows():
            mk_vals.append(_nearest_real_station_km(float(r["centroid_lat"]), float(r["centroid_lon"]), st_meta))
    else:
        mk_vals = [float("nan")] * len(g)

    mk_s = pd.Series(mk_vals, index=g.index, dtype=float)
    mk_eff = mk_s.astype(float).fillna(dist_raw.astype(float))

    rd_enabled = bool(getattr(ss, "redundancy_penalty_enabled", True))

    mode_l = str(mode).lower()

    base = pd.Series(0.0, index=g.index, dtype=float)
    if mode_l == "coverage":
        base = 0.45 * dist_n + 0.35 * unc_n + 0.20 * pct_near_n
    elif mode_l == "hotspot_discovery":
        disc = aq_str.ne("real").astype(float)
        base = 0.40 * fc_n + 0.35 * unc_n + 0.25 * dist_n
        base *= 1.0 - 0.15 * aq_str.eq("real").astype(float)
        base *= np.clip(0.95 + 0.05 * disc, 0.0, 1.0)
    elif mode_l == "equity":
        base = 0.25 * bd_n + 0.20 * poi_n + 0.20 * road_n + 0.20 * low_green_n + 0.15 * unc_n
    else:
        raise ValueError(f"Unknown sensor_siting mode: {mode}")

    base = pd.to_numeric(base, errors="coerce").fillna(0.0).astype(float)

    penalized = _apply_redundancy_penalty(base, mk_eff, rd_enabled)

    if mode_l == "coverage":
        eco_series = (0.5 * dist_n + 0.5 * pct_near_n).clip(0.0, 1.0)
        eup_series = (unc_n * pct_near_n).clip(0.0, 1.0)
    elif mode_l == "hotspot_discovery":
        eco_series = fc_n.clip(0.0, 1.0)
        eup_series = (unc_n * dist_n).clip(0.0, 1.0)
    else:
        eco_series = (0.25 * bd_n + 0.20 * poi_n + 0.20 * road_n + 0.20 * low_green_n).clip(0.0, 1.0)
        eup_series = unc_n.clip(0.0, 1.0)

    thresh = float(getattr(ss, "min_distance_from_existing_station_km", 1.0) or 0.0)
    apply_spacing = bool(getattr(ss, "apply_min_spacing_if_stations_known", True))

    spacing_exclude = pd.Series(False, index=g.index)
    if apply_spacing and thresh > 0 and st_meta is not None and not st_meta.empty:
        spacing_exclude = ~(mk_eff.astype(float) >= thresh)

    synth_cells = float(audit.get("percent_cells_synthetic", 0.0) or 0.0)
    synth_sta = float(audit.get("number_of_synthetic_aq_stations", 0) or 0)
    gates_ok = bool(audit.get("recommendation_allowed", True))

    plan_conf_base = "medium"
    if synth_cells > 0 or synth_sta > 0 or not gates_ok:
        plan_conf_base = "low"

    wf_default = DEMO_LOW_CONFIDENCE_WARNING if plan_conf_base == "low" else ""

    cand = g.assign(
        _score=penalized,
        _pct_near_frac=pct_near_frac,
        _pct_near_n=pct_near_n,
        _dist_n=dist_n,
        _unc_n=unc_n,
        _fc_n=fc_n,
        eco=eco_series,
        eup=eup_series,
        _mk_eff=mk_eff,
        _spacing_exclude=spacing_exclude,
    )

    pool = cand.loc[~cand["_spacing_exclude"]].copy()
    rationale_note = "ranked_candidates"
    if pool.empty:
        pool = cand.copy()
        rationale_note = "all_candidates_within_min_spacing_fallback_no_hard_filter"

    pool = pool.sort_values("_score", ascending=False)

    top_k = max(1, int(ss.top_k))
    top = pool.head(top_k)

    geo_rows = geo.set_index("h3_id")[["geometry"]]

    patched: List[Dict[str, Any]] = []
    for rank, (_, row) in enumerate(top.iterrows(), start=1):
        hid = str(row["h3_id"])

        rationale_parts = [
            f"mode={mode_l}",
            "objective_uncertainty_reduction_or_coverage_not_most_polluted",
        ]
        if st_meta_warning:
            rationale_parts.append(st_meta_warning)
        if float(row["_pct_near_frac"]) >= 0.66:
            rationale_parts.append("neighbors_mostly_interpolated")
        rationale_str = ";".join(rationale_parts)[:1900]

        wf = wf_default or ""
        if bool(row["_spacing_exclude"]) and rank <= top_k:
            wf = ";".join(
                filter(
                    None,
                    [
                        wf,
                        (
                            DEMO_LOW_CONFIDENCE_WARNING + ";"
                            if DEMO_LOW_CONFIDENCE_WARNING not in (wf or "")
                            else ""
                        ),
                        "CANDIDATE_NEAR_EXISTING_UNDER_MIN_SPACING_KM_FALLBACK",
                    ],
                )
            ).strip("; ")

        pmcat = str(row["pm25_category_india"]) if "pm25_category_india" in row.index else ""

        patched.append(
            {
                "h3_id": hid,
                "geometry": geo_rows.loc[hid]["geometry"],
                "candidate_rank": rank,
                "siting_score": float(round(float(row["_score"]), 6)),
                "scoring_mode": mode_l,
                "expected_coverage_gain": float(round(float(row["eco"]), 6)),
                "expected_uncertainty_reduction_proxy": float(round(float(row["eup"]), 6)),
                "nearest_station_distance_km": float(pd.to_numeric(row.get("nearest_station_distance_km"), errors="coerce") or 0.0),
                "uncertainty_band": float(pd.to_numeric(row.get("uncertainty_band"), errors="coerce") or 0.0),
                "forecast_pm25_mean": float(pd.to_numeric(row.get("forecast_pm25_mean"), errors="coerce") or 0.0),
                "pm25_category_india": pmcat,
                "rationale_flags": rationale_str,
                "planning_confidence": plan_conf_base,
                "warning_flags": wf.strip("; ") if wf else "",
            }
        )

    out = gpd.GeoDataFrame(patched, geometry="geometry", crs="EPSG:4326")

    summary = {
        "mode_requested": mode_l,
        "config_default_mode": getattr(ss, "mode", ""),
        "top_k": top_k,
        "candidates_written": int(len(out)),
        "redundancy_penalty_enabled": rd_enabled,
        "min_spacing_km_threshold": thresh,
        "spatial_ranking_notes": rationale_note,
        "nearest_station_geom_source_ok": bool(st_meta is not None and not st_meta.empty),
        "planning_confidence_aggregate": plan_conf_base,
        "combined_warning_banner": DEMO_LOW_CONFIDENCE_WARNING if plan_conf_base == "low" else "",
    }
    return out, summary


def run_sensor_siting(*, cfg: AppConfig, mode_override: Optional[str] = None) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    h3_path = cfg.data_processed_dir / "h3_grid.geojson"
    hot_path = cfg.data_outputs_dir / "hotspot_recommendations.geojson"
    audit_path = cfg.data_outputs_dir / "data_audit.json"
    static_path = cfg.data_processed_dir / "static_features.geojson"

    if not h3_path.exists():
        raise FileNotFoundError(str(h3_path))
    if not hot_path.exists():
        raise FileNotFoundError(str(hot_path))

    audit: Dict[str, Any] = {}
    if audit_path.exists():
        with open(audit_path, "r", encoding="utf-8") as f:
            audit = json.load(f)

    h3_geo = gpd.read_file(h3_path)
    hotspots = gpd.read_file(hot_path)
    hotspots_df = pd.DataFrame(hotspots.drop(columns=["geometry"], errors="ignore"))

    static_df: Optional[gpd.GeoDataFrame] = None
    if static_path.exists():
        static_df = gpd.read_file(static_path)

    st_meta, st_warn = _load_real_station_meta(cfg)

    mode = mode_override or getattr(cfg.sensor_siting, "mode", "coverage")

    cand, summary = compute_sensor_candidates(
        cfg=cfg,
        mode=mode,
        h3_geo=h3_geo,
        hotspots=hotspots_df,
        audit=audit,
        static_gdf=static_df,
        st_meta=st_meta,
        st_meta_warning=st_warn,
    )

    out_path = cfg.data_outputs_dir / "sensor_siting_candidates.geojson"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cand.to_file(out_path, driver="GeoJSON")

    metrics_path = cfg.data_outputs_dir / "metrics.json"
    summary["geojson_output"] = str(out_path.resolve())
    merge_sensor_siting_into_metrics(metrics_path, summary)

    return cand, summary
