from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from urban_platform.common.provenance_summary import build_provenance_summary
from urban_platform.decision_support.explainability import build_decision_packets, sanitize_for_json
from urban_platform.specifications.conformance import (
    assert_conforms,
    iter_manifest_schema_paths,
    load_manifest,
    schema_dir,
    validator_for_schema_file,
)
from src.scale_analysis import analyze_h3_resolution


def test_manifest_paths_exist():
    for _name, path in iter_manifest_schema_paths():
        assert path.is_file(), f"Missing schema file: {path}"


def test_manifest_lists_known_artifacts():
    m = load_manifest()
    names = set((m.get("artifacts") or {}).keys())
    assert "urban_decision_packet_core" in names
    assert "decision_packet_air_quality" in names
    assert "decision_packet" in names
    assert "data_audit" in names
    assert "metrics" in names


def test_minimal_provenance_summary():
    prov = build_provenance_summary(
        {"provenance_low_confidence_ratio": 12.5},
        {
            "percent_cells_interpolated": 10.0,
            "percent_cells_synthetic": 0.0,
            "number_of_real_aq_stations": 4,
            "avg_nearest_station_distance_km": 3.0,
            "recommendation_allowed": True,
            "recommendation_block_reason": "",
        },
    )
    assert_conforms(prov, schema_name="provenance_summary")


def test_minimal_data_audit():
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
        "source_reliability_summary": {
            "healthy_count": 2,
            "degraded_count": 0,
            "suspect_count": 0,
            "offline_count": 0,
        },
        "interpolation_quality_score": 0.3,
        "low_quality_observation_ratio": 0.05,
    }
    assert_conforms(audit, schema_name="data_audit")


def test_minimal_metrics():
    audit = {
        "percent_cells_interpolated": 0.0,
        "percent_cells_synthetic": 0.0,
        "number_of_real_aq_stations": 2,
        "avg_nearest_station_distance_km": 4.0,
        "recommendation_allowed": True,
        "recommendation_block_reason": "",
    }
    metrics = {
        "best_model": "random_forest",
        "best_metrics": {"RMSE": 9.0},
        "all_models": {"persistence": {"RMSE": 10.0}, "random_forest": {"RMSE": 9.0}},
        "target_col": "pm25_t_plus_12h",
        "data_audit": audit,
        "provenance_summary": build_provenance_summary({}, audit),
    }
    assert_conforms(metrics, schema_name="metrics")


def test_scale_analysis_from_analyzer():
    # Omit ``h3_resolution`` column: ``analyze_h3_resolution`` uses ``getattr(..., "h3_resolution")``;
    # a per-row Series makes ``int(series or -1)`` ambiguous.
    grid = gpd.GeoDataFrame(
        {"h3_id": ["a", "b"], "area_sqkm": [1.0, 1.0]},
        geometry=[Polygon([(0, 0), (0, 0.1), (0.1, 0.1), (0.1, 0)])] * 2,
        crs="EPSG:4326",
    )
    stations = pd.DataFrame(
        {
            "station_id": ["s1", "s2"],
            "data_source": ["openaq", "openaq"],
        }
    )
    scale = analyze_h3_resolution(grid, stations)
    assert_conforms(scale, schema_name="scale_analysis")


def test_source_reliability_file_shape():
    rows = [
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
    assert_conforms(rows, schema_name="source_reliability")


@pytest.fixture
def sample_decision_packet_dict():
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


def test_decision_packet_from_builder(sample_decision_packet_dict):
    assert_conforms(sample_decision_packet_dict, schema_name="decision_packet_air_quality")
    assert_conforms(sample_decision_packet_dict, schema_name="decision_packet")
    assert_conforms(sample_decision_packet_dict, schema_name="urban_decision_packet_core")


def test_decision_packets_array_schema(sample_decision_packet_dict):
    path = schema_dir("v1") / "decision_packets.schema.json"
    v = validator_for_schema_file(str(path))
    v.validate([sample_decision_packet_dict])


def test_serialized_roundtrip_strict_json(sample_decision_packet_dict):
    raw = json.dumps(sample_decision_packet_dict, allow_nan=False)
    back = json.loads(raw)
    assert_conforms(back, schema_name="decision_packet_air_quality")
    assert_conforms(back, schema_name="urban_decision_packet_core")
