from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from urban_platform.decision_support.explainability import build_decision_packets, sanitize_for_json
from urban_platform.sdk.client import UrbanPlatformClient
from urban_platform.specifications.runtime_validation import validate_artifact, validate_output_artifacts


@pytest.fixture
def aq_packet_dict():
    ts = pd.Timestamp(datetime(2026, 1, 1, 0, tzinfo=timezone.utc))
    recs = gpd.GeoDataFrame(
        {
            "h3_id": ["a"],
            "timestamp": [ts],
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
            "confidence_score": [0.3],
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
            "warning_flags": ["SYNTHETIC_AQ_USED"],
            "likely_contributing_factors": ["insufficient_evidence"],
            "recommended_action": ["Blocked"],
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
    metrics = {"best_model": "random_forest", "all_models": {"random_forest": {"RMSE": 9.0}}}
    packets = build_decision_packets(recs, feature_store, obs_store, audit, metrics, 5)
    return sanitize_for_json(packets[0])


def test_valid_air_quality_packet_passes_core_and_profile(aq_packet_dict):
    c = validate_artifact("urban_decision_packet_core", aq_packet_dict)
    p = validate_artifact("decision_packet_air_quality", aq_packet_dict)
    assert c["status"] == "valid"
    assert p["status"] == "valid"


def test_packet_missing_aq_fields_passes_core_fails_profile(aq_packet_dict):
    slim = deepcopy(aq_packet_dict)
    slim["prediction"] = {"forecast_pm25_mean": 1.0}  # missing required AQ profile keys
    c = validate_artifact("urban_decision_packet_core", slim)
    p = validate_artifact("decision_packet_air_quality", slim)
    assert c["status"] == "valid"
    assert p["status"] == "invalid"
    assert p["error_count"] >= 1


def test_validate_output_artifacts_writes_conformance_report(tmp_path: Path, aq_packet_dict):
    out = tmp_path / "data" / "outputs"
    out.mkdir(parents=True)

    with open(out / "decision_packets.json", "w", encoding="utf-8") as f:
        json.dump([aq_packet_dict], f, allow_nan=False)

    audit = {
        "number_of_real_aq_stations": 3,
        "number_of_synthetic_aq_stations": 0,
        "aq_observation_count": 100,
        "aq_completeness_ratio": 0.9,
        "percent_cells_with_observed_aq": 20.0,
        "percent_cells_interpolated": 70.0,
        "percent_cells_synthetic": 10.0,
        "avg_nearest_station_distance_km": 5.0,
        "max_nearest_station_distance_km": 12.0,
        "weather_source_type_counts": {"real": 500},
        "fire_source_type_counts": {"unavailable": 500},
        "osm_feature_counts": {"grid_cells": 50},
        "h3_resolution": 8,
        "avg_h3_cell_area_sqkm": 0.74,
        "warning_flags": [],
        "recommendation_allowed": True,
        "recommendation_block_reason": "",
        "source_reliability_summary": {"healthy_count": 2, "degraded_count": 0, "suspect_count": 0, "offline_count": 0},
        "interpolation_quality_score": 0.3,
        "low_quality_observation_ratio": 0.05,
    }
    with open(out / "data_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f)

    from urban_platform.common.provenance_summary import build_provenance_summary

    metrics = {
        "best_model": "random_forest",
        "best_metrics": {"RMSE": 9.0},
        "all_models": {"random_forest": {"RMSE": 9.0}},
        "target_col": "pm25_t_plus_12h",
        "data_audit": audit,
        "provenance_summary": build_provenance_summary({}, audit),
    }
    with open(out / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f)

    rel = [
        {
            "entity_id": "s1",
            "entity_type": "sensor",
            "variable": "pm25",
            "source": "openaq",
            "status": "healthy",
            "reliability_score": 0.95,
            "last_seen": "2026-01-01T00:00:00+00:00",
            "observation_count": 24,
            "expected_observation_count": 24.0,
            "completeness_ratio": 1.0,
            "stale_hours": 0.5,
            "flatline_detected": False,
            "impossible_value_detected": False,
            "spike_detected": False,
            "duplicate_timestamp_ratio": 0.0,
            "peer_disagreement_score": 0.0,
            "reliability_issues": "",
            "point_lat": 12.9,
            "point_lon": 77.6,
        }
    ]
    with open(out / "source_reliability.json", "w", encoding="utf-8") as f:
        json.dump(rel, f)

    scale = {
        "h3_resolution": 8,
        "avg_cell_area_sqkm": 1.0,
        "number_of_cells": 2,
        "number_of_real_stations": 2,
        "station_density_per_100_sqkm": 1.0,
        "avg_cells_per_station": 1.0,
        "resolution_warning": "",
        "resolution_assessment": {"warning": ""},
        "recommended_resolution": 8,
    }
    with open(out / "scale_analysis.json", "w", encoding="utf-8") as f:
        json.dump(scale, f)

    report = validate_output_artifacts(tmp_path)
    assert report["artifacts"]["decision_packets"]["status"] == "valid"
    assert report["artifacts"]["decision_packets"]["core_schema_status"] == "valid"
    assert report["artifacts"]["decision_packets"]["profile_schema_status"] == "valid"

    cr_path = out / "conformance_report.json"
    assert cr_path.is_file()
    loaded = json.loads(cr_path.read_text(encoding="utf-8"))
    assert loaded["artifacts"]["metrics"]["status"] == "valid"


def test_sdk_reads_conformance_report(tmp_path: Path, aq_packet_dict):
    validate_output_artifacts(tmp_path)
    c = UrbanPlatformClient(base_path=str(tmp_path))
    r = c.get_conformance_report()
    assert r.get("validated_at")
    assert "artifacts" in r
    assert c.get_spec_manifest().get("spec_version") == "v1"
    vr = c.validate_artifact("urban_decision_packet_core", aq_packet_dict)
    assert vr["status"] == "valid"
