"""Thin wrapper around osmnx.features_from_bbox with retry and rate-limit sleep.

All four urban-infrastructure ingestors (buildings, roads, drains, crowd) share
this connector.  It normalises the bbox dict convention used throughout this
codebase ({lat_min, lon_min, lat_max, lon_max}) to the osmnx 2.x convention
(left, bottom, right, top) = (lon_min, lat_min, lon_max, lat_max).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import geopandas as gpd

logger = logging.getLogger(__name__)

# Polite delay between consecutive Overpass requests (seconds).
# OSM Overpass is a shared public resource — be a good citizen.
_INTER_REQUEST_SLEEP = 1.5


def fetch_features_for_bbox(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    tags: dict[str, Any],
    *,
    timeout: int = 120,
    retry: int = 2,
    sleep: float = _INTER_REQUEST_SLEEP,
) -> gpd.GeoDataFrame:
    """Fetch OSM features within a lat/lon bbox via the Overpass API.

    Parameters
    ----------
    lat_min, lon_min, lat_max, lon_max : float
        Bounding box in EPSG:4326.
    tags : dict
        OSM tag filter.  Examples::
            {"building": True}
            {"highway": ["primary", "secondary", "residential"]}
            {"waterway": ["drain", "canal"]}
    timeout : int
        Overpass server timeout in seconds (passed to osmnx settings).
    retry : int
        Number of additional attempts after the first failure.
    sleep : float
        Seconds to sleep after each successful request (rate-limit courtesy).

    Returns
    -------
    gpd.GeoDataFrame
        Features in EPSG:4326.  Empty GeoDataFrame on failure.
    """
    import osmnx as ox

    # osmnx 2.x bbox convention: (left, bottom, right, top)
    bbox = (lon_min, lat_min, lon_max, lat_max)

    ox.settings.timeout = timeout

    last_exc: Exception | None = None
    for attempt in range(1 + retry):
        try:
            gdf = ox.features_from_bbox(bbox=bbox, tags=tags)
            if sleep > 0:
                time.sleep(sleep)
            return gdf
        except Exception as exc:
            last_exc = exc
            if attempt < retry:
                wait = (attempt + 1) * 5
                logger.warning(
                    "Overpass request failed (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1, 1 + retry, exc, wait,
                )
                time.sleep(wait)

    logger.error("Overpass request failed after %d attempts: %s", 1 + retry, last_exc)
    return gpd.GeoDataFrame()


def fetch_road_graph_for_bbox(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    *,
    network_type: str = "drive",
    timeout: int = 180,
    retry: int = 2,
    sleep: float = _INTER_REQUEST_SLEEP,
):
    """Fetch the driveable road graph within a bbox for intersection counting.

    Returns
    -------
    networkx.MultiDiGraph or None
    """
    import osmnx as ox

    bbox = (lon_min, lat_min, lon_max, lat_max)
    ox.settings.timeout = timeout

    last_exc: Exception | None = None
    for attempt in range(1 + retry):
        try:
            G = ox.graph_from_bbox(bbox=bbox, network_type=network_type,
                                   retain_all=True, truncate_by_edge=True)
            if sleep > 0:
                time.sleep(sleep)
            return G
        except Exception as exc:
            last_exc = exc
            if attempt < retry:
                wait = (attempt + 1) * 5
                logger.warning(
                    "graph_from_bbox failed (attempt %d/%d): %s — retrying in %ds",
                    attempt + 1, 1 + retry, exc, wait,
                )
                time.sleep(wait)

    logger.error("graph_from_bbox failed after %d attempts: %s", 1 + retry, last_exc)
    return None
