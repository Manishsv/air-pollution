from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from urban_platform.sdk import UrbanPlatformClient


def _write_sdk_artifacts(tmp: Path) -> None:
    (tmp / "data" / "outputs").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "processed").mkdir(parents=True, exist_ok=True)

    packets = [
        {
            "packet_id": "pkt_1",
            "h3_id": "a",
            "confidence_level": "high",
            "actionability_level": "operational",
            "prediction": {"pm25_category_india": "poor", "forecast_pm25_mean": 80.0},
            "confidence": {"confidence_score": 0.9, "recommendation_allowed": True},
        },
        {
            "packet_id": "pkt_2",
            "h3_id": "b",
            "confidence_level": "low",
            "actionability_level": "verify_only",
            "prediction": {"pm25_category_india": "good", "forecast_pm25_mean": 10.0},
            "confidence": {"confidence_score": 0.2, "recommendation_allowed": False},
        },
    ]
    with open(tmp / "data" / "outputs" / "decision_packets.json", "w", encoding="utf-8") as f:
        json.dump(packets, f)

    with open(tmp / "data" / "outputs" / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"best_model": "random_forest", "target_col": "pm25_t_plus_12h"}, f)
    with open(tmp / "data" / "outputs" / "data_audit.json", "w", encoding="utf-8") as f:
        json.dump({"number_of_real_aq_stations": 3, "percent_cells_interpolated": 90.0, "recommendation_allowed": True}, f)

    # feature/observation stores minimal
    fs = pd.DataFrame(
        {
            "grid_id": ["a"],
            "timestamp": [pd.NaT],
            "feature_name": ["road_density_km_per_sqkm"],
            "value": ["1.0"],
            "unit": [""],
            "source": ["static"],
            "confidence": [0.85],
            "quality_flag": ["ok"],
            "provenance": ["{}"],
        }
    )
    fs.to_parquet(tmp / "data" / "processed" / "feature_store.parquet", index=False)

    obs = pd.DataFrame(
        {
            "grid_id": ["a"],
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z")],
            "variable": ["pm25"],
            "value": [50.0],
            "unit": ["µg/m3"],
            "source": ["openaq"],
            "confidence": [0.8],
            "quality_flag": ["ok"],
            "observation_id": ["o1"],
            "entity_id": ["s1"],
            "entity_type": ["sensor"],
            "spatial_scope": [pd.NA],
            "point_lat": [0.5],
            "point_lon": [0.5],
        }
    )
    obs.to_parquet(tmp / "data" / "processed" / "observation_store.parquet", index=False)

    reliability = [
        {"entity_id": "s1", "entity_type": "sensor", "variable": "pm25", "source": "openaq", "status": "healthy", "reliability_score": 0.9},
        {"entity_id": "s2", "entity_type": "sensor", "variable": "pm25", "source": "openaq", "status": "offline", "reliability_score": 0.1},
    ]
    with open(tmp / "data" / "outputs" / "source_reliability.json", "w", encoding="utf-8") as f:
        json.dump(reliability, f)


def test_sdk_client_filters_and_loads(tmp_path: Path):
    _write_sdk_artifacts(tmp_path)
    c = UrbanPlatformClient(base_path=str(tmp_path))

    all_pkts = c.get_decision_packets()
    assert len(all_pkts) == 2

    poor = c.get_decision_packets(category="poor")
    assert len(poor) == 1 and poor[0]["packet_id"] == "pkt_1"

    hi = c.get_decision_packets(confidence_level="high")
    assert len(hi) == 1 and hi[0]["packet_id"] == "pkt_1"

    op = c.get_decision_packets(actionability_level="operational")
    assert len(op) == 1 and op[0]["packet_id"] == "pkt_1"

    m = c.get_metrics()
    assert m.get("best_model") == "random_forest"

    a = c.get_data_audit()
    assert int(a.get("number_of_real_aq_stations")) == 3

    missing = c.get_decision_packet("does_not_exist")
    assert missing is None

    rel = c.get_source_reliability(status="offline")
    assert len(rel) == 1
    assert rel["entity_id"].astype(str).iloc[0] == "s2"

