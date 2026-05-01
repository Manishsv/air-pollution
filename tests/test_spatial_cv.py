from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from urban_platform.models.air_quality_forecast import run_spatial_cross_validation


def _stations_hourly(n_stations: int) -> pd.DataFrame:
    ts0 = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    rows = []
    for s in range(n_stations):
        sid = f"s{s}"
        for h in range(12):
            rows.append(
                {
                    "station_id": sid,
                    "station_name": sid,
                    "latitude": 12.0 + 0.01 * s,
                    "longitude": 77.0 + 0.01 * s,
                    "timestamp": ts0 + pd.Timedelta(hours=h),
                    "pm25": 50.0 + s,
                    "data_source": "openaq",
                }
            )
    return pd.DataFrame(rows)


def test_spatial_cv_leave_one_out_when_enough_stations():
    st = _stations_hourly(5)
    res = run_spatial_cross_validation(st, station_ids="station_id", model="random_forest", n_splits=None)
    assert res["spatial_cv_method"] == "leave_one_station_out"
    assert bool(res.get("spatial_cv_performed")) is True
    assert res["spatial_cv_station_count"] >= 5
    assert "spatial_cv_mean_rmse" in res


def test_spatial_cv_fallback_when_insufficient_stations():
    st = _stations_hourly(4)
    res = run_spatial_cross_validation(st, station_ids="station_id", model="random_forest", n_splits=None)
    assert res["spatial_cv_method"] == "single_holdout_fallback"

