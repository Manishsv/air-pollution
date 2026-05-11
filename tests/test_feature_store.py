from datetime import datetime, timezone

import pandas as pd

from airos.drivers.fabric.feature_store import build_feature_store, pivot_feature_store_for_model


def test_feature_store_static_and_dynamic_present():
    static = pd.DataFrame(
        {
            "h3_id": ["a", "b"],
            "road_density_km_per_sqkm": [1.0, 2.0],
            "osm_source_type": ["osm", "osm"],
        }
    )
    aq = pd.DataFrame(
        {
            "h3_id": ["a", "b"],
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T00:00:00Z")],
            "current_pm25": [50.0, 60.0],
            "aq_source_type": ["real", "interpolated"],
            "nearest_station_distance_km": [0.0, 1.2],
            "station_count_used": [1, 3],
            "warning_flags": ["", "FAR_FROM_STATIONS"],
        }
    )
    wx = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z")],
            "temperature_2m": [25.0],
            "weather_source_type": ["real"],
        }
    )
    fs = build_feature_store(static_features=static, aq_panel=aq, weather_hourly=wx, fire_features=None)
    assert not fs.empty
    assert (fs["timestamp"].isna()).any()  # static rows
    assert (fs["timestamp"].notna()).any()  # dynamic rows


def test_pivot_has_required_model_columns_and_provenance():
    static = pd.DataFrame(
        {
            "h3_id": ["a"],
            "road_density_km_per_sqkm": [1.0],
            "osm_source_type": ["osm"],
        }
    )
    ts0 = pd.Timestamp(datetime(2026, 1, 1, 0, tzinfo=timezone.utc))
    ts1 = pd.Timestamp(datetime(2026, 1, 1, 1, tzinfo=timezone.utc))
    aq = pd.DataFrame(
        {
            "h3_id": ["a", "a"],
            "timestamp": [ts0, ts1],
            "current_pm25": [50.0, 55.0],
            "aq_source_type": ["real", "real"],
            "nearest_station_distance_km": [0.0, 0.0],
            "station_count_used": [1, 1],
            "warning_flags": ["", ""],
        }
    )
    wx = pd.DataFrame(
        {
            "timestamp": [ts0, ts1],
            "temperature_2m": [25.0, 24.5],
            "weather_source_type": ["real", "real"],
        }
    )
    fs = build_feature_store(static_features=static, aq_panel=aq, weather_hourly=wx, fire_features=None)
    model = pivot_feature_store_for_model(fs, target_variable="pm25", horizon_hours=1)

    # required core columns for legacy model codepath
    for c in [
        "h3_id",
        "timestamp",
        "current_pm25",
        "pm25_lag_1h",
        "pm25_lag_3h",
        "hour",
        "day_of_week",
        "month",
        "pm25_t_plus_1h",
        "data_quality_score",
        "aq_source_type",
        "weather_source_type",
        "osm_source_type",
        "warning_flags",
    ]:
        assert c in model.columns

    # provenance columns survive
    assert model["aq_source_type"].astype(str).iloc[0] in {"real", "interpolated", "synthetic", "unavailable"}
    assert model["osm_source_type"].astype(str).iloc[0] == "osm"


# ── DuckDB feature store tests ─────────────────────────────────────────────

import pytest
from pathlib import Path
from datetime import datetime, timezone

from airos.drivers.feature_store.schema import ensure_schema
from airos.drivers.feature_store.writer import FeatureStoreWriter
from airos.drivers.feature_store.reader import FeatureStoreReader


_BUCKET = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
_CITY = "bangalore_demo"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_fs.duckdb"


@pytest.fixture
def flood_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"h3_id": "8a283082a657fff", "flood_risk_score": 0.72,
         "rainfall_mm_per_hr": 18.0, "incident_count": 2, "asset_count": 1},
        {"h3_id": "8a283082a65ffff", "flood_risk_score": 0.35,
         "rainfall_mm_per_hr": 4.0, "incident_count": 0, "asset_count": 2},
    ])


@pytest.fixture
def air_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"h3_id": "8a283082a657fff", "aqi_score": 0.80, "pm25_ugm3": 96.0,
         "aqi_category": "poor"},
        {"h3_id": "8a283082a65ffff", "aqi_score": 0.42, "pm25_ugm3": 50.0,
         "aqi_category": "satisfactory"},
    ])


@pytest.fixture
def heat_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"h3_id": "8a283082a657fff", "heat_risk_score": 0.65, "heat_index_c": 34.0,
         "green_deficit": 0.80, "uhi_intensity": 3.2},
        {"h3_id": "8a283082a65ffff", "heat_risk_score": 0.30, "heat_index_c": 29.5,
         "green_deficit": 0.40, "uhi_intensity": -0.5},
    ])


def test_ensure_schema_idempotent(tmp_db: Path) -> None:
    import duckdb
    conn = duckdb.connect(str(tmp_db))
    ensure_schema(conn)
    ensure_schema(conn)  # second call must not raise
    conn.close()


def test_db_path_in_data_dir() -> None:
    from airos.drivers.feature_store.schema import DB_PATH
    assert DB_PATH.parent.name == "data"


def test_write_flood_creates_rows(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        n = w.write_flood_features(flood_df, city_id=_CITY,
                                   timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    assert n == 2


def test_write_air_creates_rows(tmp_db: Path, air_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        n = w.write_air_features(air_df, city_id=_CITY,
                                 timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    assert n == 2


def test_write_heat_creates_rows(tmp_db: Path, heat_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        n = w.write_heat_features(heat_df, city_id=_CITY,
                                  timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    assert n == 2


def test_upsert_replaces_existing_bucket(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    import duckdb
    conn = duckdb.connect(str(tmp_db), read_only=True)
    count = conn.execute(
        "SELECT COUNT(*) FROM flood_features WHERE city_id = ? AND timestamp_bucket = ?",
        [_CITY, _BUCKET],
    ).fetchone()[0]
    conn.close()
    assert count == 2  # not 4 — upsert replaced


def test_drainage_coverage_derived_from_asset_count(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    import duckdb
    conn = duckdb.connect(str(tmp_db), read_only=True)
    df = conn.execute("SELECT drainage_coverage FROM flood_features WHERE city_id = ?", [_CITY]).df()
    conn.close()
    assert df["drainage_coverage"].notna().all()
    assert (df["drainage_coverage"] >= 0.75).all()


def test_read_flood_returns_rows(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    reader = FeatureStoreReader(tmp_db)
    df = reader.read_flood_features(_CITY)
    reader.close()
    assert len(df) == 2
    assert "flood_risk_score" in df.columns


def test_latest_bucket_returns_value(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    reader = FeatureStoreReader(tmp_db)
    bucket = reader.latest_timestamp_bucket(_CITY)
    reader.close()
    assert bucket is not None


def test_reader_missing_db_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FeatureStoreReader(tmp_path / "nonexistent.duckdb")


def test_cross_domain_all_three(
    tmp_db: Path,
    flood_df: pd.DataFrame,
    air_df: pd.DataFrame,
    heat_df: pd.DataFrame,
) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
        w.write_air_features(air_df, city_id=_CITY,
                             timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
        w.write_heat_features(heat_df, city_id=_CITY,
                              timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    reader = FeatureStoreReader(tmp_db)
    result = reader.cross_domain_query(_CITY)
    reader.close()

    assert not result.cells_df.empty
    assert set(result.available_domains) == {"flood", "air", "heat"}
    assert "composite_risk_score" in result.cells_df.columns
    scores = result.cells_df["composite_risk_score"].dropna()
    assert (scores >= 0.0).all() and (scores <= 1.0).all()
    assert result.cells_df["elevated_domain_count"].max() >= 2


def test_cross_domain_partial_domain(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    reader = FeatureStoreReader(tmp_db)
    result = reader.cross_domain_query(_CITY)
    reader.close()
    assert not result.cells_df.empty
    assert result.available_domains == ["flood"]
    assert result.cells_df["aqi_score"].isna().all()


def test_cross_domain_empty_city(tmp_db: Path, flood_df: pd.DataFrame) -> None:
    with FeatureStoreWriter(tmp_db) as w:
        w.write_flood_features(flood_df, city_id=_CITY,
                               timestamp_bucket=_BUCKET, data_quality_flag="synthetic")
    reader = FeatureStoreReader(tmp_db)
    result = reader.cross_domain_query("mumbai_demo")
    reader.close()
    assert result.cells_df.empty
    assert result.available_domains == []

