"""
Tests for the OpenMeteo rainfall connector.

All tests use mock HTTP sessions — no live network calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from urban_platform.connectors.flood.openmeteo_rainfall import (
    _grid_points,
    _fetch_point,
    fetch_rainfall_observations,
    _COLUMNS,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _mock_session(payload: dict | None = None, status: int = 200) -> MagicMock:
    """Return a requests.Session-like mock."""
    resp = MagicMock()
    resp.status_code = status
    if payload is not None:
        resp.json.return_value = payload
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    if status != 200:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    session = MagicMock()
    session.get.return_value = resp
    return session


def _openmeteo_payload(times: list[str], precip: list[float]) -> dict:
    return {"hourly": {"time": times, "precipitation": precip, "rain": precip}}


_TIMES = [f"2026-05-07T0{h}:00" for h in range(6)]
_PRECIP = [0.0, 0.5, 2.0, 5.0, 12.0, 8.0]


# ── _grid_points ──────────────────────────────────────────────────────────

def test_grid_points_default_3x3():
    pts = _grid_points(12.87, 77.49, 13.07, 77.69)
    assert len(pts) == 9


def test_grid_points_corners():
    pts = _grid_points(0.0, 0.0, 1.0, 1.0)
    lats = {p[0] for p in pts}
    lons = {p[1] for p in pts}
    assert 0.0 in lats and 1.0 in lats
    assert 0.0 in lons and 1.0 in lons


def test_grid_points_n_param():
    pts = _grid_points(0.0, 0.0, 1.0, 1.0, n=2)
    assert len(pts) == 4


def test_grid_points_rounding():
    pts = _grid_points(12.87, 77.49, 13.07, 77.69)
    for lat, lon in pts:
        assert len(str(lat).split(".")[-1]) <= 5
        assert len(str(lon).split(".")[-1]) <= 5


# ── _fetch_point ─────────────────────────────────────────────────────────

def test_fetch_point_returns_one_row_per_call():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    rows = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)
    assert len(rows) == 1


def test_fetch_point_columns():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    row = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)[0]
    assert "rainfall_intensity_mm_per_hr" in row
    assert "rainfall_accumulation_3h_mm" in row
    assert row["data_source"] == "openmeteo"
    assert row["quality_flag"] == "real"


def test_fetch_point_intensity_is_latest_value():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    row = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)[0]
    assert row["rainfall_intensity_mm_per_hr"] == _PRECIP[-1]


def test_fetch_point_accumulation_is_3h_sum():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    row = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)[0]
    assert row["rainfall_accumulation_3h_mm"] == pytest.approx(sum(_PRECIP[-3:]), abs=0.01)


def test_fetch_point_network_error_returns_empty():
    sess = _mock_session(status=503)
    rows = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)
    assert rows == []


def test_fetch_point_empty_payload_returns_empty():
    sess = _mock_session({"hourly": {"time": [], "precipitation": [], "rain": []}})
    rows = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)
    assert rows == []


def test_fetch_point_station_id_encodes_coords():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    row = _fetch_point(12.87, 77.49, lookback_hours=3, session=sess)[0]
    assert "12.87" in row["station_id"]
    assert "77.49" in row["station_id"]


# ── fetch_rainfall_observations ───────────────────────────────────────────

def test_fetch_rainfall_observations_returns_dataframe():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    df = fetch_rainfall_observations(
        "test_city", 12.87, 77.49, 13.07, 77.69, session=sess
    )
    assert isinstance(df, pd.DataFrame)


def test_fetch_rainfall_observations_9_rows():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    df = fetch_rainfall_observations(
        "test_city", 12.87, 77.49, 13.07, 77.69, session=sess
    )
    assert len(df) == 9  # 3×3 grid


def test_fetch_rainfall_observations_required_columns():
    sess = _mock_session(_openmeteo_payload(_TIMES, _PRECIP))
    df = fetch_rainfall_observations(
        "test_city", 12.87, 77.49, 13.07, 77.69, session=sess
    )
    for col in _COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_fetch_rainfall_observations_network_failure_returns_empty():
    sess = _mock_session(status=500)
    df = fetch_rainfall_observations(
        "test_city", 12.87, 77.49, 13.07, 77.69, session=sess
    )
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_rainfall_observations_empty_columns_on_failure():
    sess = _mock_session(status=500)
    df = fetch_rainfall_observations(
        "test_city", 12.87, 77.49, 13.07, 77.69, session=sess
    )
    for col in _COLUMNS:
        assert col in df.columns
