from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Columns produced by the ward aggregator
WARD_FEATURE_COLUMNS = [
    "ward_id",
    "city_id",
    "ward_name",
    "cell_count",
    "avg_flood_risk",
    "avg_aqi_score",
    "avg_heat_risk",
    "composite_risk",
    "elevated_cell_count",
    "multi_risk_cell_count",
    "qol_safety",
    "qol_health",
    "qol_thermal",
    "qol_index",
    "domains_present",
    "timestamp_bucket",
]


@dataclass
class Ward:
    ward_id: str
    city_id: str
    name: str
    # GeoJSON polygon coordinates [[lon, lat], ...]
    coordinates: List[List[float]]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_geojson_feature(self) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [self.coordinates],
            },
            "properties": {
                "ward_id": self.ward_id,
                "city_id": self.city_id,
                "name": self.name,
                **self.metadata,
            },
        }
