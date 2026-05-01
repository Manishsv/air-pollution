from pathlib import Path

import pandas as pd


def test_openaq_raw_and_observations(monkeypatch):
    from urban_platform.connectors.air_quality import openaq as mod
    from urban_platform.standards.schemas import observation_required_columns

    raw_df = pd.DataFrame(
        {
            "station_id": ["s1"],
            "station_name": ["Station 1"],
            "latitude": [12.9],
            "longitude": [77.6],
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z")],
            "pm25": [42.0],
            "data_source": ["openaq_v3"],
        }
    )

    monkeypatch.setattr(mod._legacy_aq, "fetch_openaq_pm25_v3", lambda **kwargs: raw_df)
    monkeypatch.setattr(mod._legacy_aq, "fetch_openaq_pm25", lambda *args, **kwargs: pd.DataFrame())

    class Cfg:
        city_name = "X"
        lookback_days = 1
        bbox = type("B", (), {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0})()
        data_processed_dir = Path(".")  # used for cache_dir construction
        cache = type("Cache", (), {"ttl_days": 1, "force_refresh": True})()

    # Raw fetcher
    raw = mod.fetch_openaq_raw(Cfg())
    assert set(["station_id", "station_name", "latitude", "longitude", "timestamp", "pm25", "data_source"]).issubset(raw.columns)

    # Backward-compatible alias
    raw2 = mod.fetch_openaq(Cfg())
    assert raw2.equals(raw)

    # Observation fetcher
    obs = mod.fetch_openaq_observations(Cfg())
    for c in observation_required_columns():
        assert c in obs.columns


def test_open_meteo_raw_and_observations(monkeypatch):
    from urban_platform.connectors.weather import open_meteo as mod
    from urban_platform.standards.schemas import observation_required_columns

    raw_weather = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T01:00:00Z")],
            "temperature_2m": [25.0, 24.5],
            "wind_speed_10m": [2.0, 2.5],
            "weather_source_type": ["real", "real"],
        }
    )
    monkeypatch.setattr(mod, "_legacy_fetch", lambda **kwargs: raw_weather)

    class Cfg:
        lookback_days = 1
        bbox = type("B", (), {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0})()

    raw = mod.fetch_open_meteo_raw(Cfg())
    assert "timestamp" in raw.columns
    assert "temperature_2m" in raw.columns

    raw2 = mod.fetch_open_meteo(Cfg())
    assert raw2.equals(raw)

    obs = mod.fetch_open_meteo_observations(Cfg())
    for c in observation_required_columns():
        assert c in obs.columns

