from __future__ import annotations

import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from urban_platform.observation_store.schema import OBSERVATION_COLUMNS
from urban_platform.observation_store.writer import ObservationStoreWriter, melt_to_narrow
from urban_platform.observation_store.reader import ObservationStoreReader, to_wide
from urban_platform.observation_store.pruner import prune, prune_all


_CITY = "bangalore_demo"
_TS = pd.Timestamp("2026-05-07T10:30:00", tz="UTC")
_FETCHED_AT = datetime(2026, 5, 7, 10, 30, 0, tzinfo=timezone.utc)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def flood_wide() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "station_id": "openmeteo_12.97_77.59",
            "latitude": 12.97, "longitude": 77.59,
            "timestamp": _TS,
            "rainfall_intensity_mm_per_hr": 18.0,
            "rainfall_accumulation_3h_mm": 22.5,
            "data_source": "openmeteo",
            "quality_flag": "real",
        }
    ])


@pytest.fixture
def air_wide() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "station_id": "openmeteo_aq_12.97_77.59",
            "latitude": 12.97, "longitude": 77.59,
            "timestamp": _TS,
            "pm25_ugm3": 65.0,
            "pm10_ugm3": 104.0,
            "european_aqi": 72,
            "data_source": "openmeteo",
            "quality_flag": "real",
        }
    ])


@pytest.fixture
def heat_wide() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "station_id": "openmeteo_12.97_77.59",
            "latitude": 12.97, "longitude": 77.59,
            "timestamp": _TS,
            "temperature_c": 32.0,
            "apparent_temperature_c": 35.5,
            "relative_humidity_pct": 68.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        }
    ])


# ── A: melt_to_narrow ─────────────────────────────────────────────────────

def test_melt_flood_produces_two_rows_per_station(flood_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(flood_wide, "flood", _CITY, _FETCHED_AT)
    assert len(narrow) == 2  # intensity + accumulation
    assert set(narrow["variable"]) == {"rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm"}


def test_melt_air_produces_three_rows_per_station(air_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(air_wide, "air", _CITY, _FETCHED_AT)
    assert len(narrow) == 3
    assert set(narrow["variable"]) == {"pm25_ugm3", "pm10_ugm3", "european_aqi"}


def test_melt_heat_produces_three_rows_per_station(heat_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(heat_wide, "heat", _CITY, _FETCHED_AT)
    assert len(narrow) == 3
    assert set(narrow["variable"]) == {"temperature_c", "apparent_temperature_c", "relative_humidity_pct"}


def test_melt_null_value_excluded() -> None:
    wide = pd.DataFrame([{
        "station_id": "s1", "latitude": 0.0, "longitude": 0.0,
        "timestamp": _TS,
        "pm25_ugm3": 50.0, "pm10_ugm3": None, "european_aqi": None,
        "data_source": "openmeteo", "quality_flag": "real",
    }])
    narrow = melt_to_narrow(wide, "air", _CITY, _FETCHED_AT)
    assert len(narrow) == 1
    assert narrow.iloc[0]["variable"] == "pm25_ugm3"


def test_melt_empty_df_returns_empty() -> None:
    narrow = melt_to_narrow(pd.DataFrame(), "flood", _CITY, _FETCHED_AT)
    assert narrow.empty
    assert list(narrow.columns) == OBSERVATION_COLUMNS


def test_observation_id_deterministic(flood_wide: pd.DataFrame) -> None:
    n1 = melt_to_narrow(flood_wide, "flood", _CITY, _FETCHED_AT)
    n2 = melt_to_narrow(flood_wide, "flood", _CITY, _FETCHED_AT)
    assert list(n1["observation_id"]) == list(n2["observation_id"])


def test_observation_id_differs_by_variable(flood_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(flood_wide, "flood", _CITY, _FETCHED_AT)
    ids = narrow["observation_id"].tolist()
    assert ids[0] != ids[1]


# ── B: ObservationStoreWriter ──────────────────────────────────────────────

def test_write_creates_parquet_file(root: Path, flood_wide: pd.DataFrame) -> None:
    ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    expected = root / "flood" / _CITY / "2026-05-07.parquet"
    assert expected.exists()


def test_write_returns_row_count(root: Path, flood_wide: pd.DataFrame) -> None:
    n = ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    assert n == 2  # 2 variables per station row


def test_write_deduplicates_on_second_call(root: Path, flood_wide: pd.DataFrame) -> None:
    w = ObservationStoreWriter(root)
    w.write(flood_wide, "flood", _CITY, _FETCHED_AT)
    w.write(flood_wide, "flood", _CITY, _FETCHED_AT)
    df = pd.read_parquet(root / "flood" / _CITY / "2026-05-07.parquet")
    assert len(df) == 2  # not 4


def test_write_empty_df_returns_zero(root: Path) -> None:
    n = ObservationStoreWriter(root).write(pd.DataFrame(), "flood", _CITY, _FETCHED_AT)
    assert n == 0


def test_write_never_raises_on_bad_data(root: Path) -> None:
    result = ObservationStoreWriter(root).write(
        pd.DataFrame({"garbage": [1, 2]}), "flood", _CITY, _FETCHED_AT
    )
    assert result == 0


def test_write_partitions_by_observation_date(root: Path) -> None:
    wide = pd.DataFrame([
        {
            "station_id": "s1", "latitude": 0.0, "longitude": 0.0,
            "timestamp": pd.Timestamp("2026-05-06T23:00:00", tz="UTC"),
            "rainfall_intensity_mm_per_hr": 5.0,
            "rainfall_accumulation_3h_mm": 7.0,
            "data_source": "openmeteo", "quality_flag": "real",
        },
        {
            "station_id": "s1", "latitude": 0.0, "longitude": 0.0,
            "timestamp": pd.Timestamp("2026-05-07T01:00:00", tz="UTC"),
            "rainfall_intensity_mm_per_hr": 8.0,
            "rainfall_accumulation_3h_mm": 10.0,
            "data_source": "openmeteo", "quality_flag": "real",
        },
    ])
    ObservationStoreWriter(root).write(wide, "flood", _CITY, _FETCHED_AT)
    files = sorted((root / "flood" / _CITY).glob("*.parquet"))
    assert len(files) == 2
    assert files[0].stem == "2026-05-06"
    assert files[1].stem == "2026-05-07"


# ── C: ObservationStoreReader ──────────────────────────────────────────────

def test_read_recent_empty_when_no_files(root: Path) -> None:
    reader = ObservationStoreReader(root)
    df = reader.read_recent("flood", _CITY)
    assert df.empty


def test_read_recent_returns_data_for_fresh_file(root: Path, flood_wide: pd.DataFrame) -> None:
    ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    # File was just written, so mtime is now — well within any threshold
    reader = ObservationStoreReader(root)
    df = reader.read_recent("flood", _CITY, max_age_hours=1)
    assert not df.empty
    assert "variable" in df.columns


def test_read_recent_empty_for_stale_file(root: Path, flood_wide: pd.DataFrame, monkeypatch) -> None:
    ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    file = root / "flood" / _CITY / "2026-05-07.parquet"
    # Set mtime to 3 hours ago
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
    os.utime(file, (old_ts, old_ts))
    df = ObservationStoreReader(root).read_recent("flood", _CITY, max_age_hours=1)
    assert df.empty


def test_query_range_returns_matching_rows(root: Path, flood_wide: pd.DataFrame) -> None:
    ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    reader = ObservationStoreReader(root)
    df = reader.query_range(
        "flood", _CITY,
        ts_start=datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc),
        ts_end=datetime(2026, 5, 8, 0, 0, tzinfo=timezone.utc),
    )
    assert not df.empty
    assert (df["variable"] == "rainfall_intensity_mm_per_hr").any()


def test_query_range_empty_when_no_files(root: Path) -> None:
    df = ObservationStoreReader(root).query_range(
        "flood", _CITY,
        ts_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        ts_end=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    assert df.empty


def test_list_available_sorted(root: Path, flood_wide: pd.DataFrame) -> None:
    w = ObservationStoreWriter(root)
    w.write(flood_wide, "flood", _CITY, _FETCHED_AT)
    dates = ObservationStoreReader(root).list_available("flood", _CITY)
    assert dates == ["2026-05-07"]


# ── D: pruner ─────────────────────────────────────────────────────────────

def _write_file_for_date(root: Path, obs_date: date) -> Path:
    path = root / "flood" / _CITY / f"{obs_date.isoformat()}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": [1]}).to_parquet(path, index=False)
    return path


def test_prune_deletes_old_files(root: Path) -> None:
    old_file = _write_file_for_date(root, date(2026, 1, 1))
    today = date(2026, 5, 7)
    deleted = prune("flood", _CITY, retention_days=90, root=root, today=today)
    assert deleted == 1
    assert not old_file.exists()


def test_prune_keeps_recent_files(root: Path) -> None:
    recent = _write_file_for_date(root, date(2026, 5, 6))
    deleted = prune("flood", _CITY, retention_days=90, root=root, today=date(2026, 5, 7))
    assert deleted == 0
    assert recent.exists()


def test_prune_returns_count(root: Path) -> None:
    _write_file_for_date(root, date(2026, 1, 1))
    _write_file_for_date(root, date(2026, 1, 2))
    n = prune("flood", _CITY, retention_days=90, root=root, today=date(2026, 5, 7))
    assert n == 2


def test_prune_nonexistent_dir_returns_zero(root: Path) -> None:
    assert prune("flood", "no_such_city", root=root) == 0


def test_prune_all_covers_multiple_domains(root: Path) -> None:
    _write_file_for_date(root, date(2026, 1, 1))
    (root / "air" / _CITY).mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": [1]}).to_parquet(root / "air" / _CITY / "2026-01-01.parquet", index=False)
    results = prune_all(root=root, today=date(2026, 5, 7))
    assert results.get(f"flood/{_CITY}", 0) == 1
    assert results.get(f"air/{_CITY}", 0) == 1


# ── E: to_wide round-trip ──────────────────────────────────────────────────

def test_to_wide_flood_round_trip(flood_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(flood_wide, "flood", _CITY, _FETCHED_AT)
    wide = to_wide(narrow)
    assert "rainfall_intensity_mm_per_hr" in wide.columns
    assert "rainfall_accumulation_3h_mm" in wide.columns
    assert len(wide) == len(flood_wide)


def test_to_wide_air_round_trip(air_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(air_wide, "air", _CITY, _FETCHED_AT)
    wide = to_wide(narrow)
    assert "pm25_ugm3" in wide.columns
    assert "pm10_ugm3" in wide.columns
    assert "european_aqi" in wide.columns


def test_to_wide_heat_round_trip(heat_wide: pd.DataFrame) -> None:
    narrow = melt_to_narrow(heat_wide, "heat", _CITY, _FETCHED_AT)
    wide = to_wide(narrow)
    assert "temperature_c" in wide.columns
    assert "apparent_temperature_c" in wide.columns
    assert "relative_humidity_pct" in wide.columns


def test_to_wide_empty_returns_empty() -> None:
    assert to_wide(pd.DataFrame()).empty


def test_cache_first_returns_store_data_not_api(
    root: Path, flood_wide: pd.DataFrame
) -> None:
    """read_recent returns store data; to_wide converts it back to pipeline-ready format."""
    ObservationStoreWriter(root).write(flood_wide, "flood", _CITY, _FETCHED_AT)
    reader = ObservationStoreReader(root)
    cached = reader.read_recent("flood", _CITY, max_age_hours=1)
    assert not cached.empty
    wide = to_wide(cached)
    assert "rainfall_intensity_mm_per_hr" in wide.columns
    # Values preserved
    assert abs(wide["rainfall_intensity_mm_per_hr"].iloc[0] - 18.0) < 0.01
