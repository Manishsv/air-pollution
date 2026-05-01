import unittest
from datetime import datetime, timezone

import pandas as pd

from urban_platform.standards.converters import stations_pm25_to_observations
from urban_platform.standards.converters import weather_hourly_to_observations
from urban_platform.fabric.observation_store import build_observation_table
from urban_platform.standards.validators import SchemaValidationError, assert_quality_gate, validate_observations


class TestPlatformStandards(unittest.TestCase):
    def test_observation_schema_validation(self):
        ts = pd.to_datetime([datetime(2026, 1, 1, tzinfo=timezone.utc)], utc=True)
        obs = pd.DataFrame(
            {
                "observation_id": ["obs_1"],
                "entity_id": ["sensor_1"],
                "observed_property": ["pm25"],
                "value": [42.0],
                "unit": ["µg/m3"],
                "timestamp": ts,
                "source": ["openaq"],
                "quality_flag": ["OK"],
            }
        )
        validate_observations(obs)
        self.assertEqual(obs.loc[0, "quality_flag"], "ok")

        bad = obs.drop(columns=["entity_id"])
        with self.assertRaises(SchemaValidationError):
            validate_observations(bad)

    def test_station_conversion_to_observations(self):
        ts = pd.to_datetime([datetime(2026, 1, 1, tzinfo=timezone.utc)], utc=True)
        stations = pd.DataFrame(
            {
                "station_id": ["s1"],
                "station_name": ["Station 1"],
                "latitude": [12.9],
                "longitude": [77.6],
                "timestamp": ts,
                "pm25": [55.0],
                "data_source": ["synthetic"],
            }
        )
        obs = stations_pm25_to_observations(stations)
        validate_observations(obs)
        self.assertEqual(obs.loc[0, "entity_id"], "s1")
        self.assertEqual(obs.loc[0, "observed_property"], "pm25")
        self.assertEqual(obs.loc[0, "quality_flag"], "synthetic")

    def test_weather_conversion_and_broadcast(self):
        ts = pd.to_datetime(
            [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 1, tzinfo=timezone.utc)],
            utc=True,
        )
        weather = pd.DataFrame(
            {
                "timestamp": ts,
                "temperature_2m": [25.0, 24.5],
                "wind_speed_10m": [2.0, 2.5],
                "weather_source_type": ["real", "real"],
            }
        )
        obs = weather_hourly_to_observations(weather)
        validate_observations(obs)
        self.assertTrue((obs["entity_type"] == "weather").all())

        grid = pd.DataFrame({"h3_id": ["a", "b", "c"]})
        table = build_observation_table(obs, grid)
        # Broadcast: 2 timestamps * 2 vars * 3 cells = 12 rows
        self.assertEqual(len(table), 12)
        self.assertTrue(table["grid_id"].notna().all())

    def test_quality_gate_primitive(self):
        allowed, reason = assert_quality_gate(
            synthetic_ratio=0.25,
            max_synthetic_ratio=0.0,
            block_if_synthetic=True,
        )
        self.assertFalse(allowed)
        self.assertIn("exceeds", reason)


if __name__ == "__main__":
    unittest.main()

