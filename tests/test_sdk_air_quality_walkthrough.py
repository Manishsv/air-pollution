"""
SDK walkthrough tests for the air quality use case.

Validates the public SDK surface, app descriptor safety gates, consumer
contract schemas, and pipeline output structure — no live network calls.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import urban_platform.sdk as sdk
from urban_platform.applications.air.air_pipeline import (
    build_h3_grid_from_bbox,
    build_air_quality_dashboard,
    build_air_quality_decision_packets,
)

# ── Shared fixtures ───────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
_H3_RES = 9
_CITY = "bangalore_test"


def _aq_df() -> pd.DataFrame:
    lats = [12.87, 12.97, 13.07]
    lons = [77.49, 77.59, 77.69]
    pm25_vals = [
        [145.0, 95.0, 65.0],
        [110.0, 75.0, 45.0],
        [80.0,  50.0, 25.0],
    ]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            rows.append({
                "station_id": f"s{i}{j}", "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "pm25_ugm3": pm25_vals[i][j],
                "pm10_ugm3": pm25_vals[i][j] * 1.6,
                "european_aqi": None,
                "data_source": "openmeteo_aq", "quality_flag": "real",
            })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def h3_grid():
    return build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)


@pytest.fixture(scope="module")
def dashboard():
    return build_air_quality_dashboard(
        aq_df=_aq_df(),
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )


@pytest.fixture(scope="module")
def packets():
    return build_air_quality_decision_packets(
        aq_df=_aq_df(),
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
        top_n=5,
    )


# ── 1. Platform inventory ─────────────────────────────────────────────────

def test_sdk_app_ids_includes_air_quality():
    assert "air_quality_review" in sdk.list_app_ids()


def test_sdk_air_quality_consumer_contract_keys_present():
    keys = sdk.list_contract_keys()
    assert "consumer_air_quality_dashboard" in keys
    assert "consumer_air_quality_decision_packet" in keys


# ── 2. App descriptor & safety gates ──────────────────────────────────────

def test_app_descriptor_review_support_only():
    descriptor = sdk.get_app_descriptor("air_quality_review")
    assert descriptor["safety"]["review_support_only"] is True


def test_app_descriptor_human_review_required():
    descriptor = sdk.get_app_descriptor("air_quality_review")
    assert descriptor["safety"]["human_review_required"] is True


def test_app_descriptor_blocked_uses_nonempty():
    descriptor = sdk.get_app_descriptor("air_quality_review")
    assert len(descriptor["safety"]["blocked_uses"]) > 0


def test_app_descriptor_blocked_uses_contains_advisory():
    descriptor = sdk.get_app_descriptor("air_quality_review")
    blocked = " ".join(descriptor["safety"]["blocked_uses"])
    assert "advisory" in blocked or "health" in blocked or "cpcb" in blocked.lower()


def test_app_descriptor_domain_is_air_quality():
    descriptor = sdk.get_app_descriptor("air_quality_review")
    assert descriptor.get("domain_id") == "air_quality"


# ── 3. Contract schemas ───────────────────────────────────────────────────

def test_dashboard_schema_required_fields():
    schema = sdk.get_contract_schema("consumer_air_quality_dashboard")
    required = schema.get("required", [])
    for field in ["generated_at", "risk_summary", "map_layers", "risk_areas",
                  "active_warnings", "data_quality_summary",
                  "recommended_review_queue", "provenance_summary"]:
        assert field in required, f"{field} not in required"


def test_decision_packet_schema_required_fields():
    schema = sdk.get_contract_schema("consumer_air_quality_decision_packet")
    required = schema.get("required", [])
    for field in ["packet_id", "domain_id", "aqi_assessment", "evidence",
                  "safety_gates", "blocked_uses", "field_verification_required"]:
        assert field in required, f"{field} not in required"


def test_dashboard_schema_additional_properties_true():
    schema = sdk.get_contract_schema("consumer_air_quality_dashboard")
    assert schema.get("additionalProperties") is True


# ── 4. H3 grid ────────────────────────────────────────────────────────────

def test_h3_grid_is_dataframe(h3_grid):
    assert isinstance(h3_grid, pd.DataFrame)


def test_h3_grid_required_columns(h3_grid):
    assert {"h3_id", "centroid_lat", "centroid_lon"}.issubset(h3_grid.columns)


def test_h3_grid_cell_count(h3_grid):
    assert len(h3_grid) > 100


# ── 5. Dashboard output ───────────────────────────────────────────────────

def test_dashboard_required_fields_present(dashboard):
    for field in ["generated_at", "city_id", "risk_summary", "map_layers",
                  "risk_areas", "active_warnings", "data_quality_summary",
                  "recommended_review_queue", "provenance_summary"]:
        assert field in dashboard, f"Missing: {field}"


def test_dashboard_city_id(dashboard):
    assert dashboard["city_id"] == _CITY


def test_dashboard_risk_cells_is_list(dashboard):
    assert isinstance(dashboard.get("risk_cells"), list)
    assert len(dashboard["risk_cells"]) > 0


def test_dashboard_risk_areas_min_one(dashboard):
    assert len(dashboard["risk_areas"]) >= 1


def test_dashboard_data_quality_flag_valid(dashboard):
    assert dashboard["data_quality_flag"] in ("real", "synthetic", "unavailable")


def test_dashboard_provenance_sources_list(dashboard):
    assert isinstance(dashboard["provenance_summary"]["sources"], list)


def test_dashboard_generated_at_is_iso(dashboard):
    assert "T" in dashboard["generated_at"]


# ── 6. Decision packets ───────────────────────────────────────────────────

def test_packets_required_fields(packets):
    for p in packets:
        for field in ["packet_id", "domain_id", "timestamp", "h3_id",
                      "aqi_assessment", "evidence", "safety_gates",
                      "blocked_uses", "field_verification_required"]:
            assert field in p, f"Missing: {field}"


def test_packets_sorted_desc(packets):
    scores = [p["confidence"]["confidence_score"] for p in packets]
    assert scores == sorted(scores, reverse=True)


def test_packets_max_5(packets):
    assert len(packets) <= 5


def test_packets_domain_id(packets):
    assert all(p["domain_id"] == "air_quality" for p in packets)


def test_packets_recommendation_blocked(packets):
    assert all(p["confidence"]["recommendation_allowed"] is False for p in packets)


def test_packets_field_verification_required(packets):
    assert all(p["field_verification_required"] is True for p in packets)


# ── 7. Safety gate conformance ────────────────────────────────────────────

def test_dashboard_unavailable_on_empty_aq():
    d = build_air_quality_dashboard(
        aq_df=pd.DataFrame(columns=[
            "station_id", "latitude", "longitude", "timestamp",
            "pm25_ugm3", "pm10_ugm3", "european_aqi",
            "data_source", "quality_flag",
        ]),
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )
    assert d["data_quality_flag"] == "unavailable"


def test_dashboard_synthetic_flag_on_synthetic_input():
    df = _aq_df().copy()
    df["quality_flag"] = "synthetic"
    d = build_air_quality_dashboard(
        aq_df=df, h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert d["data_quality_flag"] == "synthetic"
    assert d["provenance_summary"]["synthetic_used"] is True


def test_dashboard_warnings_list(dashboard):
    assert isinstance(dashboard.get("active_warnings", []), list)
    assert len(dashboard["active_warnings"]) >= 1


# ── 8. Walkthrough script runs end-to-end ─────────────────────────────────

def test_walkthrough_script_runs():
    script = Path("examples/sdk/air_quality_walkthrough.py")
    assert script.exists(), "Walkthrough script not found"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Walkthrough failed:\n{result.stderr}"
    assert "Walkthrough complete" in result.stdout
