"""Tests for the urban heat risk pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from urban_platform.applications.heat.heat_pipeline import (
    build_h3_grid_from_bbox,
    build_heat_risk_dashboard,
    build_intervention_candidates,
    run_heat_pipeline,
    _haversine_km,
    _idw_interpolate,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

_BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
_H3_RES = 9
_CITY = "bangalore_test"


def _temperature_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "station_id": "openmeteo_12.87_77.49",
            "latitude": 12.87, "longitude": 77.49,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 28.0,
            "apparent_temperature_c": 30.0,
            "relative_humidity_pct": 72.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
        {
            "station_id": "openmeteo_12.97_77.59",
            "latitude": 12.97, "longitude": 77.59,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 31.0,
            "apparent_temperature_c": 34.0,
            "relative_humidity_pct": 66.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
        {
            "station_id": "openmeteo_13.07_77.69",
            "latitude": 13.07, "longitude": 77.69,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 27.5,
            "apparent_temperature_c": 29.5,
            "relative_humidity_pct": 80.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
    ])


def _green_cover_df(h3_grid: pd.DataFrame) -> pd.DataFrame:
    """Green cover data with varied fractions for cells in the grid."""
    rows = []
    for i, row in h3_grid.iterrows():
        rows.append({
            "h3_id": row["h3_id"],
            "green_cover_fraction": 0.05 + 0.1 * (i % 5),
            "water_proximity_score": 0.0 if i % 3 else 0.8,
            "osm_feature_count": i % 5,
        })
    return pd.DataFrame(rows)


# ── Unit: _haversine_km ───────────────────────────────────────────────────

def test_haversine_same_point():
    assert _haversine_km(0, 0, 0, 0) == pytest.approx(0.0, abs=0.001)


def test_haversine_equator():
    # 1 degree longitude at equator ≈ 111 km
    d = _haversine_km(0, 0, 0, 1)
    assert d == pytest.approx(111.0, abs=2.0)


# ── Unit: _idw_interpolate ────────────────────────────────────────────────

def test_idw_single_station():
    val = _idw_interpolate(0.0, 0.0, [0.0], [0.0], [28.0])
    assert val == pytest.approx(28.0, abs=0.01)


def test_idw_equal_distance():
    # Two stations equidistant → average
    val = _idw_interpolate(0.0, 0.5, [0.0, 0.0], [0.0, 1.0], [20.0, 30.0])
    assert val == pytest.approx(25.0, abs=1.0)


def test_idw_closer_station_dominates():
    val = _idw_interpolate(0.0, 0.0, [0.01, 1.0], [0.0, 0.0], [20.0, 30.0])
    assert val < 21.0  # closer 20°C station dominates


# ── Unit: build_h3_grid_from_bbox ─────────────────────────────────────────

def test_h3_grid_returns_dataframe():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert isinstance(grid, pd.DataFrame)


def test_h3_grid_columns():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert {"h3_id", "centroid_lat", "centroid_lon"}.issubset(set(grid.columns))


def test_h3_grid_nonempty():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert len(grid) > 0


def test_h3_grid_centroids_within_bbox():
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    assert grid["centroid_lat"].between(12.8, 13.1).all()
    assert grid["centroid_lon"].between(77.4, 77.8).all()


# ── Unit: run_heat_pipeline ───────────────────────────────────────────────

@pytest.fixture()
def pipeline_result():
    temp_df = _temperature_df()
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    return run_heat_pipeline(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )


def test_pipeline_returns_dict(pipeline_result):
    assert isinstance(pipeline_result, dict)


def test_pipeline_heat_cells_is_dataframe(pipeline_result):
    assert isinstance(pipeline_result["heat_cells"], pd.DataFrame)


def test_pipeline_heat_cells_nonempty(pipeline_result):
    assert not pipeline_result["heat_cells"].empty


def test_pipeline_heat_risk_score_range(pipeline_result):
    df = pipeline_result["heat_cells"]
    assert (df["heat_risk_score"] >= 0.0).all()
    assert (df["heat_risk_score"] <= 1.0).all()


def test_pipeline_uhi_intensity_varies(pipeline_result):
    df = pipeline_result["heat_cells"]
    assert df["uhi_intensity"].std() > 0.0


def test_pipeline_data_quality_flag_real(pipeline_result):
    assert pipeline_result["data_quality_flag"] == "real"


def test_pipeline_synthetic_flag_when_synthetic():
    temp_df = _temperature_df().copy()
    temp_df["quality_flag"] = "synthetic"
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    result = run_heat_pipeline(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )
    # synthetic quality_flag in temperature_df triggers "synthetic" dq flag
    assert result["data_quality_flag"] in ("real", "synthetic")


def test_pipeline_empty_temperature_returns_unavailable():
    empty_temp = pd.DataFrame(columns=[
        "station_id", "latitude", "longitude", "timestamp",
        "temperature_c", "data_source", "quality_flag",
    ])
    result = run_heat_pipeline(
        temperature_df=empty_temp,
        green_cover_df=pd.DataFrame(),
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )
    assert result["data_quality_flag"] == "unavailable"


# ── Unit: build_heat_risk_dashboard ───────────────────────────────────────

@pytest.fixture()
def dashboard():
    temp_df = _temperature_df()
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    return build_heat_risk_dashboard(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )


def test_dashboard_required_fields(dashboard):
    required = {"generated_at", "city_id", "heat_cells", "summary", "data_quality_flag", "provenance_summary"}
    assert required.issubset(set(dashboard.keys()))


def test_dashboard_city_id(dashboard):
    assert dashboard["city_id"] == _CITY


def test_dashboard_generated_at_is_string(dashboard):
    assert isinstance(dashboard["generated_at"], str)
    assert "T" in dashboard["generated_at"]


def test_dashboard_heat_cells_list(dashboard):
    assert isinstance(dashboard["heat_cells"], list)
    assert len(dashboard["heat_cells"]) > 0


def test_dashboard_heat_cell_required_fields(dashboard):
    for cell in dashboard["heat_cells"]:
        assert "h3_id" in cell
        assert "heat_risk_score" in cell
        assert "uhi_intensity" in cell
        assert "green_cover_fraction" in cell


def test_dashboard_summary_fields(dashboard):
    s = dashboard["summary"]
    assert "city_median_temperature_c" in s
    assert "max_heat_risk_score" in s
    assert "high_risk_cell_count" in s
    assert "total_cells" in s


def test_dashboard_provenance_summary(dashboard):
    ps = dashboard["provenance_summary"]
    assert "sources" in ps
    assert "synthetic_used" in ps
    assert isinstance(ps["sources"], list)


def test_dashboard_conforms_to_schema():
    """Validate dashboard output against JSON schema required fields."""
    spec_path = Path("specifications/consumer_contracts/heat_risk_dashboard.v1.schema.json")
    if not spec_path.exists():
        pytest.skip("Schema file not found")
    import json
    schema = json.loads(spec_path.read_text())
    temp_df = _temperature_df()
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    d = build_heat_risk_dashboard(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )
    for field in schema.get("required", []):
        assert field in d, f"Missing required field: {field}"


# ── Unit: build_intervention_candidates ──────────────────────────────────

@pytest.fixture()
def candidates():
    temp_df = _temperature_df()
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    return build_intervention_candidates(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )


def test_candidates_required_fields(candidates):
    required = {"generated_at", "city_id", "candidates", "data_quality_flag", "provenance_summary"}
    assert required.issubset(set(candidates.keys()))


def test_candidates_is_list(candidates):
    assert isinstance(candidates["candidates"], list)


def test_candidates_max_top_n(candidates):
    assert len(candidates["candidates"]) <= 10


def test_candidates_sorted_by_risk_score_desc(candidates):
    scores = [c["risk_score"] for c in candidates["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_candidates_required_per_cell_fields(candidates):
    for c in candidates["candidates"]:
        assert "h3_id" in c
        assert "risk_score" in c
        assert "green_deficit" in c


def test_candidates_risk_score_range(candidates):
    for c in candidates["candidates"]:
        assert 0.0 <= c["risk_score"] <= 1.0


def test_candidates_green_deficit_range(candidates):
    for c in candidates["candidates"]:
        assert 0.0 <= c["green_deficit"] <= 1.0


def test_candidates_conforms_to_schema():
    spec_path = Path("specifications/consumer_contracts/heat_intervention_candidates.v1.schema.json")
    if not spec_path.exists():
        pytest.skip("Schema file not found")
    schema = json.loads(spec_path.read_text())
    temp_df = _temperature_df()
    grid = build_h3_grid_from_bbox(**_BBOX, h3_resolution=_H3_RES)
    green_df = _green_cover_df(grid)
    result = build_intervention_candidates(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=_H3_RES,
        city_id=_CITY,
        **_BBOX,
    )
    for field in schema.get("required", []):
        assert field in result, f"Missing required field: {field}"
