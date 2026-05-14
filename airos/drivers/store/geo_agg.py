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
# Public: hybrid polygon aggregation (centroid for small, area-weighted for large)
# ---------------------------------------------------------------------------

def aggregate_polygons_to_h3(
    gdf: gpd.GeoDataFrame,
    h3_ids: list[str],
    city_id: str,
    *,
    resolution: int = 8,
    large_polygon_threshold: float = 0.25,
    tag_column: str | None = None,
    tag_values: list[str] | None = None,
) -> tuple[dict[str, dict[str, float]], dict[int, str]]:
    """Aggregate polygon features to H3 cells with **hybrid assignment**
    (methodology §1.2-B caveat).

    For each polygon:

    - **Small polygon** (`polygon_area ≤ threshold × cell_area`) → centroid
      assignment. The whole polygon contributes count `1.0` to its host cell.
      Fast path; equivalent to the legacy point-aggregation behaviour.

    - **Large polygon** (`polygon_area > threshold × cell_area`) → area-
      weighted intersection. The polygon's count `1.0` is apportioned across
      every intersecting H3 cell by overlap area fraction. So an industrial
      estate that spans 3 cells with overlaps 0.5/0.3/0.2 of its area
      contributes 0.5/0.3/0.2 to each cell respectively. This eliminates
      the under-counting of exposure in adjacent cells that pure centroid
      assignment produces.

    Parameters
    ----------
    gdf : GeoDataFrame of polygon features (EPSG:4326).
    h3_ids : H3 cell IDs to aggregate into.
    city_id : used to choose UTM projection for metric area computation.
    resolution : H3 resolution of `h3_ids` — used to compute cell area for
        the small/large split.
    large_polygon_threshold : fraction of cell area above which a polygon
        is treated as large. Default 0.25 (25% of cell area).
    tag_column, tag_values : optional sub-grouping (same semantics as
        `aggregate_points_to_h3`).

    Returns
    -------
    counts_by_cell : {h3_id: {"total": float, "tagged": float}}
        Float counts because large polygons contribute fractional amounts.
    assignment_methods : {feature_index: "centroid" | "area_weighted"}
        Useful for stamping `geometry_assignment_method` on per-feature
        side tables (e.g. `poi_points`).
    """
    if gdf is None or gdf.empty:
        return (
            {h3_id: {"total": 0.0, "tagged": 0.0} for h3_id in h3_ids},
            {},
        )

    utm        = _utm_for_city(city_id)
    cell_area_m2 = cell_area_km2(resolution) * 1_000_000  # km² → m²

    # Project once for fast area + intersection math.
    gdf_utm = gdf.to_crs(utm)
    gdf_utm = gdf_utm.copy()
    gdf_utm["_area_m2"] = gdf_utm.geometry.area

    # Initialise counters
    counts: dict[str, dict[str, float]] = {
        h3_id: {"total": 0.0, "tagged": 0.0} for h3_id in h3_ids
    }
    assignment_methods: dict[int, str] = {}

    # Spatial index in the source (4326) CRS for cell-bbox candidate selection
    sindex = gdf.sindex

    # Pre-compute H3 cell polygons in 4326 + UTM for intersection math
    cell_polys_4326 = {h3_id: _h3_polygon(h3_id) for h3_id in h3_ids}
    cell_polys_utm_series = gpd.GeoSeries(
        list(cell_polys_4326.values()), crs="EPSG:4326",
    ).to_crs(utm)
    cell_polys_utm = dict(zip(cell_polys_4326.keys(), cell_polys_utm_series))

    h3_id_set = set(h3_ids)

    for idx, feature in gdf_utm.iterrows():
        geom_utm  = feature.geometry
        area_m2   = float(feature["_area_m2"])
        is_large  = area_m2 > large_polygon_threshold * cell_area_m2
        tagged    = (
            tag_column and tag_values and tag_column in gdf.columns
            and gdf.loc[idx, tag_column] in tag_values
        )

        if not is_large:
            # Small polygon — centroid assignment (back-compat fast path).
            try:
                centroid = feature.geometry.centroid
                # Project centroid back to lat/lon for h3
                centroid_4326 = (
                    gpd.GeoSeries([centroid], crs=utm)
                    .to_crs("EPSG:4326").iloc[0]
                )
                cell = h3.latlng_to_cell(centroid_4326.y, centroid_4326.x, resolution)
            except Exception:
                continue
            if cell in h3_id_set:
                counts[cell]["total"] += 1.0
                if tagged:
                    counts[cell]["tagged"] += 1.0
                assignment_methods[idx] = "centroid"
            continue

        # Large polygon — area-weighted intersection across candidate cells.
        candidate_idx = list(sindex.intersection(gdf.loc[idx].geometry.bounds))
        # `sindex.intersection` returns indices INTO gdf — not h3_ids. We need
        # to walk h3_ids and intersect with each candidate's cell polygon.
        # Simpler: iterate the candidate h3_ids by bbox.
        polygon_bounds = gdf_utm.geometry[idx].bounds
        # Use cell-bbox prefilter: iterate all h3 cells but skip those whose
        # bbox doesn't intersect the polygon's bbox.
        any_assigned = False
        for h3_id, cell_poly in cell_polys_utm.items():
            cb = cell_poly.bounds
            if (cb[2] < polygon_bounds[0] or cb[0] > polygon_bounds[2]
                or cb[3] < polygon_bounds[1] or cb[1] > polygon_bounds[3]):
                continue   # no bbox overlap
            try:
                inter = geom_utm.intersection(cell_poly)
            except Exception:
                continue
            if inter.is_empty:
                continue
            frac = inter.area / area_m2 if area_m2 > 0 else 0
            if frac <= 0:
                continue
            counts[h3_id]["total"] += float(frac)
            if tagged:
                counts[h3_id]["tagged"] += float(frac)
            any_assigned = True
        if any_assigned:
            assignment_methods[idx] = "area_weighted"

    return counts, assignment_methods


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
