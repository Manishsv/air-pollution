from __future__ import annotations

from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from urban_platform.decision_support.explainability import build_decision_packets, sanitize_for_json


def test_build_decision_packets_structure_and_guidance():
    ts = pd.Timestamp(datetime(2026, 1, 1, 0, tzinfo=timezone.utc))
    recs = gpd.GeoDataFrame(
        {
            "h3_id": ["a"],
            "timestamp": [ts],
            # omit centroids to exercise geometry fallback
            "centroid_lat": [pd.NA],
            "centroid_lon": [pd.NA],
            "current_pm25": [50.0],
            "forecast_pm25_mean": [70.0],
            "forecast_pm25_p10": [55.0],
            "forecast_pm25_p50": [70.0],
            "forecast_pm25_p90": [90.0],
            "forecast_pm25_std": [8.0],
            "uncertainty_band": [35.0],
            "pm25_category_india": ["poor"],
            "confidence_score": [0.3],  # low confidence
            "data_quality_score": [0.4],
            "driver_confidence": ["low"],
            "recommendation_allowed": [False],
            "recommendation_block_reason": ["Synthetic data used"],
            "aq_source_type": ["synthetic"],
            "weather_source_type": ["real"],
            "fire_source_type": ["unavailable"],
            "interpolation_method": [""],
            "nearest_station_distance_km": [12.0],
            "station_count_used": [1],
            "warning_flags": ["SYNTHETIC_AQ_USED; FAR_FROM_STATIONS"],
            "likely_contributing_factors": ["insufficient_evidence"],
            "recommended_action": ["No operational recommendation: blocked"],
        },
        geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
        crs="EPSG:4326",
    )

    feature_store = pd.DataFrame(
        {
            "grid_id": ["a", "a"],
            "timestamp": [pd.NaT, ts],
            "feature_name": ["road_density_km_per_sqkm", "current_pm25"],
            "value": ["1.0", "50.0"],
            "unit": ["", ""],
            "source": ["static", "aq"],
            "confidence": [0.85, 0.8],
            "quality_flag": ["ok", "synthetic"],
            "provenance": ["{}", "{}"],
        }
    )

    obs_store = pd.DataFrame(
        {
            "grid_id": ["a"],
            "timestamp": [ts],
            "variable": ["pm25"],
            "value": [50.0],
            "unit": ["µg/m3"],
            "source": ["openaq"],
            "confidence": [0.1],
            "quality_flag": ["synthetic"],
            "observation_id": ["obs1"],
            "entity_id": ["s1"],
            "entity_type": ["sensor"],
            "spatial_scope": [pd.NA],
            "point_lat": [0.6],
            "point_lon": [0.6],
        }
    )

    audit = {"number_of_real_aq_stations": 1, "percent_cells_interpolated": 90.0, "percent_cells_synthetic": 10.0, "avg_nearest_station_distance_km": 12.0}
    metrics = {"best_model": "random_forest", "all_models": {"persistence": {"RMSE": 10.0}, "random_forest": {"RMSE": 9.0}}}

    packets = build_decision_packets(recommendations_gdf=recs, feature_store_df=feature_store, observation_store_df=obs_store, data_audit=audit, metrics=metrics, top_n_features=5)
    assert isinstance(packets, list) and len(packets) == 1
    pkt = packets[0]

    for k in ["packet_id", "event_id", "h3_id", "timestamp", "location", "prediction", "confidence", "provenance", "evidence", "review_guidance", "audit_context"]:
        assert k in pkt

    assert "confidence_score" in pkt["confidence"]
    assert "aq_source_type" in pkt["provenance"]
    assert "static_features" in pkt["evidence"]
    assert "dynamic_features" in pkt["evidence"]

    # centroid computed from geometry
    assert float(pkt["location"]["centroid_lat"]) == 0.5
    assert float(pkt["location"]["centroid_lon"]) == 0.5

    # strict-JSON safe (no NaN/inf)
    cleaned = sanitize_for_json(pkt)
    import json as _json

    _json.dumps(cleaned, allow_nan=False)

    # human-readable interpretation fields
    assert pkt["confidence_level"] in {"low", "medium", "high"}
    assert isinstance(pkt["actionability_level"], str) and pkt["actionability_level"]
    assert isinstance(pkt["why_this_recommendation"], str) and len(pkt["why_this_recommendation"]) > 0
    assert isinstance(pkt["risk_of_error"], list)

    # no literal "nan" strings anywhere (after sanitization)
    s = _json.dumps(cleaned, allow_nan=False).lower()
    assert '"nan"' not in s

    # blocked recommendation should trigger reviewer questions
    qs = pkt["review_guidance"]["questions_for_reviewer"]
    assert any("blocked" in q.lower() for q in qs)


def test_interpolated_packet_includes_nearby_stations_and_is_strict_json():
    ts = pd.Timestamp(datetime(2026, 1, 1, 0, tzinfo=timezone.utc))
    recs = gpd.GeoDataFrame(
        {
            "h3_id": ["a"],
            "timestamp": [ts],
            "aq_source_type": ["interpolated"],
            "station_count_used": [3],
            "current_pm25": [50.0],
            "forecast_pm25_mean": [70.0],
            "pm25_category_india": ["poor"],
            "confidence_score": [0.7],
            "data_quality_score": [0.6],
            "recommendation_allowed": [True],
            "recommended_action": ["Test action"],
        },
        geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
        crs="EPSG:4326",
    )

    feature_store = pd.DataFrame(
        {
            "grid_id": ["a"],
            "timestamp": [ts],
            "feature_name": ["current_pm25"],
            "value": ["50.0"],
            "unit": [""],
            "source": ["aq"],
            "confidence": [0.8],
            "quality_flag": ["ok"],
            "provenance": ["{}"],
        }
    )

    # two stations with coordinates and latest pm25 readings
    obs_store = pd.DataFrame(
        {
            "grid_id": ["x", "y"],
            "timestamp": [ts, ts],
            "variable": ["pm25", "pm25"],
            "value": [40.0, 45.0],
            "unit": ["µg/m3", "µg/m3"],
            "source": ["openaq", "openaq"],
            "confidence": [0.8, 0.8],
            "quality_flag": ["ok", "ok"],
            "observation_id": ["o1", "o2"],
            "entity_id": ["s1", "s2"],
            "entity_type": ["sensor", "sensor"],
            "spatial_scope": [pd.NA, pd.NA],
            "point_lat": [0.6, 0.9],
            "point_lon": [0.6, 0.9],
            "source_reliability_score": [0.9, 0.4],
            "source_reliability_status": ["healthy", "degraded"],
            "source_reliability_issues": ["", "stale_data; incomplete_data"],
        }
    )

    packets = build_decision_packets(
        recommendations_gdf=recs,
        feature_store_df=feature_store,
        observation_store_df=obs_store,
        data_audit={},
        metrics={},
        top_n_features=5,
    )
    pkt = packets[0]
    ns = pkt["evidence"]["nearby_station_records"]
    assert len(ns) > 0
    assert isinstance(ns[0]["distance_km"], float)
    assert "latest_pm25_value" in ns[0]
    assert "latest_pm25_timestamp" in ns[0]
    assert "source_reliability_score" in ns[0]
    assert "source_reliability_status" in ns[0]
    assert "source_reliability_issues" in ns[0]
    assert any("Nearby AQ source reliability is degraded" in x for x in (pkt.get("risk_of_error") or []))

    import json as _json

    _json.dumps(sanitize_for_json(pkt), allow_nan=False)

