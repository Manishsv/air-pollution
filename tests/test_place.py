from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from airos.drivers.place.schema import Ward
from airos.drivers.place.ward_registry import load_wards, _synthetic_grid
from airos.drivers.place.h3_to_ward import assign_wards
from airos.drivers.place.ward_aggregator import _aggregate, _weighted_qol


# ── Ward ──────────────────────────────────────────────────────────────────

def test_ward_to_geojson_feature():
    w = Ward(
        ward_id="w1", city_id="bangalore_demo",
        name="Ward 1 (South West)",
        coordinates=[[77.49, 12.87], [77.54, 12.87], [77.54, 12.92], [77.49, 12.92], [77.49, 12.87]],
    )
    feat = w.to_geojson_feature()
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["ward_id"] == "w1"


# ── Ward registry ─────────────────────────────────────────────────────────

def test_load_wards_bangalore_returns_20():
    wards = load_wards("bangalore_demo")
    assert len(wards) == 20


def test_load_wards_delhi_returns_20():
    wards = load_wards("delhi_demo")
    assert len(wards) == 20


def test_load_wards_unknown_city_returns_empty():
    wards = load_wards("no_such_city_xyz")
    assert wards == []


def test_synthetic_grid_ward_ids_unique():
    wards = _synthetic_grid("bangalore_demo", 12.87, 77.49, 13.07, 77.69)
    ids = [w.ward_id for w in wards]
    assert len(ids) == len(set(ids))


def test_synthetic_grid_coordinates_are_closed_rings():
    wards = _synthetic_grid("bangalore_demo", 12.87, 77.49, 13.07, 77.69)
    for w in wards:
        assert w.coordinates[0] == w.coordinates[-1], f"Ring not closed for {w.ward_id}"


# ── H3 to ward ────────────────────────────────────────────────────────────

def _make_cells(h3_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"h3_id": h3_ids})


def test_assign_wards_empty_cells():
    wards = load_wards("bangalore_demo")
    result = assign_wards(pd.DataFrame(), wards)
    assert result.empty


def test_assign_wards_empty_wards():
    cells = _make_cells(["8a283082a657fff"])
    result = assign_wards(cells, [])
    assert result["ward_id"].iloc[0] == "unassigned"


def test_assign_wards_bangalore_cells_get_ward():
    import h3
    # Generate H3 cells from known points inside Bangalore bbox
    latlons = [(12.97, 77.59), (12.90, 77.52), (13.00, 77.65)]
    cell_ids = [h3.latlng_to_cell(lat, lon, 9) for lat, lon in latlons]
    cells = _make_cells(cell_ids)
    wards = load_wards("bangalore_demo")
    result = assign_wards(cells, wards)
    assert "ward_id" in result.columns
    assert "ward_name" in result.columns
    assigned = result[result["ward_id"] != "unassigned"]
    assert not assigned.empty


# ── Ward aggregator ───────────────────────────────────────────────────────

@pytest.fixture
def cross_domain_cells() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "h3_id": "fake_h3_01", "ward_id": "bangalore_demo_w01", "ward_name": "Ward 1",
            "flood_risk_score": 0.7, "aqi_score": 0.6, "heat_risk_score": 0.5,
            "composite_risk_score": 0.6, "elevated_domain_count": 3,
        },
        {
            "h3_id": "fake_h3_02", "ward_id": "bangalore_demo_w01", "ward_name": "Ward 1",
            "flood_risk_score": 0.4, "aqi_score": 0.3, "heat_risk_score": 0.2,
            "composite_risk_score": 0.3, "elevated_domain_count": 0,
        },
        {
            "h3_id": "fake_h3_03", "ward_id": "bangalore_demo_w02", "ward_name": "Ward 2",
            "flood_risk_score": 0.1, "aqi_score": 0.1, "heat_risk_score": 0.1,
            "composite_risk_score": 0.1, "elevated_domain_count": 0,
        },
    ])


def test_aggregate_produces_one_row_per_ward(cross_domain_cells):
    result = _aggregate(cross_domain_cells, ["flood", "air", "heat"], "2026-05-07T10:00", "bangalore_demo")
    assert len(result) == 2
    assert set(result["ward_id"]) == {"bangalore_demo_w01", "bangalore_demo_w02"}


def test_aggregate_qol_index_in_range(cross_domain_cells):
    result = _aggregate(cross_domain_cells, ["flood", "air", "heat"], "2026-05-07T10:00", "bangalore_demo")
    assert result["qol_index"].between(0.0, 1.0).all()


def test_aggregate_sorted_worst_first(cross_domain_cells):
    result = _aggregate(cross_domain_cells, ["flood", "air", "heat"], "2026-05-07T10:00", "bangalore_demo")
    assert result["qol_index"].iloc[0] <= result["qol_index"].iloc[-1]


def test_weighted_qol_all_domains():
    qol = _weighted_qol(0.8, 0.6, 0.7, ["flood", "air", "heat"])
    assert qol is not None
    assert 0.0 <= qol <= 1.0


def test_weighted_qol_partial_domains():
    qol = _weighted_qol(0.5, None, None, ["flood"])
    assert qol is not None
    assert abs(qol - 0.5) < 0.01


def test_weighted_qol_no_domains():
    qol = _weighted_qol(None, None, None, [])
    assert qol is None
