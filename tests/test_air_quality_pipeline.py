"""
Tests for the air quality pipeline.

No live network calls; all fixtures are in-process DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from urban_platform.applications.air.air_pipeline import (
    _aqi_category,
    _aqi_color,
    _worst_category,
    _data_quality_flag,
    run_air_quality_pipeline,
    build_air_quality_dashboard,
    build_air_quality_decision_packets,
)
from urban_platform.applications.flood.flood_pipeline import (
    build_h3_grid_from_bbox,
)

# ── Shared fixtures ───────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
_H3_RES = 9
_CITY = "test_city"


def _make_aq_df(n: int = 9) -> pd.DataFrame:
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
    return pd.DataFrame(rows[:n])


# ── AQI category thresholds ───────────────────────────────────────────────

def test_aqi_category_good():
    assert _aqi_category(0.0) == "good"
    assert _aqi_category(15.0) == "good"
    assert _aqi_category(29.9) == "good"


def test_aqi_category_satisfactory():
    assert _aqi_category(30.0) == "satisfactory"
    assert _aqi_category(45.0) == "satisfactory"
    assert _aqi_category(59.9) == "satisfactory"


def test_aqi_category_moderate():
    assert _aqi_category(60.0) == "moderate"
    assert _aqi_category(75.0) == "moderate"
    assert _aqi_category(89.9) == "moderate"


def test_aqi_category_poor():
    assert _aqi_category(90.0) == "poor"
    assert _aqi_category(105.0) == "poor"
    assert _aqi_category(119.9) == "poor"


def test_aqi_category_very_poor():
    assert _aqi_category(120.0) == "very_poor"
    assert _aqi_category(185.0) == "very_poor"
    assert _aqi_category(249.9) == "very_poor"


def test_aqi_category_severe():
    assert _aqi_category(250.0) == "severe"
    assert _aqi_category(350.0) == "severe"


def test_aqi_color_returns_rgba_list():
    for cat in ("good", "satisfactory", "moderate", "poor", "very_poor", "severe"):
        c = _aqi_color(cat)
        assert len(c) == 4
        assert all(0 <= v <= 255 for v in c)


# ── run_air_quality_pipeline ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def pipeline_result():
    return run_air_quality_pipeline(
        _make_aq_df(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )


def test_pipeline_returns_required_keys(pipeline_result):
    for key in ("risk_cells", "data_quality_flag", "city_id", "summary"):
        assert key in pipeline_result


def test_pipeline_risk_cells_is_dataframe(pipeline_result):
    assert isinstance(pipeline_result["risk_cells"], pd.DataFrame)
    assert len(pipeline_result["risk_cells"]) > 0


def test_pipeline_risk_cells_columns(pipeline_result):
    required = {"h3_id", "pm25_ugm3", "aqi_score", "aqi_category", "color"}
    assert required.issubset(pipeline_result["risk_cells"].columns)


def test_pipeline_aqi_score_range(pipeline_result):
    scores = pipeline_result["risk_cells"]["aqi_score"]
    assert (scores >= 0.0).all()
    assert (scores <= 1.0).all()


def test_pipeline_aqi_categories_valid(pipeline_result):
    valid = {"good", "satisfactory", "moderate", "poor", "very_poor", "severe"}
    assert set(pipeline_result["risk_cells"]["aqi_category"].unique()).issubset(valid)


def test_pipeline_dqf_real_on_real_data(pipeline_result):
    assert pipeline_result["data_quality_flag"] == "real"


def test_pipeline_dqf_unavailable_on_empty_aq():
    result = run_air_quality_pipeline(
        pd.DataFrame(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert result["data_quality_flag"] == "unavailable"


def test_pipeline_dqf_synthetic_on_synthetic_aq():
    df = _make_aq_df()
    df["quality_flag"] = "synthetic"
    df["data_source"] = "synthetic"
    result = run_air_quality_pipeline(
        df, h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert result["data_quality_flag"] == "synthetic"


def test_pipeline_summary_counts_match_cells(pipeline_result):
    summary = pipeline_result["summary"]
    risk_cells = pipeline_result["risk_cells"]
    total = (
        summary["severe_count"] + summary["very_poor_count"] + summary["poor_count"]
        + summary["moderate_count"] + summary["satisfactory_count"] + summary["good_count"]
    )
    assert total == summary["total_cells"] == len(risk_cells)


def test_pipeline_high_pm25_corner_has_poor_aqi():
    """SW corner (145 µg/m³) should produce poor/very_poor AQI cells nearby."""
    result = run_air_quality_pipeline(
        _make_aq_df(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    risk_cells = result["risk_cells"]
    poor_count = (risk_cells["aqi_category"].isin(["poor", "very_poor", "severe"])).sum()
    assert poor_count > 0, "Expected at least one poor+ AQI cell near SW corner"


# ── build_air_quality_dashboard ───────────────────────────────────────────

@pytest.fixture(scope="module")
def dashboard():
    return build_air_quality_dashboard(
        _make_aq_df(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )


def test_dashboard_required_fields(dashboard):
    required = [
        "generated_at", "city_id", "risk_summary", "map_layers",
        "risk_areas", "active_warnings", "data_quality_summary",
        "recommended_review_queue", "provenance_summary",
    ]
    for field in required:
        assert field in dashboard, f"Missing: {field}"


def test_dashboard_city_id(dashboard):
    assert dashboard["city_id"] == _CITY


def test_dashboard_risk_summary_required_fields(dashboard):
    rs = dashboard["risk_summary"]
    assert "overall_aqi_category" in rs
    assert "time_window" in rs
    assert rs["overall_aqi_category"] in (
        "good", "satisfactory", "moderate", "poor", "very_poor", "severe"
    )


def test_dashboard_map_layers_min_one(dashboard):
    assert len(dashboard["map_layers"]) >= 1
    for layer in dashboard["map_layers"]:
        assert "layer_id" in layer
        assert "layer_type" in layer
        assert "title" in layer


def test_dashboard_risk_areas_min_one(dashboard):
    assert len(dashboard["risk_areas"]) >= 1
    for area in dashboard["risk_areas"]:
        assert "area_id" in area
        assert "aqi_category" in area
        assert "confidence_score" in area


def test_dashboard_active_warnings_nonempty(dashboard):
    assert isinstance(dashboard["active_warnings"], list)
    assert len(dashboard["active_warnings"]) >= 1
    for w in dashboard["active_warnings"]:
        assert "warning_id" in w
        assert "severity" in w
        assert "message" in w


def test_dashboard_data_quality_summary(dashboard):
    dqs = dashboard["data_quality_summary"]
    assert "synthetic_data_used" in dqs
    assert "confidence_note" in dqs
    assert isinstance(dqs["synthetic_data_used"], bool)


def test_dashboard_provenance_summary(dashboard):
    ps = dashboard["provenance_summary"]
    assert "sources" in ps and isinstance(ps["sources"], list)
    assert "synthetic_used" in ps and isinstance(ps["synthetic_used"], bool)


def test_dashboard_risk_cells_present(dashboard):
    assert "risk_cells" in dashboard
    assert len(dashboard["risk_cells"]) > 0
    for cell in dashboard["risk_cells"]:
        assert "h3_id" in cell
        assert "aqi_category" in cell
        assert "confidence_score" in cell


def test_dashboard_validates_against_schema(dashboard):
    from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
    schema_path = str(
        (SPEC_ROOT / "consumer_contracts" / "air_quality_dashboard.v1.schema.json").resolve()
    )
    validator_for_schema_file(schema_path).validate(dashboard)


def test_dashboard_unavailable_on_empty_aq():
    d = build_air_quality_dashboard(
        pd.DataFrame(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert d["data_quality_flag"] == "unavailable"
    assert d["provenance_summary"]["synthetic_used"] is False


# ── build_air_quality_decision_packets ───────────────────────────────────

@pytest.fixture(scope="module")
def packets():
    return build_air_quality_decision_packets(
        _make_aq_df(), h3_resolution=_H3_RES, city_id=_CITY, **_BBOX, top_n=5,
    )


def test_packets_returns_list(packets):
    assert isinstance(packets, list)
    assert len(packets) > 0


def test_packets_max_top_n(packets):
    assert len(packets) <= 5


def test_packets_sorted_descending(packets):
    scores = [p["confidence"]["confidence_score"] for p in packets]
    assert scores == sorted(scores, reverse=True)


def test_packets_domain_id(packets):
    assert all(p["domain_id"] == "air_quality" for p in packets)


def test_packets_recommendation_always_blocked(packets):
    assert all(p["confidence"]["recommendation_allowed"] is False for p in packets)


def test_packets_field_verification_required(packets):
    assert all(p["field_verification_required"] is True for p in packets)


def test_packets_safety_gates_min_one(packets):
    assert all(len(p["safety_gates"]) >= 1 for p in packets)


def test_packets_have_h3_id(packets):
    for p in packets:
        assert "h3_id" in p
        assert len(p["h3_id"]) > 0


def test_packets_review_guidance_present(packets):
    for p in packets:
        rg = p["review_guidance"]
        assert "review_prompts" in rg and len(rg["review_prompts"]) > 0
        assert "when_not_to_act" in rg and len(rg["when_not_to_act"]) > 0


def test_packets_validate_against_schema(packets):
    from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
    schema_path = str(
        (SPEC_ROOT / "consumer_contracts" / "air_quality_decision_packet.v1.schema.json").resolve()
    )
    validator = validator_for_schema_file(schema_path)
    for p in packets:
        validator.validate(p)
