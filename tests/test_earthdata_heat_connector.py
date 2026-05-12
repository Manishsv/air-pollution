"""Tests for the NASA Earthdata MODIS LST heat connector.

All tests are offline — no earthaccess / network calls are made.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from airos.drivers.connectors.heat.earthdata_lst import (
    _heat_risk,
    _make_grid,
    fetch_lst_observations,
)

# ── _heat_risk ────────────────────────────────────────────────────────────

def test_heat_risk_none_lst_returns_none():
    assert _heat_risk(None, None) is None


def test_heat_risk_25c_no_ndvi_is_zero():
    assert _heat_risk(25.0, None) == pytest.approx(0.0, abs=0.001)


def test_heat_risk_45c_no_ndvi_is_one():
    assert _heat_risk(45.0, None) == pytest.approx(1.0, abs=0.001)


def test_heat_risk_clamps_below_25c():
    assert _heat_risk(10.0, None) == pytest.approx(0.0, abs=0.001)


def test_heat_risk_clamps_above_45c():
    assert _heat_risk(60.0, None) == pytest.approx(1.0, abs=0.001)


def test_heat_risk_with_high_ndvi_lower_than_without():
    risk_no_ndvi   = _heat_risk(35.0, None)
    risk_high_ndvi = _heat_risk(35.0, 1.0)   # ndvi_score = 0 → lower heat risk
    assert risk_high_ndvi < risk_no_ndvi


def test_heat_risk_with_low_ndvi_adds_ndvi_component():
    # ndvi=0 → ndvi_score=1 → adds 0.3 × 1 to lst component
    risk_no_ndvi   = _heat_risk(35.0, None)
    risk_zero_ndvi = _heat_risk(35.0, 0.0)
    assert risk_zero_ndvi > risk_no_ndvi


def test_heat_risk_returns_float():
    result = _heat_risk(32.0, 0.3)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


# ── _make_grid ────────────────────────────────────────────────────────────

def test_make_grid_returns_list_of_tuples():
    grid = _make_grid(12.87, 77.49, 12.90, 77.52)
    assert isinstance(grid, list)
    assert all(isinstance(pt, tuple) and len(pt) == 2 for pt in grid)


def test_make_grid_nonempty_for_valid_bbox():
    grid = _make_grid(12.87, 77.49, 12.90, 77.52)
    assert len(grid) > 0


def test_make_grid_coords_within_bbox():
    lat_min, lon_min, lat_max, lon_max = 12.87, 77.49, 12.92, 77.54
    grid = _make_grid(lat_min, lon_min, lat_max, lon_max)
    for lat, lon in grid:
        assert lat_min <= lat < lat_max + 0.01
        assert lon_min <= lon < lon_max + 0.01


def test_make_grid_rounded_to_6_decimals():
    grid = _make_grid(12.87, 77.49, 12.90, 77.52)
    for lat, lon in grid:
        assert lat == round(lat, 6)
        assert lon == round(lon, 6)


# ── fetch_lst_observations (no token → empty) ─────────────────────────────

def test_fetch_returns_empty_when_no_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    df = fetch_lst_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_empty_has_correct_columns(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    df = fetch_lst_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    expected = {
        "station_id", "latitude", "longitude", "timestamp",
        "temperature_c", "apparent_temperature_c", "relative_humidity_pct",
        "lst_c", "ndvi", "heat_risk_score", "data_source", "quality_flag",
    }
    assert expected.issubset(set(df.columns))


# ── heat dispatcher routing ───────────────────────────────────────────────

def test_dispatcher_uses_openmeteo_without_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)

    called = {}

    def fake_openmeteo(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_days=1, session=None):
        called["source"] = "openmeteo"
        return pd.DataFrame()

    monkeypatch.setattr(
        "airos.drivers.connectors.heat.openmeteo.fetch_temperature_observations",
        fake_openmeteo,
    )

    from airos.drivers.connectors.heat import fetch_temperature_observations
    fetch_temperature_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert called.get("source") == "openmeteo"


def test_dispatcher_attempts_earthdata_with_token(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token-for-test")

    called = {}

    def fake_earthdata(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_days=8):
        called["source"] = "earthdata"
        return pd.DataFrame()   # empty → will fall through to openmeteo

    def fake_openmeteo(city_name, lat_min, lon_min, lat_max, lon_max,
                       lookback_days=1, session=None):
        called["fallback"] = "openmeteo"
        return pd.DataFrame()

    monkeypatch.setattr(
        "airos.drivers.connectors.heat.earthdata_lst.fetch_lst_observations",
        fake_earthdata,
    )
    monkeypatch.setattr(
        "airos.drivers.connectors.heat.openmeteo.fetch_temperature_observations",
        fake_openmeteo,
    )

    from airos.drivers.connectors import heat as heat_mod
    import importlib
    importlib.reload(heat_mod)

    heat_mod.fetch_temperature_observations("bangalore", 12.87, 77.49, 13.07, 77.69)
    assert called.get("source") == "earthdata"
