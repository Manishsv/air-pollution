from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import geopandas as gpd
import osmnx as ox
from shapely.geometry import Polygon, box


logger = logging.getLogger(__name__)


def _repair_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geom = gdf.geometry.iloc[0]
    try:
        from shapely.make_valid import make_valid  # type: ignore

        geom = make_valid(geom)
    except Exception:
        pass
    try:
        geom = geom.buffer(0)
    except Exception:
        pass

    if geom is None or geom.is_empty:
        raise ValueError("Boundary geometry is empty after repair.")

    out = gdf.copy()
    out.geometry = [geom]
    return out


def boundary_from_bbox(north: float, south: float, east: float, west: float) -> gpd.GeoDataFrame:
    poly: Polygon = box(west, south, east, north)
    return gpd.GeoDataFrame({"name": ["bbox"]}, geometry=[poly], crs="EPSG:4326")


def boundary_from_ward_geojson(path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Ward polygon file is empty: {path}")
    if gdf.crs is None:
        logger.warning("Ward polygon has no CRS; assuming EPSG:4326.")
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    geom = gdf.geometry.unary_union
    return gpd.GeoDataFrame({"name": ["ward"]}, geometry=[geom], crs="EPSG:4326")


def get_city_boundary(city_name: str) -> gpd.GeoDataFrame:
    # OSMnx must receive WGS84 polygons.
    ox.settings.use_cache = True
    ox.settings.log_console = False
    gdf = ox.geocode_to_gdf(city_name)
    gdf = gdf[["display_name", "geometry"]].rename(columns={"display_name": "name"})
    gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    gdf = _repair_geometry(gdf)
    return gdf


@dataclass(frozen=True)
class BoundaryBundle:
    boundary_wgs84: gpd.GeoDataFrame
    boundary_projected: gpd.GeoDataFrame
    bbox_tuple: Optional[tuple[float, float, float, float]]  # south,north,west,east
    poly_hash: str


def get_boundary_bundle(
    *,
    spatial_mode: str,
    city_name: str,
    fallback_city_name: str,
    local_crs: str,
    bbox: Optional[tuple[float, float, float, float]] = None,  # north,south,east,west
    ward_polygon_path: Optional[str] = None,
) -> BoundaryBundle:
    spatial_mode = spatial_mode.strip().lower()
    if spatial_mode == "bbox":
        if bbox is None:
            raise ValueError("bbox mode requires bbox coordinates.")
        north, south, east, west = bbox
        boundary_wgs84 = boundary_from_bbox(north=north, south=south, east=east, west=west)
        bbox_tuple = (south, north, west, east)
    elif spatial_mode in {"ward", "polygon"}:
        if not ward_polygon_path:
            raise ValueError("ward mode requires ward_polygon_path in config.")
        boundary_wgs84 = boundary_from_ward_geojson(ward_polygon_path)
        bbox_tuple = None
    elif spatial_mode in {"full_city", "city"}:
        try:
            boundary_wgs84 = get_city_boundary(city_name)
        except Exception as e:
            logger.warning("City boundary failed for %s (%s). Trying fallback %s.", city_name, e, fallback_city_name)
            boundary_wgs84 = get_city_boundary(fallback_city_name)
        bbox_tuple = None
    else:
        raise ValueError(f"Unknown spatial_mode: {spatial_mode}")

    boundary_wgs84 = boundary_wgs84.to_crs("EPSG:4326")
    geom = boundary_wgs84.geometry.iloc[0]
    poly_hash = __import__("hashlib").sha1(geom.wkb_hex.encode("utf-8")).hexdigest()[:10]
    boundary_projected = boundary_wgs84.to_crs(local_crs)

    return BoundaryBundle(
        boundary_wgs84=boundary_wgs84,
        boundary_projected=boundary_projected,
        bbox_tuple=bbox_tuple,
        poly_hash=poly_hash,
    )

