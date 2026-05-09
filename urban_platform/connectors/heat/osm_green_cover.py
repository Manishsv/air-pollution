"""
OSM green cover connector for urban heat risk.

Pulls parks, forests, grass, trees, and water bodies for a city boundary
polygon using osmnx, then computes per-H3-cell green cover fraction and
water proximity score.

Green cover fraction: share of H3 cell area covered by OSM green features.
Water proximity score: 1.0 if any water feature intersects the cell,
    0.0 if no water within 500 m, interpolated linearly in between.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import h3
import pandas as pd
from shapely.geometry import Polygon, Point, shape
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

_GREEN_TAGS: list[dict[str, Any]] = [
    {"leisure": "park"},
    {"landuse": "forest"},
    {"landuse": "grass"},
    {"landuse": "meadow"},
    {"natural": "tree_row"},
    {"natural": "scrub"},
    {"natural": "heath"},
]

_WATER_TAGS: list[dict[str, Any]] = [
    {"natural": "water"},
    {"landuse": "reservoir"},
    {"natural": "wetland"},
    {"waterway": True},
]

_WATER_PROXIMITY_RADIUS_M = 500.0
# 1 degree latitude ≈ 111 km; used for rough degree-to-metre conversion
_DEG_PER_METRE = 1.0 / 111_000.0


def _h3_cell_polygon(h3_id: str) -> Polygon:
    """Return the Shapely polygon for an H3 cell boundary."""
    coords = h3.cell_to_boundary(h3_id)
    return Polygon([(lon, lat) for lat, lon in coords])


def _union_from_features(gdf: Any) -> Optional[Any]:
    """Union all geometries in a GeoDataFrame; return None if empty."""
    if gdf is None or len(gdf) == 0:
        return None
    geoms = [g for g in gdf.geometry if g is not None and not g.is_empty]
    if not geoms:
        return None
    return unary_union(geoms)


def _green_cover_fraction(cell_poly: Polygon, green_union: Optional[Any]) -> float:
    if green_union is None or cell_poly.area == 0:
        return 0.0
    intersection = cell_poly.intersection(green_union)
    return min(1.0, intersection.area / cell_poly.area)


def _water_proximity_score(
    cell_poly: Polygon,
    water_union: Optional[Any],
    radius_m: float = _WATER_PROXIMITY_RADIUS_M,
) -> float:
    if water_union is None:
        return 0.0
    if cell_poly.intersects(water_union):
        return 1.0
    centroid = cell_poly.centroid
    # Convert radius to approximate degrees for 2D geometry
    radius_deg = radius_m * _DEG_PER_METRE
    nearest = water_union.distance(centroid)
    if nearest >= radius_deg:
        return 0.0
    return round(1.0 - nearest / radius_deg, 4)


def compute_green_cover(
    boundary: Polygon,
    h3_resolution: int = 8,
    osmnx_module: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Compute green cover fraction and water proximity score per H3 cell.

    Parameters
    ----------
    boundary : shapely.geometry.Polygon
        City boundary polygon (WGS-84 lat/lon).
    h3_resolution : int
        H3 resolution for cell grid (default 8).
    osmnx_module : module, optional
        Injectable osmnx module for testing. Uses real osmnx if None.

    Returns
    -------
    pd.DataFrame with columns:
        h3_id, green_cover_fraction, water_proximity_score, osm_feature_count
    Returns empty DataFrame on any OSM fetch failure.
    """
    columns = ["h3_id", "green_cover_fraction", "water_proximity_score", "osm_feature_count"]
    empty = pd.DataFrame(columns=columns)

    ox = osmnx_module
    if ox is None:
        try:
            import osmnx as _ox
            ox = _ox
        except ImportError:
            logger.error("osmnx is not installed")
            return empty

    # Fetch green and water features
    green_union: Optional[Any] = None
    water_union: Optional[Any] = None
    osm_feature_count_total = 0

    for tags in _GREEN_TAGS:
        try:
            gdf = ox.features_from_polygon(boundary, tags=tags)
            u = _union_from_features(gdf)
            if u is not None:
                green_union = u if green_union is None else green_union.union(u)
                osm_feature_count_total += len(gdf)
        except Exception as exc:
            logger.debug("OSM green fetch skipped for tags %s: %s", tags, exc)

    for tags in _WATER_TAGS:
        try:
            gdf = ox.features_from_polygon(boundary, tags=tags)
            u = _union_from_features(gdf)
            if u is not None:
                water_union = u if water_union is None else water_union.union(u)
        except Exception as exc:
            logger.debug("OSM water fetch skipped for tags %s: %s", tags, exc)

    # Enumerate H3 cells covering the boundary
    try:
        h3_ids = list(h3.geo_to_cells(
            {
                "type": "Polygon",
                "coordinates": [[(lon, lat) for lon, lat in boundary.exterior.coords]],
            },
            h3_resolution,
        ))
    except Exception as exc:
        logger.warning("H3 cell enumeration failed: %s", exc)
        return empty

    if not h3_ids:
        logger.warning("No H3 cells found for boundary at resolution %d", h3_resolution)
        return empty

    rows = []
    for h3_id in h3_ids:
        cell_poly = _h3_cell_polygon(h3_id)
        gcf = _green_cover_fraction(cell_poly, green_union)
        wps = _water_proximity_score(cell_poly, water_union)
        rows.append({
            "h3_id": h3_id,
            "green_cover_fraction": round(gcf, 4),
            "water_proximity_score": wps,
            "osm_feature_count": osm_feature_count_total,
        })

    df = pd.DataFrame(rows, columns=columns)
    logger.info(
        "Green cover computed for %d H3 cells at resolution %d (%d OSM features)",
        len(df), h3_resolution, osm_feature_count_total,
    )
    return df
