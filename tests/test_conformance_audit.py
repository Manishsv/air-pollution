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
from urban_platform.specifications.audit import run_conformance_audit


@pytest.fixture
def aq_packet_dict() -> dict:
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
            "forecast_pm25_p90": [85.0],
            "forecast_pm25_std": [10.0],
            "uncertainty_band": [30.0],
            "pm25_category_india": ["poor"],
            "confidence_score": [0.2],
            "data_quality_score": [0.3],
            "driver_confidence": ["low"],
            "recommendation_allowed": [False],
            "recommendation_block_reason": ["demo"],
            "likely_contributing_factors": ["unknown"],
            "recommended_action": ["demo"],
            "review_questions": [["q"]],
            "review_steps": [["s"]],
            "when_not_to_act": [["n"]],
            "geometry": [Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )
    feature_store = pd.DataFrame(
        {
            "grid_id": ["a", "a"],
            "timestamp": [pd.NaT, ts],
            "feature_name": ["road_density", "current_pm25"],
            "value": ["1.0", "50.0"],
            "unit": ["", "µg/m3"],
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


def _write_min_outputs(tmp_path: Path, *, packet: dict) -> None:
    out = tmp_path / "data" / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "decision_packets.json", "w", encoding="utf-8") as f:
        json.dump([packet], f, allow_nan=False)

    # Minimal valid artifacts (same shape as existing conformance tests)
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
        "avg_cell_area_sqkm": 0.74,
        "number_of_cells": 50,
        "number_of_real_stations": 3,
        "station_density_per_100_sqkm": 0.4,
        "avg_cells_per_station": 12.0,
        "resolution_warning": "",
        "resolution_assessment": {"warning": ""},
        "recommended_resolution": 8,
    }
    with open(out / "scale_analysis.json", "w", encoding="utf-8") as f:
        json.dump(scale, f)


def test_conformance_report_is_generated(tmp_path: Path, aq_packet_dict: dict):
    _write_min_outputs(tmp_path, packet=aq_packet_dict)
    report = run_conformance_audit(tmp_path)
    path = tmp_path / "data" / "outputs" / "conformance_report.json"
    assert path.exists()
    assert "results" in report
    assert len(report["results"]) > 0


def test_valid_artifacts_pass(tmp_path: Path, aq_packet_dict: dict):
    _write_min_outputs(tmp_path, packet=aq_packet_dict)
    report = run_conformance_audit(tmp_path)
    results = report["results"]

    # Key artifact checks should be valid
    def row(artifact_or_api: str, schema_name: str) -> dict:
        for r in results:
            if r["artifact_or_api"] == artifact_or_api and r["schema_name"] == schema_name:
                return r
        raise AssertionError(f"Missing row for {artifact_or_api} {schema_name}")

    assert row(str(tmp_path / "data" / "outputs" / "decision_packets.json"), "decision_packets")["status"] == "valid"
    assert row(f"{tmp_path / 'data' / 'outputs' / 'decision_packets.json'}#items", "decision_packet_air_quality")["status"] == "valid"
    assert row(str(tmp_path / "data" / "outputs" / "data_audit.json"), "data_audit")["status"] == "valid"
    assert row(str(tmp_path / "data" / "outputs" / "metrics.json"), "metrics")["status"] == "valid"


def test_intentionally_invalid_packet_fails_with_useful_error(tmp_path: Path, aq_packet_dict: dict):
    bad = deepcopy(aq_packet_dict)
    bad["prediction"] = {"forecast_pm25_mean": 1.0}  # missing required AQ keys
    _write_min_outputs(tmp_path, packet=bad)
    report = run_conformance_audit(tmp_path)

    # Find the item-level AQ validation row
    rows = [r for r in report["results"] if r["artifact_or_api"].endswith("decision_packets.json#items") and r["schema_name"] == "decision_packet_air_quality"]
    assert rows, "Expected AQ item-level validation row"
    r = rows[0]
    assert r["status"] == "invalid"
    assert r["error_count"] >= 1
    assert any("prediction" in (e.get("path") or "") or "required property" in (e.get("message") or "") for e in r["errors"])


def test_sdk_response_validation_works_for_one_api(tmp_path: Path, aq_packet_dict: dict):
    _write_min_outputs(tmp_path, packet=aq_packet_dict)
    report = run_conformance_audit(tmp_path)
    rows = [r for r in report["results"] if r["artifact_or_api"] == "api:get_decision_packets()" and r["schema_name"] == "decision_packets"]
    assert rows
    assert rows[0]["status"] == "valid"

