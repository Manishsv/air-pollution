"""Geometry aggregation helpers: OSM features → per-H3-cell statistics.

Two public functions:
    aggregate_points_to_h3   — count/group point features per H3 cell
    aggregate_lines_to_h3    — sum clipped line lengths (metres) per H3 cell

Both use an STRtree spatial index so they scale to cities with 50 000+ OSM
features without becoming prohibitively slow.

H3 cell area at each resolution (approximate):
    res 7 → ~5.16 km²    res 8 → ~0.74 km²    res 9 → ~0.11 km²
    res 10 → ~0.015 km²

We store signals at res 8 by default (matches DEFAULT_H3_RES in ingestor.py).

UTM zones used for metric length calculations (per city):
    bangalore, mumbai, pune → EPSG:32643 (UTM 43N)
    hyderabad, chennai      → EPSG:32644 (UTM 44N)
    delhi                   → EPSG:32643 (UTM 43N)  ← close enough for our use
"""
from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import h3
import numpy as np
from shapely.geometry import Polygon

logger = logging.getLogger(__name__)

# City → UTM zone (for metric distance calculations)
CITY_UTM: dict[str, str] = {
    "bangalore":  "EPSG:32643",
    "mumbai":     "EPSG:32643",
    "pune":       "EPSG:32643",
    "delhi":      "EPSG:32643",
    "hyderabad":  "EPSG:32644",
    "chennai":    "EPSG:32644",
}
_DEFAULT_UTM = "EPSG:32643"


def _h3_polygon(h3_id: str) -> Polygon:
    """Return a shapely Polygon for an H3 cell boundary (EPSG:4326)."""
    # h3.cell_to_boundary returns [(lat, lon), ...] — shapely wants (lon, lat)
    boundary = h3.cell_to_boundary(h3_id)
    return Polygon([(lon, lat) for lat, lon in boundary])


def _utm_for_city(city_id: str) -> str:
    return CITY_UTM.get(city_id, _DEFAULT_UTM)


# ---------------------------------------------------------------------------
# Public: point-in-polygon
# ---------------------------------------------------------------------------

def aggregate_points_to_h3(
    gdf: gpd.GeoDataFrame,
    h3_ids: list[str],
    *,
    tag_column: str | None = None,
    tag_values: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Count point-like features per H3 cell using an STRtree spatial index.

    Centroid is used for polygon/multipolygon features (e.g. building footprints).

    Parameters
    ----------
    gdf : GeoDataFrame (EPSG:4326)
    h3_ids : list of H3 cell IDs to aggregate into
    tag_column : optional column name to group on (e.g. "building" or "highway")
    tag_values : optional list of values that constitute a "tagged" subset

    Returns
    -------
    dict  {h3_id: {"total": int, "tagged": int}}
        "total"  = count of all features whose centroid falls in this cell
        "tagged" = count of features where tag_column is in tag_values
    """
    if gdf is None or gdf.empty:
        return {h3_id: {"total": 0, "tagged": 0} for h3_id in h3_ids}

    # Normalise to point geometry (centroid for polygons/multipolygons)
    gdf = gdf.copy()
    gdf["_pt"] = gdf.geometry.centroid
    pts = gpd.GeoDataFrame(gdf, geometry="_pt", crs="EPSG:4326")

    # Build spatial index over point centroids
    sindex = pts.sindex

    result: dict[str, dict[str, Any]] = {}
    for h3_id in h3_ids:
        cell_poly = _h3_polygon(h3_id)
        candidate_idx = list(sindex.intersection(cell_poly.bounds))
        if not candidate_idx:
            result[h3_id] = {"total": 0, "tagged": 0}
            continue

        candidates = pts.iloc[candidate_idx]
        inside = candidates[candidates["_pt"].within(cell_poly)]
        total = len(inside)

        tagged = 0
        if tag_column and tag_values and tag_column in inside.columns:
            tagged = int(inside[tag_column].isin(tag_values).sum())

        result[h3_id] = {"total": total, "tagged": tagged}

    return result


# ---------------------------------------------------------------------------
# Public: line length aggregation
# ---------------------------------------------------------------------------

def aggregate_lines_to_h3(
    gdf: gpd.GeoDataFrame,
    h3_ids: list[str],
    city_id: str,
    *,
    tag_column: str | None = None,
    tag_values: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """Sum clipped line lengths (metres) per H3 cell.

    Uses STRtree candidate pre-filtering then shapely intersection for precision.

    Parameters
    ----------
    gdf : GeoDataFrame of linestring features (EPSG:4326)
    h3_ids : H3 cell IDs
    city_id : used to choose UTM projection for metric length
    tag_column : optional tag column for sub-grouping
    tag_values : tag values that define the "tagged" subset (e.g. major roads)

    Returns
    -------
    dict  {h3_id: {"total_m": float, "tagged_m": float}}
    """
    if gdf is None or gdf.empty:
        return {h3_id: {"total_m": 0.0, "tagged_m": 0.0} for h3_id in h3_ids}

    utm = _utm_for_city(city_id)

    # Project once for the whole GeoDataFrame (much faster than per-clip projection)
    gdf_utm = gdf.to_crs(utm)

    # Spatial index on the ORIGINAL (4326) geometries for bbox filtering
    sindex = gdf.sindex

    result: dict[str, dict[str, float]] = {}
    for h3_id in h3_ids:
        cell_poly_4326 = _h3_polygon(h3_id)
        candidate_idx = list(sindex.intersection(cell_poly_4326.bounds))
        if not candidate_idx:
            result[h3_id] = {"total_m": 0.0, "tagged_m": 0.0}
            continue

        # Project cell polygon to UTM for metric computation
        cell_poly_utm = (
            gpd.GeoDataFrame(geometry=[cell_poly_4326], crs="EPSG:4326")
            .to_crs(utm)
            .geometry.iloc[0]
        )

        candidates_utm = gdf_utm.iloc[candidate_idx]
        clipped = candidates_utm.copy()
        clipped["_clipped"] = clipped.geometry.intersection(cell_poly_utm)
        clipped = clipped[~clipped["_clipped"].is_empty]

        total_m = float(clipped["_clipped"].length.sum())

        tagged_m = 0.0
        if tag_column and tag_values and tag_column in clipped.columns:
            mask = clipped[tag_column].isin(tag_values)
            tagged_m = float(clipped.loc[mask, "_clipped"].length.sum())

        result[h3_id] = {"total_m": total_m, "tagged_m": tagged_m}

    return result


# ---------------------------------------------------------------------------
# Utility: generate H3 cell list from bbox
# ---------------------------------------------------------------------------

def cells_for_bbox(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    resolution: int,
) -> list[str]:
    """Return all H3 cells covering the given bounding box."""
    bbox_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min], [lon_max, lat_min],
            [lon_max, lat_max], [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }
    return sorted(h3.geo_to_cells(bbox_geojson, resolution))


# ---------------------------------------------------------------------------
# Utility: H3 cell area in km² (approximate)
# ---------------------------------------------------------------------------

_H3_AREA_KM2: dict[int, float] = {
    7:  5.1612,
    8:  0.7373,
    9:  0.1053,
    10: 0.0150,
}

def cell_area_km2(resolution: int) -> float:
    return _H3_AREA_KM2.get(resolution, 0.7373)
