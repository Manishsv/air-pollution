"""Tests for the OpenMeteo heat connector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from urban_platform.connectors.heat.openmeteo import (
    _grid_points,
    fetch_temperature_observations,
)

# ── Grid points ────────────────────────────────────────────────────────────

def test_grid_points_returns_n_squared():
    pts = _grid_points(10.0, 20.0, 12.0, 22.0, n=3)
    assert len(pts) == 9


def test_grid_points_corners_included():
    pts = _grid_points(10.0, 20.0, 12.0, 22.0, n=3)
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    assert min(lats) == pytest.approx(10.0, abs=0.01)
    assert max(lats) == pytest.approx(12.0, abs=0.01)
    assert min(lons) == pytest.approx(20.0, abs=0.01)
    assert max(lons) == pytest.approx(22.0, abs=0.01)


def test_grid_points_n2_returns_four():
    pts = _grid_points(0.0, 0.0, 1.0, 1.0, n=2)
    assert len(pts) == 4


# ── Happy-path fetch ───────────────────────────────────────────────────────

def _make_openmeteo_response(lat: float, lon: float) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": ["2026-05-07T00:00", "2026-05-07T01:00"],
            "temperature_2m": [28.5, 29.1],
            "apparent_temperature": [31.0, 32.2],
            "relative_humidity_2m": [70, 68],
        },
    }


def _mock_session(responses: list[dict]) -> MagicMock:
    """Build a requests.Session mock returning successive JSON payloads."""
    session = MagicMock(spec=requests.Session)
    resp_mocks = []
    for data in responses:
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = data
        resp_mocks.append(r)
    session.get.side_effect = resp_mocks
    return session


def test_fetch_returns_dataframe():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)  # 3x3 grid = 9 calls
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        lookback_days=1,
        session=session,
    )
    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_fetch_dataframe_columns():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    expected_cols = {
        "station_id", "latitude", "longitude", "timestamp",
        "temperature_c", "apparent_temperature_c", "relative_humidity_pct",
        "data_source", "quality_flag",
    }
    assert expected_cols.issubset(set(df.columns))


def test_fetch_data_source_is_openmeteo():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert (df["data_source"] == "openmeteo").all()


def test_fetch_station_id_format():
    data = _make_openmeteo_response(12.87, 77.49)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert df["station_id"].str.startswith("openmeteo_").all()


def test_fetch_temperature_values_numeric():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert pd.to_numeric(df["temperature_c"], errors="coerce").notna().all()


def test_fetch_timestamp_ends_with_z():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert df["timestamp"].str.endswith("Z").all()


# ── Empty-on-failure path ─────────────────────────────────────────────────

def test_fetch_empty_on_network_error():
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.exceptions.ConnectionError("timeout")
    df = fetch_temperature_observations(
        city_name="offline_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_empty_on_http_error():
    session = MagicMock(spec=requests.Session)
    r = MagicMock()
    r.raise_for_status.side_effect = requests.exceptions.HTTPError("503")
    session.get.return_value = r
    df = fetch_temperature_observations(
        city_name="http_error_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_empty_df_has_correct_columns():
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.exceptions.ConnectionError("timeout")
    df = fetch_temperature_observations(
        city_name="offline_city",
        lat_min=0.0, lon_min=0.0, lat_max=1.0, lon_max=1.0,
        session=session,
    )
    expected_cols = [
        "station_id", "latitude", "longitude", "timestamp",
        "temperature_c", "apparent_temperature_c", "relative_humidity_pct",
        "data_source", "quality_flag",
    ]
    assert list(df.columns) == expected_cols


# ── Record count ──────────────────────────────────────────────────────────

def test_fetch_record_count_is_grid_times_hours():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)  # 9 grid points, 2 hours each
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert len(df) == 9 * 2  # 9 points × 2 time steps


def test_fetch_humidity_is_float():
    data = _make_openmeteo_response(12.97, 77.59)
    session = _mock_session([data] * 9)
    df = fetch_temperature_observations(
        city_name="test_city",
        lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69,
        session=session,
    )
    assert df["relative_humidity_pct"].dtype in (float, "float64")
