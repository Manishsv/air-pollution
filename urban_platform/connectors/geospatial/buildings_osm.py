from __future__ import annotations

from typing import Any

import geopandas as gpd

from urban_platform.connectors.geospatial.osm import fetch_osm


def fetch_buildings_osm(config: Any, *, boundary_bundle: Any, sample_mode: bool) -> gpd.GeoDataFrame:
    layers = fetch_osm(config, boundary_bundle=boundary_bundle, sample_mode=sample_mode)
    return layers.get("buildings", gpd.GeoDataFrame())

