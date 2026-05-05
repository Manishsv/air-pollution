from __future__ import annotations

import logging
from typing import Iterable, List

import geopandas as gpd
import numpy as np
import h3
from shapely.geometry import MultiPolygon, Polygon


logger = logging.getLogger(__name__)


def _polygon_to_latlngpoly(poly: Polygon) -> h3.LatLngPoly:
    # Shapely coords are (lon, lat). H3 expects (lat, lon).
    exterior = [(lat, lon) for lon, lat in list(poly.exterior.coords)]
    holes = []
    for ring in poly.interiors:  # important: interiors (not interior)
        holes.append([(lat, lon) for lon, lat in list(ring.coords)])
    return h3.LatLngPoly(exterior, holes)


def _geometry_to_cells(geom: Polygon | MultiPolygon, resolution: int) -> List[str]:
    cells: List[str] = []
    if isinstance(geom, Polygon):
        cells = list(h3.polygon_to_cells(_polygon_to_latlngpoly(geom), resolution))
    elif isinstance(geom, MultiPolygon):
        for p in geom.geoms:
            cells.extend(list(h3.polygon_to_cells(_polygon_to_latlngpoly(p), resolution)))
    else:
        raise TypeError(f"Unsupported geometry type for H3 grid: {type(geom)}")
    return sorted(list(set(cells)))


def create_h3_grid(boundary_wgs84: gpd.GeoDataFrame, resolution: int) -> gpd.GeoDataFrame:
    boundary_wgs84 = boundary_wgs84.to_crs("EPSG:4326")
    geom = boundary_wgs84.geometry.iloc[0]

    if geom is None or geom.is_empty:
        raise ValueError("Boundary geometry is empty; cannot create H3 grid.")

    if geom.geom_type == "GeometryCollection":
        geom = geom.buffer(0)

    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        geom = geom.convex_hull

    cells = _geometry_to_cells(geom, resolution)
    if not cells:
        raise ValueError("H3 grid creation returned 0 cells; check boundary and resolution.")

    polygons = []
    centroids = []
    for c in cells:
        # h3.cell_to_boundary returns (lat, lon)
        coords_latlon = h3.cell_to_boundary(c)
        coords_lonlat = [(lon, lat) for lat, lon in coords_latlon]
        poly = Polygon(coords_lonlat)
        polygons.append(poly)
        cent = poly.centroid
        centroids.append((cent.y, cent.x))  # lat, lon

    gdf = gpd.GeoDataFrame(
        {
            "h3_id": cells,
            "centroid_lat": [c[0] for c in centroids],
            "centroid_lon": [c[1] for c in centroids],
        },
        geometry=polygons,
        crs="EPSG:4326",
    )

    # Area in sqkm needs projected/metric CRS.
    gdf_proj = gdf.to_crs(boundary_wgs84.estimate_utm_crs() or "EPSG:32643")
    area_sqkm = (gdf_proj.geometry.area / 1e6).astype(float)
    gdf["area_sqkm"] = area_sqkm.values
    return gdf

