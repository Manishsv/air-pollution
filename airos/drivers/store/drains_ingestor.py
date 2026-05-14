"""Drains domain ingestor — OSM waterway features → per-H3-cell signals.

Signals written (domain="drains", source="osm"):
    DRAIN_LENGTH_M        metres     Total clipped length of drains/canals in cell
    WATERWAY_COUNT        count      Number of distinct waterway features in cell
    OPEN_DRAIN_RATIO      ratio      Fraction of waterway length that is open
                                     (drain, canal, ditch vs. culvert/underground)
    FLOOD_DRAIN_CAPACITY  index      Proxy 0–1: normalised drain density relative
                                     to area — higher = more drainage capacity
    DATA_CONFIDENCE       ratio      0.65 (OSM drain coverage is patchy; open
                                     drains in informal settlements often unmapped)

Why no h3_assessments?
    Drain density is structural context, not a risk domain.  The H3 Expert
    Agent uses it to modulate flood risk — low drain density + high rainfall
    → elevated flood concern regardless of terrain alone.

OSM waterway tag hierarchy used:
    Open  : drain, canal, ditch, stream, river
    Closed: culvert (typically underground or covered)

Refresh cadence: weekly.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# OSM tags that return waterway features (lines)
_WATERWAY_TAGS: dict = {
    "waterway": [
        "river", "stream", "canal",
        "drain", "ditch",
        "culvert",         # included so we can compute open vs closed ratio
    ],
}

# Values that count as "open" drainage (not culvert/underground)
_OPEN_WATERWAY_VALUES = {"river", "stream", "canal", "drain", "ditch"}

from airos.os.rules import rules as _rules

def _data_confidence() -> float:
    return _rules.get("drains", "data_confidence", default=0.65)

def _drain_saturation() -> float:
    return _rules.get("drains", "flood_drain_saturation_m_per_km2", default=10_000.0)


def ingest_drains(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch OSM waterway features for the city bbox and write per-cell signals.

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
        aggregate_lines_to_h3, aggregate_points_to_h3,
        cells_for_bbox, cell_area_km2,
    )
    from airos.drivers.connectors.geospatial.overpass_bbox import fetch_features_for_bbox

    try:
        _check_interval("drains", city_id, force)
    except Exception as e:
        logger.info("[%s/drains] %s", city_id, e)
        return 0

    logger.info("[%s/drains] Fetching OSM waterway features …", city_id)
    gdf = fetch_features_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        tags=_WATERWAY_TAGS,
    )

    if gdf.empty:
        logger.info("[%s/drains] No OSM waterway data returned.", city_id)
        record_ingest(city_id=city_id, domain="drains", rows_written=0,
                      status="partial", error_msg="overpass returned empty")
        return 0

    logger.info("[%s/drains] %d waterway features fetched. Aggregating …",
                city_id, len(gdf))

    h3_ids   = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )
    area_km2 = cell_area_km2(DEFAULT_H3_RES)

    # Separate line features from point/polygon features
    # OSM waterways are predominantly LineStrings; nodes (e.g. river confluences)
    # are filtered out to avoid length-sum errors on point geometries.
    from shapely.geometry import LineString, MultiLineString
    import pandas as pd

    line_mask = gdf.geometry.apply(
        lambda g: isinstance(g, (LineString, MultiLineString)) if g is not None else False
    )
    line_gdf  = gdf[line_mask]
    point_gdf = gdf[~line_mask]  # polygons and nodes counted separately

    # Aggregate line lengths (total + open-drain subset)
    if line_gdf.empty:
        lengths: dict = {h3_id: {"total_m": 0.0, "tagged_m": 0.0} for h3_id in h3_ids}
    else:
        lengths = aggregate_lines_to_h3(
            line_gdf, h3_ids, city_id,
            tag_column="waterway",
            tag_values=list(_OPEN_WATERWAY_VALUES),
        )

    # Count distinct waterway features (points + line centroids) per cell
    # This gives WATERWAY_COUNT regardless of feature type.
    feature_counts = aggregate_points_to_h3(gdf, h3_ids)

    # ── Write signals ──────────────────────────────────────────────────────
    signal_rows: list[dict] = []
    for h3_id in h3_ids:
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        c        = lengths.get(h3_id, {"total_m": 0.0, "tagged_m": 0.0})
        total_m  = c["total_m"]
        open_m   = c["tagged_m"]

        wwy_count   = float(feature_counts.get(h3_id, {}).get("total", 0))
        open_ratio  = round(open_m / total_m, 4) if total_m > 0 else 0.0

        # Flood drain capacity index [0, 1]: normalised drain density
        density_m_per_km2 = (total_m / area_km2) * 1000 if total_m > 0 else 0.0
        capacity_idx = round(
            min(density_m_per_km2 / _drain_saturation(), 1.0),
            4,
        )

        signal_rows += [
            {"h3_id": h3_id, "signal": "DRAIN_LENGTH_M",       "value": round(total_m, 1), "unit": "metres"},
            {"h3_id": h3_id, "signal": "WATERWAY_COUNT",        "value": wwy_count,         "unit": "count"},
            {"h3_id": h3_id, "signal": "OPEN_DRAIN_RATIO",      "value": open_ratio,        "unit": "ratio"},
            {"h3_id": h3_id, "signal": "FLOOD_DRAIN_CAPACITY",  "value": capacity_idx,      "unit": "index"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",       "value": _data_confidence(), "unit": "ratio"},
        ]

    written = write_signals(
        signal_rows, city_id=city_id, domain="drains", source="osm",
        geometry_assignment_method="line_clip",
    )
    logger.info("[%s/drains] %d cells × 5 signals = %d rows written.",
                city_id, len(h3_ids), written)
    record_ingest(city_id=city_id, domain="drains", rows_written=written)
    return written
