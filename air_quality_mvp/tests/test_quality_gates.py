import unittest
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from src.data_audit import audit_data_coverage


class TestQualityGates(unittest.TestCase):
    def test_block_recommendations_if_synthetic(self):
        grid = gpd.GeoDataFrame(
            {"h3_id": ["a"], "area_sqkm": [1.0]},
            geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
            crs="EPSG:4326",
        )
        ts = pd.to_datetime([datetime(2026, 1, 1, tzinfo=timezone.utc)])
        stations = pd.DataFrame(
            {
                "station_id": ["s1"],
                "station_name": ["Synthetic"],
                "latitude": [0.5],
                "longitude": [0.5],
                "timestamp": ts,
                "pm25": [50.0],
                "data_source": ["synthetic"],
            }
        )
        aq_panel = pd.DataFrame(
            {
                "h3_id": ["a"],
                "timestamp": ts,
                "current_pm25": [50.0],
                "aq_source_type": ["synthetic"],
                "nearest_station_distance_km": [1.0],
            }
        )
        model_ds = aq_panel.copy()
        gates = {
            "block_recommendations_if_synthetic": True,
            "max_synthetic_aq_ratio_for_recommendations": 0.0,
            "min_real_stations_required": 3,
            "max_avg_station_distance_km": 10,
        }
        audit = audit_data_coverage(
            grid_gdf=grid,
            aq_stations_hourly=stations,
            aq_panel=aq_panel,
            model_dataset=model_ds,
            h3_resolution=8,
            quality_gates=gates,
        )
        self.assertFalse(audit["recommendation_allowed"])
        self.assertIn("Synthetic", audit["recommendation_block_reason"])


if __name__ == "__main__":
    unittest.main()

