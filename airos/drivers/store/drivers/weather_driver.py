"""AirOS built-in weather driver — OpenMeteo API (no key required)."""
from __future__ import annotations

from airos.drivers.store.drivers._base import _InTreeDriver


class WeatherDriver(_InTreeDriver):
    domain = "weather"
    cadence_hours = 0.25          # 15 minutes; Open-Meteo updates hourly
    produces_assessments = False  # structural context only

    signal_names = [
        "TEMP_C", "HUMIDITY_PCT", "WIND_SPEED_MS",
        "WIND_DIR_DEG", "RAINFALL_MM", "DATA_CONFIDENCE",
    ]
    data_sources = ["OpenMeteo API (open-access, no key required)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_weather
        return _ingest_weather(city_id, bbox, force=force)
