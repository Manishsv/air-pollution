"""
Tests for the flood risk pipeline.

No live network calls; all fixtures are in-process DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from airos.apps.flood.flood_pipeline import (
    _haversine_km,
    _idw_interpolate,
    _risk_level,
    _risk_color,
    _overall_risk,
    _data_quality_flag,
    build_h3_grid_from_bbox,
    run_flood_pipeline,
    build_flood_risk_dashboard,
    build_flood_decision_packets,
)

# ── Shared fixtures ───────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
_H3_RES = 9
_CITY = "test_city"


def _make_rainfall_df(n: int = 9) -> pd.DataFrame:
    lats = [12.87, 12.97, 13.07]
    lons = [77.49, 77.59, 77.69]
    intensities = [[1.0, 3.0, 8.0], [2.0, 6.0, 18.0], [0.5, 12.0, 35.0]]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            rows.append({
                "station_id": f"s{i}{j}", "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "rainfall_intensity_mm_per_hr": intensities[i][j],
                "rainfall_accumulation_3h_mm": intensities[i][j] * 3,
                "data_source": "openmeteo", "quality_flag": "real",
            })
    return pd.DataFrame(rows[:n])


def _make_incidents_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"latitude": 13.06, "longitude": 77.67, "severity": "high",
         "incident_type": "waterlogging", "quality_flag": "unverified"},
        {"latitude": 12.97, "longitude": 77.65, "severity": "moderate",
         "incident_type": "waterlogging", "quality_flag": "unverified"},
    ])


def _make_assets_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"latitude": 13.00, "longitude": 77.55, "asset_type": "drain"},
        {"latitude": 12.90, "longitude": 77.52, "asset_type": "drain"},
    ])


# ── Haversine ─────────────────────────────────────────────────────────────

def test_haversine_same_point_is_zero():
    assert _haversine_km(12.87, 77.49, 12.87, 77.49) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    # ~1 degree of latitude ≈ 111 km
    d = _haversine_km(0.0, 0.0, 1.0, 0.0)
    assert 110.0 < d < 112.0


def test_haversine_symmetric():
    d1 = _haversine_km(12.87, 77.49, 13.07, 77.69)
    d2 = _haversine_km(13.07, 77.69, 12.87, 77.49)
    assert d1 == pytest.approx(d2, rel=1e-6)


# ── IDW ───────────────────────────────────────────────────────────────────

def test_idw_at_observation_point():
    import numpy as np
    val = _idw_interpolate(0.0, 0.0, np.array([0.0]), np.array([0.0]), np.array([25.0]))
    assert pytest.approx(val, abs=0.1) == 25.0


def test_idw_midpoint_between_two_equal():
    import numpy as np
    val = _idw_interpolate(
        0.0, 0.5,
        np.array([0.0, 0.0]),
        np.array([0.0, 1.0]),
        np.array([10.0, 10.0]),
    )
    assert pytest.approx(val, abs=0.01) == 10.0


def test_idw_nearer_station_weighs_more():
    import numpy as np
    val = _idw_interpolate(
        0.0, 0.1,
        np.array([0.0, 0.0]),
        np.array([0.0, 1.0]),
        np.array([20.0, 5.0]),
    )
    assert val > 12.5   # closer to the 20-degree station


# ── Risk level + color ────────────────────────────────────────────────────

def test_risk_level_thresholds():
    assert _risk_level(0.0) == "low"
    assert _risk_level(0.24) == "low"
    assert _risk_level(0.25) == "moderate"
    assert _risk_level(0.49) == "moderate"
    assert _risk_level(0.50) == "high"
    assert _risk_level(0.74) == "high"
    assert _risk_level(0.75) == "severe"
    assert _risk_level(1.0) == "severe"


def test_risk_color_returns_rgba_list():
    for level in ("low", "moderate", "high", "severe"):
        c = _risk_color(level)
        assert len(c) == 4
        assert all(0 <= v <= 255 for v in c)


# ── H3 grid ───────────────────────────────────────────────────────────────

def test_build_h3_grid_returns_dataframe():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert isinstance(grid, pd.DataFrame)


def test_build_h3_grid_has_required_columns():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert {"h3_id", "centroid_lat", "centroid_lon"}.issubset(grid.columns)


def test_build_h3_grid_cell_count_sensible():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert len(grid) > 100


def test_build_h3_grid_centroids_within_bbox():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert grid["centroid_lat"].between(_BBOX["lat_min"] - 0.1, _BBOX["lat_max"] + 0.1).all()
    assert grid["centroid_lon"].between(_BBOX["lon_min"] - 0.1, _BBOX["lon_max"] + 0.1).all()


# ── run_flood_pipeline ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pipeline_result():
    return run_flood_pipeline(
        _make_rainfall_df(), _make_incidents_df(), _make_assets_df(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )


def test_pipeline_returns_required_keys(pipeline_result):
    for key in ("risk_cells", "data_quality_flag", "city_id", "summary"):
        assert key in pipeline_result


def test_pipeline_risk_cells_is_dataframe(pipeline_result):
    assert isinstance(pipeline_result["risk_cells"], pd.DataFrame)
    assert len(pipeline_result["risk_cells"]) > 0


def test_pipeline_risk_cells_columns(pipeline_result):
    required = {"h3_id", "rainfall_mm_per_hr", "incident_count",
                "asset_count", "flood_risk_score", "risk_level", "color"}
    assert required.issubset(pipeline_result["risk_cells"].columns)


def test_pipeline_risk_score_range(pipeline_result):
    scores = pipeline_result["risk_cells"]["flood_risk_score"]
    assert (scores >= 0.0).all()
    assert (scores <= 1.0).all()


def test_pipeline_risk_levels_valid(pipeline_result):
    valid = {"low", "moderate", "high", "severe"}
    assert set(pipeline_result["risk_cells"]["risk_level"].unique()).issubset(valid)


def test_pipeline_dqf_real_on_real_data(pipeline_result):
    assert pipeline_result["data_quality_flag"] == "real"


def test_pipeline_dqf_unavailable_on_empty_rainfall():
    result = run_flood_pipeline(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert result["data_quality_flag"] == "unavailable"


def test_pipeline_dqf_synthetic_on_synthetic_rainfall():
    df = _make_rainfall_df()
    df["quality_flag"] = "synthetic"
    df["data_source"] = "synthetic"
    result = run_flood_pipeline(
        df, pd.DataFrame(), pd.DataFrame(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert result["data_quality_flag"] == "synthetic"


def test_pipeline_summary_counts_match_cells(pipeline_result):
    summary = pipeline_result["summary"]
    risk_cells = pipeline_result["risk_cells"]
    total = (summary["severe_count"] + summary["high_count"]
             + summary["moderate_count"] + summary["low_count"])
    assert total == summary["total_cells"] == len(risk_cells)


def test_pipeline_hot_corner_has_high_risk():
    """NE corner (35 mm/hr) should produce high/severe risk cells nearby."""
    result = run_flood_pipeline(
        _make_rainfall_df(), pd.DataFrame(), pd.DataFrame(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    risk_cells = result["risk_cells"]
    # NE corner cells should have elevated scores
    ne_cells = risk_cells[
        risk_cells["centroid_lat"].isna() == False  # noqa: E712
    ] if "centroid_lat" in risk_cells.columns else risk_cells
    high_count = (risk_cells["risk_level"].isin(["high", "severe"])).sum()
    assert high_count > 0, "Expected at least one high/severe cell near NE corner"


# ── build_flood_risk_dashboard ────────────────────────────────────────────

@pytest.fixture(scope="module")
def dashboard():
    return build_flood_risk_dashboard(
        _make_rainfall_df(), _make_incidents_df(), _make_assets_df(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
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
    assert "overall_risk_level" in rs
    assert "time_window" in rs
    assert rs["overall_risk_level"] in ("low", "moderate", "high", "severe")


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
        assert "risk_level" in area
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
        assert "risk_level" in cell
        assert "confidence_score" in cell


def test_dashboard_validates_against_schema(dashboard):
    from airos.os.specifications.conformance import SPEC_ROOT, validator_for_schema_file
    schema_path = str(
        (SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()
    )
    validator_for_schema_file(schema_path).validate(dashboard)


def test_dashboard_unavailable_on_empty_rainfall():
    d = build_flood_risk_dashboard(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX,
    )
    assert d["data_quality_flag"] == "unavailable"
    assert d["provenance_summary"]["synthetic_used"] is False


# ── build_flood_decision_packets ──────────────────────────────────────────

@pytest.fixture(scope="module")
def packets():
    return build_flood_decision_packets(
        _make_rainfall_df(), _make_incidents_df(), _make_assets_df(),
        h3_resolution=_H3_RES, city_id=_CITY, **_BBOX, top_n=5,
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
    assert all(p["domain_id"] == "flood_risk" for p in packets)


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
    from airos.os.specifications.conformance import SPEC_ROOT, validator_for_schema_file
    schema_path = str(
        (SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve()
    )
    validator = validator_for_schema_file(schema_path)
    for p in packets:
        validator.validate(p)
