from datetime import datetime, timezone

import pandas as pd

from urban_platform.fabric.feature_store import build_feature_store, pivot_feature_store_for_model


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

