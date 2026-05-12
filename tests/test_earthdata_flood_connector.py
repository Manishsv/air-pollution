"""Tests for the NASA Earthdata GPM IMERG flood connector.

All tests are offline — no earthaccess / network calls are made.
"""
from __future__ import annotations

import pandas as pd
import pytest

from airos.drivers.connectors.flood.earthdata_flood import (
    _flood_risk,
    _make_grid,
    fetch_rainfall_observations,
)

# ── _flood_risk ───────────────────────────────────────────────────────────

def test_flood_risk_zero_rain_sea_level_is_max_terrain():
    # 0 mm rain → rain_score=0; 0m elev → terrain_score=1 → risk = 0.4
    assert _flood_risk(0.0, 0.0) == pytest.approx(0.4, abs=0.001)


def test_flood_risk_50mm_rain_sea_level_is_one():
    assert _flood_risk(50.0, 0.0) == pytest.approx(1.0, abs=0.001)


def test_flood_risk_high_elevation_reduces_terrain_component():
    risk_low  = _flood_risk(30.0, 0.0)
    risk_high = _flood_risk(30.0, 300.0)
    assert risk_high < risk_low


def test_flood_risk_clamps_at_one():
    assert _flood_risk(100.0, 0.0) == pytest.approx(1.0, abs=0.001)


def test_flood_risk_clamps_at_zero():
    # 0 mm rain + very high elevation → floor at 0
    assert _flood_risk(0.0, 500.0) == pytest.approx(0.0, abs=0.001)


def test_flood_risk_returns_float():
    result = _flood_risk(25.0, 50.0)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


# ── _make_grid ────────────────────────────────────────────────────────────

def test_make_grid_returns_list_of_tuples():
    grid = _make_grid(12.87, 77.49, 12.97, 77.59)
    assert isinstance(grid, list)
    assert all(isinstance(pt, tuple) and len(pt) == 2 for pt in grid)


def test_make_grid_nonempty():
    grid = _make_grid(12.87, 77.49, 12.97, 77.59)
    assert len(grid) > 0


def test_make_grid_step_is_01():
    # With 0.1° step, a 0.2° bbox should have ~3 points per axis
    grid = _make_grid(12.0, 77.0, 12.2, 77.2)
    lats = sorted({pt[0] for pt in grid})
    assert len(lats) >= 3


def test_make_grid_coords_rounded():
    grid = _make_grid(12.87, 77.49, 12.97, 77.59)
    for lat, lon in grid:
        assert lat == round(lat, 4)
        assert lon == round(lon, 4)


# ── fetch_rainfall_observations (no token → empty) ────────────────────────

def test_fetch_returns_empty_when_no_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    df = fetch_rainfall_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_empty_has_correct_columns(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    df = fetch_rainfall_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    expected = {
        "station_id", "latitude", "longitude", "timestamp",
        "rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm",
        "elevation_m", "jrc_water_occurrence",
        "flood_risk_score", "data_source", "quality_flag",
    }
    assert expected.issubset(set(df.columns))


# ── flood dispatcher routing ──────────────────────────────────────────────

def test_dispatcher_uses_openmeteo_without_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)

    called = {}

    def fake_openmeteo(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_hours=3, session=None):
        called["source"] = "openmeteo"
        return pd.DataFrame()

    monkeypatch.setattr(
        "airos.drivers.connectors.flood.openmeteo_rainfall.fetch_rainfall_observations",
        fake_openmeteo,
    )

    from airos.drivers.connectors.flood import fetch_rainfall_observations as dispatch
    dispatch("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert called.get("source") == "openmeteo"


def test_dispatcher_attempts_earthdata_with_token(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token-for-test")

    called = {}

    def fake_earthdata(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_hours=3):
        called["source"] = "earthdata"
        return pd.DataFrame()   # empty → will fall through to openmeteo

    def fake_openmeteo(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_hours=3, session=None):
        called["fallback"] = "openmeteo"
        return pd.DataFrame()

    monkeypatch.setattr(
        "airos.drivers.connectors.flood.earthdata_flood.fetch_rainfall_observations",
        fake_earthdata,
    )
    monkeypatch.setattr(
        "airos.drivers.connectors.flood.openmeteo_rainfall.fetch_rainfall_observations",
        fake_openmeteo,
    )

    from airos.drivers.connectors import flood as flood_mod
    import importlib
    importlib.reload(flood_mod)

    flood_mod.fetch_rainfall_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert called.get("source") == "earthdata"
