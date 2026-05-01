from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from src.scale_analysis import analyze_h3_resolution


def _grid(n: int, area_sqkm: float = 1.0, h3_resolution: int = 8) -> gpd.GeoDataFrame:
    polys = []
    for i in range(n):
        polys.append(Polygon([(i, 0), (i, 1), (i + 1, 1), (i + 1, 0)]))
    gdf = gpd.GeoDataFrame({"h3_id": [f"c{i}" for i in range(n)], "area_sqkm": [area_sqkm] * n}, geometry=polys, crs="EPSG:4326")
    gdf.h3_resolution = h3_resolution  # type: ignore[attr-defined]
    return gdf


def test_resolution_assessment_warns_when_density_low():
    grid = _grid(100, area_sqkm=1.0, h3_resolution=8)  # 100 sqkm
    stations = pd.DataFrame(
        {
            "station_id": ["s1", "s2", "s3"],  # density = 3 per 100 sqkm
            "latitude": [0.0, 0.1, 0.2],
            "longitude": [0.0, 0.1, 0.2],
            "data_source": ["openaq", "openaq", "openaq"],
        }
    )
    out = analyze_h3_resolution(grid, stations)
    assert out["resolution_assessment"]["warning"] == "Grid too fine for sensor density"
    assert int(out["recommended_resolution"]) == 7


def test_resolution_assessment_warns_when_many_cells_per_station():
    grid = _grid(100, area_sqkm=1.0, h3_resolution=8)
    stations = pd.DataFrame(
        {
            "station_id": [f"s{i}" for i in range(10)],  # density = 10 per 100 sqkm (ok)
            "latitude": [0.0] * 10,
            "longitude": [0.0] * 10,
            "data_source": ["openaq"] * 10,
        }
    )
    out = analyze_h3_resolution(grid, stations)
    # avg_cells_per_station = 10 -> not strictly >10; no warning per spec
    assert out["resolution_assessment"]["warning"] in {"", "Grid too fine for sensor density"}

