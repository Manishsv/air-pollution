from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from urban_platform.api.local import (
    get_decision_packet,
    get_decision_packets,
    get_features,
    get_observations,
    get_recommendations,
    get_source_reliability,
)


def _write_artifacts(tmp: Path) -> None:
    processed = tmp / "data" / "processed"
    outputs = tmp / "data" / "outputs"
    processed.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)

    fs = pd.DataFrame(
        {
            "grid_id": ["a", "a", "b"],
            "timestamp": [pd.NaT, pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T00:00:00Z")],
            "feature_name": ["road_density_km_per_sqkm", "current_pm25", "temperature_2m"],
            "value": ["1.0", "50.0", "25.0"],
            "unit": ["", "", "°C"],
            "source": ["static", "aq", "weather"],
            "confidence": [0.85, 0.8, 0.8],
            "quality_flag": ["ok", "ok", "ok"],
            "provenance": ['{"layer":"static_features"}', '{"layer":"aq_panel"}', '{"layer":"weather_hourly"}'],
        }
    )
    fs.to_parquet(processed / "feature_store.parquet", index=False)

    obs = pd.DataFrame(
        {
            "grid_id": ["a", "a"],
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T01:00:00Z")],
            "variable": ["pm25", "pm25"],
            "value": [55.0, 56.0],
            "unit": ["µg/m3", "µg/m3"],
            "source": ["openaq", "openaq"],
            "confidence": [0.8, 0.8],
            "quality_flag": ["ok", "ok"],
            "observation_id": ["obs1", "obs2"],
            "entity_id": ["s1", "s1"],
            "entity_type": ["sensor", "sensor"],
            "spatial_scope": [pd.NA, pd.NA],
            "point_lat": [12.9, 12.9],
            "point_lon": [77.6, 77.6],
        }
    )
    obs.to_parquet(processed / "observation_store.parquet", index=False)

    # recommendations geojson
    grid = gpd.GeoDataFrame(
        {
            "h3_id": ["a"],
            "centroid_lat": [0.5],
            "centroid_lon": [0.5],
            "area_sqkm": [1.0],
            "forecast_pm25_mean": [60.0],
            "recommended_action": ["Do X"],
            "confidence_score": [0.7],
            "aq_source_type": ["real"],
        },
        geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
        crs="EPSG:4326",
    )
    grid.to_file(outputs / "hotspot_recommendations.geojson", driver="GeoJSON")

    with open(outputs / "data_audit.json", "w", encoding="utf-8") as f:
        json.dump({"recommendation_allowed": True}, f)
    with open(outputs / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"best_model": "random_forest"}, f)

    packets = [
        {
            "packet_id": "pkt_1",
            "h3_id": "a",
            "prediction": {"pm25_category_india": "poor"},
            "confidence": {"confidence_score": 0.7, "recommendation_allowed": True},
        },
        {
            "packet_id": "pkt_2",
            "h3_id": "b",
            "prediction": {"pm25_category_india": "good"},
            "confidence": {"confidence_score": 0.2, "recommendation_allowed": False},
        },
    ]
    with open(outputs / "decision_packets.json", "w", encoding="utf-8") as f:
        json.dump(packets, f)

    reliability = [
        {"entity_id": "s1", "entity_type": "sensor", "variable": "pm25", "source": "openaq", "status": "healthy", "reliability_score": 0.9},
        {"entity_id": "s2", "entity_type": "sensor", "variable": "pm25", "source": "openaq", "status": "offline", "reliability_score": 0.1},
    ]
    with open(outputs / "source_reliability.json", "w", encoding="utf-8") as f:
        json.dump(reliability, f)


def test_get_features_returns_long_form(tmp_path: Path):
    _write_artifacts(tmp_path)
    df = get_features(base_dir=tmp_path)
    assert not df.empty
    for c in ["grid_id", "timestamp", "feature_name", "value", "source", "confidence", "quality_flag", "provenance"]:
        assert c in df.columns


def test_get_observations_filter_by_variable_and_time(tmp_path: Path):
    _write_artifacts(tmp_path)
    start = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    df = get_observations(variable="pm25", start_time=start, end_time=end, base_dir=tmp_path)
    assert not df.empty
    assert (df["variable"] == "pm25").all()
    assert df["timestamp"].min() >= pd.to_datetime(start, utc=True)
    assert df["timestamp"].max() <= pd.to_datetime(end, utc=True)


def test_get_observations_reads_observation_store_first(tmp_path: Path):
    _write_artifacts(tmp_path)
    # If observation_store is preferred, pm25 value should be 55.0 from obs parquet,
    # not 50.0 from feature store fallback.
    df = get_observations(variable="pm25", grid_id="a", base_dir=tmp_path)
    assert float(df["value"].iloc[0]) == 55.0


def test_get_observations_fallback_when_missing_observation_store(tmp_path: Path):
    _write_artifacts(tmp_path)
    # Remove observation_store.parquet to trigger fallback.
    (tmp_path / "data" / "processed" / "observation_store.parquet").unlink()
    df = get_observations(variable="pm25", grid_id="a", base_dir=tmp_path)
    # fallback maps pm25 -> current_pm25 and returns string values from feature_store
    assert not df.empty
    assert (df["variable"] == "current_pm25").all()


def test_get_recommendations_returns_records_with_confidence(tmp_path: Path):
    _write_artifacts(tmp_path)
    df = get_recommendations(base_dir=tmp_path)
    assert not df.empty
    assert "recommended_action" in df.columns
    assert "confidence" in df.columns
    # provenance-ish fields where available
    assert "aq_source_type" in df.columns


def test_get_decision_packets_filters_and_get_one(tmp_path: Path):
    _write_artifacts(tmp_path)
    pkts = get_decision_packets(min_confidence=0.5, base_dir=tmp_path)
    assert len(pkts) == 1
    assert pkts[0]["packet_id"] == "pkt_1"

    pkts2 = get_decision_packets(recommendation_allowed=False, base_dir=tmp_path)
    assert len(pkts2) == 1
    assert pkts2[0]["packet_id"] == "pkt_2"

    pkts3 = get_decision_packets(category="poor", base_dir=tmp_path)
    assert len(pkts3) == 1
    assert pkts3[0]["packet_id"] == "pkt_1"

    one = get_decision_packet("pkt_2", base_dir=tmp_path)
    assert one is not None and one["packet_id"] == "pkt_2"

    missing = get_decision_packet("does_not_exist", base_dir=tmp_path)
    assert missing is None


def test_get_source_reliability_reads_and_filters(tmp_path: Path):
    _write_artifacts(tmp_path)
    df = get_source_reliability(base_dir=tmp_path)
    assert not df.empty
    df2 = get_source_reliability(status="offline", base_dir=tmp_path)
    assert len(df2) == 1
    assert df2["entity_id"].astype(str).iloc[0] == "s2"

