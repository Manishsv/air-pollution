from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from urban_platform.common.provenance_summary import build_provenance_summary


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively replace NaN/inf with None so output is strict JSON.
    """
    # floats / numpy scalars
    try:
        if isinstance(obj, (float, np.floating)):
            return obj if np.isfinite(float(obj)) else None
    except Exception:
        pass
    # pandas missing
    try:
        if obj is pd.NA:
            return None
    except Exception:
        pass
    if obj is None:
        return None
    if isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    # timestamps and other objects
    try:
        if isinstance(obj, (pd.Timestamp,)):
            return str(pd.to_datetime(obj, utc=True))
    except Exception:
        pass
    return obj


def _packet_id(h3_id: str, ts: pd.Timestamp) -> str:
    raw = f"{h3_id}|{str(pd.to_datetime(ts, utc=True))}"
    return "pkt_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _event_id(h3_id: str, ts: pd.Timestamp) -> str:
    raw = f"event|{h3_id}|{str(pd.to_datetime(ts, utc=True))}"
    return "evt_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _as_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if np.isfinite(v):
            return v
        return float(default)
    except Exception:
        return float(default)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _json_safe(obj: Any) -> Any:
    try:
        json.dumps(obj, default=str)
        return obj
    except Exception:
        return str(obj)


def _feature_records(feature_store_df: pd.DataFrame, *, grid_id: str, ts: Optional[pd.Timestamp], names: Optional[list[str]] = None, window_minutes: int = 90) -> list[dict]:
    if feature_store_df is None or feature_store_df.empty:
        return []
    fs = feature_store_df.copy()
    fs["timestamp"] = pd.to_datetime(fs["timestamp"], utc=True, errors="coerce")
    fs = fs[fs["grid_id"].astype(str) == str(grid_id)].copy()
    if names is not None:
        fs = fs[fs["feature_name"].astype(str).isin([str(n) for n in names])].copy()
    if ts is None:
        fs = fs[fs["timestamp"].isna()].copy()
    else:
        lo = pd.to_datetime(ts, utc=True) - timedelta(minutes=int(window_minutes))
        hi = pd.to_datetime(ts, utc=True) + timedelta(minutes=int(window_minutes))
        fs = fs[fs["timestamp"].between(lo, hi)].copy()
        # choose closest per feature
        fs["dt_abs"] = (fs["timestamp"] - pd.to_datetime(ts, utc=True)).abs()
        fs = fs.sort_values(["feature_name", "dt_abs"]).drop_duplicates(subset=["feature_name"], keep="first").drop(columns=["dt_abs"])

    out = []
    for r in fs.itertuples(index=False):
        val = getattr(r, "value")
        if isinstance(val, str) and val.strip().lower() == "nan":
            val = None
        out.append(
            {
                "feature_name": str(getattr(r, "feature_name")),
                "value": val,
                "unit": str(getattr(r, "unit", "")),
                "source": str(getattr(r, "source", "")),
                "confidence": _as_float(getattr(r, "confidence", 0.0), 0.0),
                "quality_flag": str(getattr(r, "quality_flag", "")),
                "provenance": str(getattr(r, "provenance", "")),
            }
        )
    return out


def _observation_records(observation_store_df: pd.DataFrame, *, grid_id: str, variable: str, ts: pd.Timestamp, window_minutes: int = 90) -> list[dict]:
    if observation_store_df is None or observation_store_df.empty:
        return []
    od = observation_store_df.copy()
    od["timestamp"] = pd.to_datetime(od["timestamp"], utc=True, errors="coerce")
    lo = pd.to_datetime(ts, utc=True) - timedelta(minutes=int(window_minutes))
    hi = pd.to_datetime(ts, utc=True) + timedelta(minutes=int(window_minutes))
    od = od[(od["grid_id"].astype(str) == str(grid_id)) & (od["variable"].astype(str) == str(variable)) & (od["timestamp"].between(lo, hi))].copy()
    if od.empty:
        return []
    # keep closest few
    od["dt_abs"] = (od["timestamp"] - pd.to_datetime(ts, utc=True)).abs()
    od = od.sort_values("dt_abs").head(10).drop(columns=["dt_abs"])
    keep = ["timestamp", "value", "unit", "source", "quality_flag", "confidence", "observation_id", "entity_id", "entity_type", "point_lat", "point_lon"]
    keep = [c for c in keep if c in od.columns]
    return [{k: _json_safe(getattr(r, k)) for k in keep} for r in od.itertuples(index=False)]


def _nearest_station_records(observation_store_df: pd.DataFrame, *, centroid_lat: float, centroid_lon: float, ts: pd.Timestamp, k: int = 5) -> list[dict]:
    if observation_store_df is None or observation_store_df.empty:
        return []
    od = observation_store_df.copy()
    od["timestamp"] = pd.to_datetime(od["timestamp"], utc=True, errors="coerce")
    # station points are entity_type=sensor and variable=pm25
    m = (od.get("entity_type", "").astype(str).str.lower() == "sensor") & (od.get("variable", "").astype(str) == "pm25")
    od = od[m].dropna(subset=["point_lat", "point_lon", "entity_id"]).copy()
    if od.empty:
        return []
    # de-dup per station; choose nearest-time record for name/source/quality
    od["dt_abs"] = (od["timestamp"] - pd.to_datetime(ts, utc=True)).abs()
    od = od.sort_values(["entity_id", "dt_abs"]).drop_duplicates(subset=["entity_id"], keep="first").drop(columns=["dt_abs"])
    od["distance_km"] = od.apply(lambda r: _haversine_km(centroid_lat, centroid_lon, float(r["point_lat"]), float(r["point_lon"])), axis=1)
    od = od.sort_values("distance_km").head(int(k))
    out = []
    for r in od.itertuples(index=False):
        latest_ts = getattr(r, "timestamp", pd.NaT)
        latest_val = getattr(r, "value", np.nan)
        rel_score = getattr(r, "source_reliability_score", np.nan)
        rel_status = getattr(r, "source_reliability_status", None)
        rel_issues = getattr(r, "source_reliability_issues", None)
        out.append(
            {
                "entity_id": str(getattr(r, "entity_id")),
                "station_name": str(getattr(r, "station_name", "")) if hasattr(r, "station_name") else "",
                "distance_km": _as_float(getattr(r, "distance_km"), 999.0),
                "source": str(getattr(r, "source", "")),
                "quality_flag": str(getattr(r, "quality_flag", "")),
                "latest_pm25_value": _as_float(latest_val, np.nan),
                "latest_pm25_timestamp": str(pd.to_datetime(latest_ts, utc=True)) if pd.notna(latest_ts) else None,
                "source_reliability_score": _as_float(rel_score, np.nan),
                "source_reliability_status": None if rel_status is None else str(rel_status),
                "source_reliability_issues": None if rel_issues is None else str(rel_issues),
                "point_lat": _as_float(getattr(r, "point_lat"), np.nan),
                "point_lon": _as_float(getattr(r, "point_lon"), np.nan),
            }
        )
    return out


def _review_guidance(*, recommendation_allowed: bool, confidence_score: float, warning_flags: str) -> dict:
    questions = []
    steps = []
    when_not_to_act = [
        "Do not act solely on synthetic data.",
        "Do not treat proxy factors as causal attribution.",
        "Do not issue enforcement action without field verification.",
    ]

    if not recommendation_allowed:
        questions.extend(
            [
                "Why was recommendation blocked?",
                "Is synthetic or insufficient data being used?",
                "Is field verification needed before any action?",
            ]
        )
        steps.extend(
            [
                "Review the data audit and provenance flags.",
                "Check whether PM2.5 values are observed or interpolated.",
                "Request field verification before any operational action.",
            ]
        )

    if confidence_score < 0.5 or ("SYNTHETIC" in (warning_flags or "").upper()):
        steps.extend(
            [
                "Check nearest station data.",
                "Verify local conditions through field staff.",
                "Review whether PM2.5 values are observed or interpolated.",
                "Check weather and wind conditions.",
            ]
        )
    else:
        steps.extend(
            [
                "Review supporting data sources.",
                "Confirm agency jurisdiction.",
                "Decide whether to issue advisory, inspection, or work order.",
            ]
        )

    if not questions:
        questions = [
            "Is the confidence and uncertainty acceptable for this type of action?",
            "Are there strong warning flags indicating sparse or synthetic data?",
            "Is field verification required before action?",
        ]

    # Deduplicate
    def _uniq(xs: list[str]) -> list[str]:
        out = []
        seen = set()
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {
        "questions_for_reviewer": _uniq(questions),
        "suggested_verification_steps": _uniq(steps),
        "when_not_to_act": when_not_to_act,
    }


def build_decision_packets(
    recommendations_gdf,
    feature_store_df: pd.DataFrame,
    observation_store_df: pd.DataFrame,
    data_audit: dict,
    metrics: dict,
    top_n_features: int = 10,
) -> list[dict]:
    """
    Build decision packets for human review. One packet per grid cell recommendation.
    """
    if recommendations_gdf is None or len(recommendations_gdf) == 0:
        return []

    gdf = recommendations_gdf.copy()
    if "timestamp" in gdf.columns:
        gdf["timestamp"] = pd.to_datetime(gdf["timestamp"], utc=True, errors="coerce")

    packets: list[dict] = []

    # Top-features from metrics (if present)
    metric_fi = None
    if isinstance(metrics, dict):
        metric_fi = metrics.get("feature_importances") or metrics.get("feature_importance") or None
    top_features_from_metrics: list[dict] = []
    if isinstance(metric_fi, dict):
        try:
            top_features_from_metrics = [{"feature": k, "importance": float(v)} for k, v in sorted(metric_fi.items(), key=lambda kv: -float(kv[1]))[: int(top_n_features)]]
        except Exception:
            top_features_from_metrics = []

    known_top_features = [
        "current_pm25",
        "pm25_lag_1h",
        "pm25_lag_3h",
        "pm25_lag_24h",
        "wind_speed_10m",
        "relative_humidity_2m",
        "road_density_km_per_sqkm",
        "built_up_ratio",
        "green_area_sqm",
        "fire_count_nearby",
    ]

    for row in gdf.itertuples(index=False):
        h3_id = str(getattr(row, "h3_id"))
        ts = getattr(row, "timestamp", pd.Timestamp.utcnow())
        ts = pd.to_datetime(ts, utc=True, errors="coerce")
        pkt_id = _packet_id(h3_id, ts)
        evt_id = _event_id(h3_id, ts)

        centroid_lat = _as_float(getattr(row, "centroid_lat", np.nan), np.nan)
        centroid_lon = _as_float(getattr(row, "centroid_lon", np.nan), np.nan)
        geom = getattr(row, "geometry", None)
        geometry_geojson = None
        if geom is not None:
            try:
                geometry_geojson = geom.__geo_interface__
            except Exception:
                geometry_geojson = None
            # Fallback centroid extraction from geometry (EPSG:4326 expected)
            try:
                if not np.isfinite(centroid_lat) or not np.isfinite(centroid_lon):
                    c = geom.centroid
                    centroid_lat = float(c.y)
                    centroid_lon = float(c.x)
            except Exception:
                pass

        confidence_score = _as_float(getattr(row, "confidence_score", 0.0), 0.0)
        data_quality_score = _as_float(getattr(row, "data_quality_score", 0.0), 0.0)
        wf_raw = getattr(row, "warning_flags", "")
        try:
            warning_flags = "" if wf_raw is None or (isinstance(wf_raw, float) and not np.isfinite(wf_raw)) or str(wf_raw).lower() == "nan" else str(wf_raw)
        except Exception:
            warning_flags = str(wf_raw or "")
        recommendation_allowed = bool(getattr(row, "recommendation_allowed", True))
        recommendation_block_reason = str(getattr(row, "recommendation_block_reason", "") or "")
        aq_source_type = str(getattr(row, "aq_source_type", "unavailable") or "unavailable")
        driver_confidence = str(getattr(row, "driver_confidence", "") or "")

        # Evidence
        observed_pm25 = _observation_records(observation_store_df, grid_id=h3_id, variable="pm25", ts=ts)
        if not observed_pm25:
            observed_pm25_note = "No direct PM2.5 observation found for this grid/timestamp."
        else:
            observed_pm25_note = ""

        nearby_stations = []
        nearby_station_note = ""
        if aq_source_type.lower() == "interpolated":
            # Determine whether station coordinates exist in observation store
            coords_available = False
            try:
                if observation_store_df is not None and not observation_store_df.empty and {"point_lat", "point_lon", "entity_id"}.issubset(set(observation_store_df.columns)):
                    tmp = observation_store_df.copy()
                    tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], utc=True, errors="coerce")
                    mm = (tmp.get("entity_type", "").astype(str).str.lower() == "sensor") & (tmp.get("variable", "").astype(str) == "pm25")
                    tmp = tmp[mm].dropna(subset=["point_lat", "point_lon", "entity_id"])
                    coords_available = len(tmp) > 0
            except Exception:
                coords_available = False

            if not coords_available:
                nearby_station_note = "No station coordinates available in observation store."
            elif np.isfinite(centroid_lat) and np.isfinite(centroid_lon):
                nearby_stations = _nearest_station_records(observation_store_df, centroid_lat=centroid_lat, centroid_lon=centroid_lon, ts=ts, k=5)
                if not nearby_stations:
                    nearby_station_note = "No nearby station records found."
            else:
                nearby_station_note = "No nearby station records found."

        weather_vars = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "precipitation"]
        weather_records = []
        for wv in weather_vars:
            recs = _observation_records(observation_store_df, grid_id=h3_id, variable=wv, ts=ts)
            if recs:
                # keep closest one per var
                weather_records.append({"variable": wv, "record": recs[0]})

        static_feature_names = [
            "road_density_km_per_sqkm",
            "building_count",
            "built_up_ratio",
            "industrial_landuse_area_sqm",
            "commercial_landuse_area_sqm",
            "residential_landuse_area_sqm",
            "green_area_sqm",
            "poi_count",
        ]
        static_features = _feature_records(feature_store_df, grid_id=h3_id, ts=None, names=static_feature_names)

        dynamic_feature_names = [
            "current_pm25",
            "pm25_lag_1h",
            "pm25_lag_3h",
            "pm25_lag_24h",
            *weather_vars,
            "fire_count_nearby",
            "distance_to_nearest_fire_km",
        ]
        dynamic_features = _feature_records(feature_store_df, grid_id=h3_id, ts=ts, names=dynamic_feature_names)

        if top_features_from_metrics:
            top_features_used = top_features_from_metrics[: int(top_n_features)]
        else:
            # Fallback: include known features if present as (name,value) using dynamic/static evidence
            avail = {d["feature_name"]: d.get("value") for d in (dynamic_features + static_features)}
            top_features_used = [{"feature": f, "value": avail.get(f)} for f in known_top_features if f in avail][: int(top_n_features)]

        # Data sources section (coarse but traceable)
        data_sources = [
            {
                "source_type": "air_quality",
                "source_name": str(getattr(row, "aq_source_type", "unavailable")),
                "source_mode": "observed" if str(getattr(row, "aq_source_type", "")).lower() == "real" else "interpolated",
                "confidence": confidence_score,
                "notes": "OpenAQ + IDW interpolation (see provenance fields)",
            },
            {
                "source_type": "weather",
                "source_name": str(getattr(row, "weather_source_type", "unavailable")),
                "source_mode": "hourly",
                "confidence": confidence_score,
                "notes": "Open-Meteo (or synthetic fallback) broadcast to grid",
            },
            {
                "source_type": "geospatial",
                "source_name": str(getattr(row, "osm_source_type", "osm")) if hasattr(row, "osm_source_type") else "osm",
                "source_mode": "static",
                "confidence": 0.85,
                "notes": "OpenStreetMap-derived static proxies",
            },
        ]

        # Audit context
        model_vs_persistence = ""
        try:
            bm = metrics.get("best_model")
            all_models = metrics.get("all_models", {}) or {}
            persist = all_models.get("persistence", {}) or {}
            best = all_models.get(bm, {}) or {}
            if best and persist:
                model_vs_persistence = f"{bm}: RMSE {best.get('RMSE'):.2f} vs persistence {persist.get('RMSE'):.2f}"
        except Exception:
            model_vs_persistence = ""

        audit_context = {
            "number_of_real_aq_stations": int(data_audit.get("number_of_real_aq_stations", 0) or 0),
            "percent_cells_interpolated": float(data_audit.get("percent_cells_interpolated", 0.0) or 0.0),
            "percent_cells_synthetic": float(data_audit.get("percent_cells_synthetic", 0.0) or 0.0),
            "avg_nearest_station_distance_km": float(data_audit.get("avg_nearest_station_distance_km", 0.0) or 0.0),
            "spatial_validation_rmse": float(metrics.get("spatial_validation_rmse", np.nan) or np.nan),
            "model_vs_persistence_summary": model_vs_persistence,
        }

        summary = f"H3 {h3_id}: {str(getattr(row, 'pm25_category_india', 'unknown'))} | action={str(getattr(row, 'recommended_action', '') or '')[:80]}"

        # --- Human-readable interpretation fields ---
        if confidence_score < 0.4:
            confidence_level = "low"
        elif confidence_score < 0.7:
            confidence_level = "medium"
        else:
            confidence_level = "high"

        if not recommendation_allowed:
            actionability_level = "blocked"
        elif confidence_level == "low":
            actionability_level = "verify_only"
        elif aq_source_type.lower() == "interpolated":
            actionability_level = "verify_only"
        elif confidence_level == "medium":
            actionability_level = "advisory"
        else:
            actionability_level = "operational"

        if actionability_level == "verify_only":
            actionability_hint = "Field verification is recommended before action."
        elif actionability_level == "advisory":
            actionability_hint = "Consider precautionary measures."
        elif actionability_level == "operational":
            actionability_hint = "Action can be taken with confidence."
        else:
            actionability_hint = "Do not act due to insufficient data."

        forecast_pm25 = _as_float(getattr(row, "forecast_pm25_mean", np.nan), np.nan)
        category = str(getattr(row, "pm25_category_india", "unknown") or "unknown")
        uncertainty_band = _as_float(getattr(row, "uncertainty_band", np.nan), np.nan)

        why_this_recommendation = (
            f"{category} PM2.5 is forecast ({forecast_pm25:.1f} µg/m³), based on {aq_source_type} data "
            f"with {confidence_level} confidence and uncertainty range of {uncertainty_band:.1f}. {actionability_hint}"
        )

        risk_of_error: list[str] = []
        if aq_source_type.lower() == "interpolated":
            risk_of_error.append("High dependence on interpolated AQ data")
        if np.isfinite(uncertainty_band) and float(uncertainty_band) > 10:
            risk_of_error.append("High forecast uncertainty")
        try:
            if float(audit_context.get("percent_cells_interpolated", 0.0) or 0.0) > 80:
                risk_of_error.append("Sparse station coverage across area")
        except Exception:
            pass
        if driver_confidence.strip().lower() == "low":
            risk_of_error.append("Contributing factors are uncertain")

        # Reliability-driven risk hints (added later once we have nearby stations)

        packet = {
            "packet_id": pkt_id,
            "event_id": evt_id,
            "h3_id": h3_id,
            "timestamp": str(pd.to_datetime(ts, utc=True)),
            "confidence_level": confidence_level,
            "actionability_level": actionability_level,
            "why_this_recommendation": why_this_recommendation,
            "risk_of_error": risk_of_error,
            "location": {
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "geometry_geojson": geometry_geojson,
            },
            "summary": summary,
            "prediction": {
                "current_pm25": _as_float(getattr(row, "current_pm25", np.nan), np.nan),
                "forecast_pm25_mean": _as_float(getattr(row, "forecast_pm25_mean", np.nan), np.nan),
                "forecast_pm25_p10": _as_float(getattr(row, "forecast_pm25_p10", np.nan), np.nan),
                "forecast_pm25_p50": _as_float(getattr(row, "forecast_pm25_p50", np.nan), np.nan),
                "forecast_pm25_p90": _as_float(getattr(row, "forecast_pm25_p90", np.nan), np.nan),
                "forecast_pm25_std": _as_float(getattr(row, "forecast_pm25_std", np.nan), np.nan),
                "uncertainty_band": _as_float(getattr(row, "uncertainty_band", np.nan), np.nan),
                "pm25_category_india": str(getattr(row, "pm25_category_india", "unknown")),
            },
            "confidence": {
                "confidence_score": confidence_score,
                "data_quality_score": data_quality_score,
                "driver_confidence": driver_confidence,
                "recommendation_allowed": recommendation_allowed,
                "recommendation_block_reason": recommendation_block_reason,
            },
            "provenance": {
                "aq_source_type": aq_source_type,
                "weather_source_type": str(getattr(row, "weather_source_type", "unavailable")),
                "fire_source_type": str(getattr(row, "fire_source_type", "unavailable")),
                "interpolation_method": str(getattr(row, "interpolation_method", "")),
                "nearest_station_distance_km": _as_float(getattr(row, "nearest_station_distance_km", np.nan), np.nan),
                "station_count_used": int(_as_float(getattr(row, "station_count_used", np.nan), 0)),
                "warning_flags": warning_flags,
                "aq_source_reliability_min": None,
                "aq_source_reliability_avg": None,
            },
            "data_sources": data_sources,
            "evidence": {
                "observed_pm25_records": observed_pm25,
                "observed_pm25_note": observed_pm25_note,
                "nearby_station_records": nearby_stations,
                "nearby_station_note": nearby_station_note,
                "weather_records": weather_records,
                "static_features": static_features,
                "dynamic_features": dynamic_features,
                "top_features_used": top_features_used,
            },
            "likely_contributing_factors": (
                [{"factor": "unknown", "reason": "insufficient data confidence"}]
                if str(getattr(row, "likely_contributing_factors", "") or "").strip() == "insufficient_evidence"
                else str(getattr(row, "likely_contributing_factors", ""))
            ),
            "recommended_action": str(getattr(row, "recommended_action", "")),
            "review_guidance": _review_guidance(
                recommendation_allowed=recommendation_allowed,
                confidence_score=confidence_score,
                warning_flags=warning_flags,
            ),
            "audit_context": audit_context,
        }
        packet["provenance_summary"] = build_provenance_summary(metrics or {}, data_audit or {})

        # Add source reliability summary counts (best-effort, platform-level)
        try:
            sr = observation_store_df.copy() if observation_store_df is not None else pd.DataFrame()
            if not sr.empty and "source_reliability_status" in sr.columns:
                aq = sr[(sr.get("entity_type", "").astype(str).str.lower() == "sensor") & (sr.get("variable", "").astype(str) == "pm25")].copy()
                wx = sr[(sr.get("entity_type", "").astype(str).str.lower() == "weather")].copy()
                packet["source_reliability_summary"] = {
                    "aq_sensor_status_counts": aq["source_reliability_status"].fillna("unknown").astype(str).value_counts().to_dict() if not aq.empty else {},
                    "weather_source_status_counts": wx["source_reliability_status"].fillna("unknown").astype(str).value_counts().to_dict() if not wx.empty else {},
                    "low_reliability_sources_nearby": [
                        s for s in (nearby_stations or [])
                        if str(s.get("source_reliability_status") or "").lower() in {"degraded", "suspect", "offline"}
                    ][:5],
                    "reliability_warnings": [],
                }
            else:
                packet["source_reliability_summary"] = {
                    "aq_sensor_status_counts": {},
                    "weather_source_status_counts": {},
                    "low_reliability_sources_nearby": [],
                    "reliability_warnings": ["AQ data source reliability is uncertain"],
                }
        except Exception:
            packet["source_reliability_summary"] = {
                "aq_sensor_status_counts": {},
                "weather_source_status_counts": {},
                "low_reliability_sources_nearby": [],
                "reliability_warnings": ["AQ data source reliability is uncertain"],
            }

        # Compute AQ source reliability aggregates from nearby stations
        try:
            scores = [float(s.get("source_reliability_score")) for s in (nearby_stations or []) if s.get("source_reliability_score") is not None and np.isfinite(float(s.get("source_reliability_score")))]
            if scores:
                packet["provenance"]["aq_source_reliability_min"] = float(min(scores))
                packet["provenance"]["aq_source_reliability_avg"] = float(sum(scores) / len(scores))
            else:
                # missing reliability
                if "AQ data source reliability is uncertain" not in risk_of_error:
                    risk_of_error.append("AQ data source reliability is uncertain")
        except Exception:
            if "AQ data source reliability is uncertain" not in risk_of_error:
                risk_of_error.append("AQ data source reliability is uncertain")

        # Add reliability warnings to risk_of_error when nearby sources are degraded/suspect/offline
        try:
            bad = any(str(s.get("source_reliability_status") or "").lower() in {"degraded", "suspect", "offline"} for s in (nearby_stations or []))
            if bad and "Nearby AQ source reliability is degraded" not in risk_of_error:
                risk_of_error.append("Nearby AQ source reliability is degraded")
        except Exception:
            pass

        packet["risk_of_error"] = risk_of_error

        packets.append(packet)

    return packets

