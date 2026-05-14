"""Roads domain ingestor — OSM road network → per-H3-cell signals.

Signals written (domain="roads", source="osm"):
    ROAD_LENGTH_M         metres     Total clipped road length in cell
    ROAD_DENSITY          m_per_km2  ROAD_LENGTH_M / cell_area_km2
    MAJOR_ROAD_RATIO      ratio      Length of primary/secondary/trunk roads
                                     as fraction of total road length
    INTERSECTION_COUNT    count      Number of road intersections inside cell
    DATA_CONFIDENCE       ratio      0.85 (OSM road network is well-mapped in
                                     Indian cities; minor lanes may be missing)

Why no h3_assessments?
    Road density is structural context — not a risk signal.  The H3 Expert
    Agent uses it to reason about pollution-source proximity (traffic emissions),
    heat islands (impervious surface), and flood drainage blockage risk.

Road type hierarchy (OpenStreetMap `highway=` values):
    Major: motorway, trunk, primary, secondary (and _link variants)
    Minor: tertiary, residential, unclassified, service, living_street, etc.

Refresh cadence: weekly (road network changes slowly).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# OSM highway tags to fetch — excludes footways/cycleways/paths
# to keep the dataset focused on vehicle-accessible roads.
_ROAD_TAGS: dict = {
    "highway": [
        "motorway", "motorway_link",
        "trunk", "trunk_link",
        "primary", "primary_link",
        "secondary", "secondary_link",
        "tertiary", "tertiary_link",
        "residential", "unclassified",
        "service", "living_street",
        "road",
    ],
}

# Tag values that count as "major" roads
_MAJOR_ROAD_VALUES = {
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
}

from airos.os.rules import rules as _rules

def _data_confidence() -> float:
    return _rules.get("roads", "data_confidence", default=0.85)


def ingest_roads(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch OSM road network for the city bbox and write per-cell signals.

    Parameters
    ----------
    city_id : str
    bbox    : dict with keys lat_min, lon_min, lat_max, lon_max
    force   : skip the watermark interval check

    Returns
    -------
    int — number of signal rows written
    """
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import (
        write_signals, upsert_metadata, record_ingest,
    )
    from airos.drivers.store.geo_agg import (
        aggregate_lines_to_h3, cells_for_bbox, cell_area_km2,
    )
    from airos.drivers.connectors.geospatial.overpass_bbox import (
        fetch_features_for_bbox, fetch_road_graph_for_bbox,
    )

    try:
        _check_interval("roads", city_id, force)
    except Exception as e:
        logger.info("[%s/roads] %s", city_id, e)
        return 0

    logger.info("[%s/roads] Fetching OSM road network …", city_id)
    gdf = fetch_features_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        tags=_ROAD_TAGS,
    )

    if gdf.empty:
        logger.info("[%s/roads] No OSM road data returned.", city_id)
        record_ingest(city_id=city_id, domain="roads", rows_written=0,
                      status="partial", error_msg="overpass returned empty")
        return 0

    logger.info("[%s/roads] %d road features fetched. Aggregating …",
                city_id, len(gdf))

    h3_ids   = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )
    area_km2 = cell_area_km2(DEFAULT_H3_RES)

    # Line-length aggregation (uses UTM projection for metric accuracy)
    lengths = aggregate_lines_to_h3(
        gdf, h3_ids, city_id,
        tag_column="highway",
        tag_values=list(_MAJOR_ROAD_VALUES),
    )

    # Intersection count — use osmnx graph nodes (degree ≥ 3)
    # Gracefully skip if graph fetch fails
    intersection_by_cell: dict[str, int] = {}
    try:
        G = fetch_road_graph_for_bbox(
            bbox["lat_min"], bbox["lon_min"],
            bbox["lat_max"], bbox["lon_max"],
        )
        if G is not None:
            import h3 as _h3
            import osmnx as ox
            # Nodes with degree ≥ 3 in undirected projection = intersections
            nodes_gdf, _ = ox.graph_to_gdfs(G)
            # osmnx node GDF has lat/lon in index or geometry column
            if "geometry" in nodes_gdf.columns:
                for _, node in nodes_gdf.iterrows():
                    pt = node.geometry
                    if pt is None or pt.is_empty:
                        continue
                    cell = _h3.latlng_to_cell(pt.y, pt.x, DEFAULT_H3_RES)
                    if cell in intersection_by_cell:
                        intersection_by_cell[cell] += 1
                    else:
                        intersection_by_cell[cell] = 1
    except Exception as exc:
        logger.warning("[%s/roads] Intersection count skipped: %s", city_id, exc)

    # ── Write signals ──────────────────────────────────────────────────────
    signal_rows: list[dict] = []
    for h3_id in h3_ids:
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        c = lengths.get(h3_id, {"total_m": 0.0, "tagged_m": 0.0})
        total_m  = c["total_m"]
        major_m  = c["tagged_m"]

        density       = round(total_m / area_km2, 2) if total_m > 0 else 0.0
        major_ratio   = round(major_m / total_m, 4) if total_m > 0 else 0.0
        intersections = float(intersection_by_cell.get(h3_id, 0))

        signal_rows += [
            {"h3_id": h3_id, "signal": "ROAD_LENGTH_M",      "value": round(total_m, 1),  "unit": "metres"},
            {"h3_id": h3_id, "signal": "ROAD_DENSITY",        "value": density,             "unit": "m_per_km2"},
            {"h3_id": h3_id, "signal": "MAJOR_ROAD_RATIO",    "value": major_ratio,         "unit": "ratio"},
            {"h3_id": h3_id, "signal": "INTERSECTION_COUNT",  "value": intersections,       "unit": "count"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",     "value": _data_confidence(),  "unit": "ratio"},
        ]

    written = write_signals(
        signal_rows, city_id=city_id, domain="roads", source="osm",
        geometry_assignment_method="line_clip",
    )
    logger.info("[%s/roads] %d cells × 5 signals = %d rows written.",
                city_id, len(h3_ids), written)
    record_ingest(city_id=city_id, domain="roads", rows_written=written)
    return written
