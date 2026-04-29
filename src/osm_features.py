from __future__ import annotations

import logging
from typing import Dict, Optional

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Polygon


logger = logging.getLogger(__name__)


LANDUSE_TAGS = {
    "landuse": [
        "industrial",
        "commercial",
        "residential",
        "retail",
        "forest",
        "grass",
        "recreation_ground",
        "cemetery",
    ]
}

POI_TAGS = {
    "amenity": True,
    "shop": True,
    "leisure": True,
    "tourism": True,
    "healthcare": True,
    "public_transport": True,
}

BUILDING_TAGS = {"building": True}

ROAD_TAGS = {"highway": True}

USEFUL_HIGHWAY_CLASSES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
    "unclassified",
}


def _safe_features_from_polygon(poly_wgs84: Polygon, tags: dict) -> gpd.GeoDataFrame:
    try:
        gdf = ox.features_from_polygon(poly_wgs84, tags)
        if not isinstance(gdf, gpd.GeoDataFrame):
            gdf = gpd.GeoDataFrame(gdf)
        if gdf.empty:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return gdf.to_crs("EPSG:4326")
    except Exception as e:
        logger.warning("OSM download failed for tags=%s: %s", tags, e)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def _clip_projected(gdf_wgs84: gpd.GeoDataFrame, boundary_projected: gpd.GeoDataFrame, local_crs: str) -> gpd.GeoDataFrame:
    if gdf_wgs84.empty:
        return gpd.GeoDataFrame(geometry=[], crs=local_crs)
    gdf = gdf_wgs84.to_crs(local_crs)
    b = boundary_projected.geometry.iloc[0]
    gdf = gdf[gdf.geometry.intersects(b)].copy()
    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=local_crs)
    gdf["geometry"] = gdf.geometry.intersection(b)
    gdf = gdf[~gdf.geometry.is_empty].copy()
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf.set_crs(local_crs, allow_override=True)
    return gdf


def _limit_rows(gdf: gpd.GeoDataFrame, max_rows: Optional[int]) -> gpd.GeoDataFrame:
    if max_rows is None or max_rows <= 0 or gdf.empty:
        return gdf
    if len(gdf) <= max_rows:
        return gdf
    return gdf.iloc[:max_rows].copy()


def _normalize_highway_col(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty or "highway" not in gdf.columns:
        return gdf
    hw = gdf["highway"]

    def first_val(v):
        if isinstance(v, list) and v:
            return str(v[0])
        return str(v) if v is not None else None

    gdf = gdf.copy()
    gdf["highway_class"] = hw.apply(first_val)
    return gdf


def download_osm_features(
    *,
    spatial_mode: str,
    city_name: str,
    boundary_wgs84: gpd.GeoDataFrame,
    boundary_projected: gpd.GeoDataFrame,
    local_crs: str,
    sample_mode: bool = True,
    max_buildings: int = 5000,
    max_roads: int = 5000,
    max_pois: int = 3000,
) -> Dict[str, gpd.GeoDataFrame]:
    """
    Returns projected GeoDataFrames in `local_crs`:
      - roads
      - buildings
      - landuse
      - pois
    """
    spatial_mode = spatial_mode.strip().lower()
    boundary_wgs84 = boundary_wgs84.to_crs("EPSG:4326")
    poly_wgs84 = boundary_wgs84.geometry.iloc[0]

    # NOTE: OSMnx feature download must be EPSG:4326 polygon.
    buildings_wgs84 = _safe_features_from_polygon(poly_wgs84, BUILDING_TAGS)
    landuse_wgs84 = _safe_features_from_polygon(poly_wgs84, LANDUSE_TAGS)
    pois_wgs84 = _safe_features_from_polygon(poly_wgs84, POI_TAGS)

    if spatial_mode == "bbox":
        # Lightweight roads: query as features, no graph.
        roads_wgs84 = _safe_features_from_polygon(poly_wgs84, ROAD_TAGS)
    else:
        # Full city roads: graph approach, then filter spatially with projected boundary.
        try:
            G = ox.graph_from_place(city_name, network_type="drive", simplify=True)
            G_proj = ox.project_graph(G, to_crs=local_crs)
            roads_edges = ox.graph_to_gdfs(G_proj, nodes=False)
            roads_wgs84 = roads_edges.to_crs("EPSG:4326")
        except Exception as e:
            logger.warning("Road graph download failed; falling back to highway features: %s", e)
            roads_wgs84 = _safe_features_from_polygon(poly_wgs84, ROAD_TAGS)

    roads_proj = _clip_projected(roads_wgs84, boundary_projected, local_crs)
    roads_proj = _normalize_highway_col(roads_proj)
    if not roads_proj.empty and "highway_class" in roads_proj.columns:
        roads_proj = roads_proj[roads_proj["highway_class"].isin(USEFUL_HIGHWAY_CLASSES)].copy()

    buildings_proj = _clip_projected(buildings_wgs84, boundary_projected, local_crs)
    landuse_proj = _clip_projected(landuse_wgs84, boundary_projected, local_crs)
    pois_proj = _clip_projected(pois_wgs84, boundary_projected, local_crs)

    # Development sampling to keep bbox runs fast
    if sample_mode:
        buildings_proj = _limit_rows(buildings_proj, max_buildings)
        roads_proj = _limit_rows(roads_proj, max_roads)
        pois_proj = _limit_rows(pois_proj, max_pois)

    return {
        "roads": roads_proj,
        "buildings": buildings_proj,
        "landuse": landuse_proj,
        "pois": pois_proj,
    }

