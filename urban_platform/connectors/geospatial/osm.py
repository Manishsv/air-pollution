from __future__ import annotations

from typing import Any, Dict

import geopandas as gpd

from src.osm_features import download_osm_features as _legacy_download


def fetch_osm(config: Any, *, boundary_bundle: Any, sample_mode: bool) -> Dict[str, gpd.GeoDataFrame]:
    """
    Fetch raw OSM feature layers as GeoDataFrames. No feature engineering.

    Returns dict with keys (as in legacy): roads, buildings, landuse, pois
    """
    return _legacy_download(
        spatial_mode=str(getattr(config, "spatial_mode")),
        city_name=str(getattr(config, "city_name")),
        boundary_wgs84=boundary_bundle.boundary_wgs84,
        boundary_projected=boundary_bundle.boundary_projected,
        local_crs=str(getattr(config, "local_crs")),
        sample_mode=bool(sample_mode),
        sample_seed=int(getattr(getattr(config, "development"), "sample_seed")),
        max_buildings=int(getattr(getattr(config, "development"), "max_buildings")),
        max_roads=int(getattr(getattr(config, "development"), "max_roads")),
        max_pois=int(getattr(getattr(config, "development"), "max_pois")),
        max_landuse=int(getattr(getattr(config, "development"), "max_landuse")),
        road_classes=list(getattr(getattr(config, "osm"), "road_classes")),
    )

