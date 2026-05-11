"""Buildings domain ingestor — OSM building footprints → per-H3-cell statistics.

Signals written (domain="buildings", source="osm"):
    BUILDING_COUNT        count      Number of buildings with centroid in cell
    BUILDING_DENSITY      per_km2    BUILDING_COUNT / cell_area_km2
    AVG_FLOORS            floors     Mean of building:levels tag (default 1 when missing)
    COMMERCIAL_RATIO      ratio      Fraction of buildings with commercial/retail tag

These are structural signals — they do NOT produce h3_assessments entries.
The H3 Expert Agent reads them as static context for reasoning about
population exposure and urban density.

Refresh cadence: weekly (OSM data changes slowly).
Data confidence: 0.75 (OSM building coverage is good in Indian cities for
                        major structures; informal structures may be missing).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# OSM tags that indicate commercial/retail use
_COMMERCIAL_TAGS = {
    "commercial", "retail", "office", "shop", "supermarket",
    "marketplace", "mall", "bank", "fuel",
}

# OSM building tags to query
_BUILDING_TAGS: dict = {"building": True}

# Data confidence for coverage signal
from airos.os.rules import rules as _rules

def _data_confidence() -> float:
    return _rules.get("buildings", "data_confidence", default=0.75)


def ingest_buildings(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch OSM building features for the city bbox and write per-cell signals.

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
        aggregate_points_to_h3, cells_for_bbox, cell_area_km2,
    )
    from airos.drivers.connectors.geospatial.overpass_bbox import fetch_features_for_bbox
    import numpy as np

    try:
        _check_interval("buildings", city_id, force)
    except Exception as e:
        logger.info("[%s/buildings] %s", city_id, e)
        return 0

    logger.info("[%s/buildings] Fetching OSM building footprints …", city_id)
    gdf = fetch_features_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        tags=_BUILDING_TAGS,
    )

    if gdf.empty:
        logger.info("[%s/buildings] No OSM building data returned.", city_id)
        record_ingest(city_id=city_id, domain="buildings", rows_written=0,
                      status="partial", error_msg="overpass returned empty")
        return 0

    logger.info("[%s/buildings] %d building features fetched. Aggregating …",
                city_id, len(gdf))

    # Generate H3 cells for bbox
    h3_ids = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )
    area_km2 = cell_area_km2(DEFAULT_H3_RES)

    # Extract floors and commercial tags before point aggregation
    gdf = gdf.copy()
    gdf["_floors"] = (
        gdf.get("building:levels", None)
        .pipe(lambda s: s if s is not None else gdf.get("building:levels"))
    )
    # Coerce to numeric, default to 1 when missing
    if "_floors" not in gdf.columns:
        gdf["_floors"] = 1.0
    else:
        gdf["_floors"] = (
            gdf["_floors"]
            .astype(str)
            .str.extract(r"(\d+)", expand=False)
            .astype(float)
            .fillna(1.0)
        )

    # Commercial building flag
    building_col = "building" if "building" in gdf.columns else None
    if building_col:
        gdf["_commercial"] = gdf[building_col].isin(_COMMERCIAL_TAGS)
    else:
        gdf["_commercial"] = False

    # Spatial aggregation — count buildings per cell
    counts = aggregate_points_to_h3(
        gdf, h3_ids,
        tag_column=building_col,
        tag_values=list(_COMMERCIAL_TAGS),
    )

    # Per-cell floor and commercial averages using centroid-based assignment
    # Build a quick lookup: H3 cell → rows
    import h3 as _h3
    gdf["_centroid"] = gdf.geometry.centroid
    gdf["_h3_cell"] = gdf["_centroid"].apply(
        lambda pt: _h3.latlng_to_cell(pt.y, pt.x, DEFAULT_H3_RES)
        if pt is not None and not pt.is_empty else None
    )
    cell_groups = gdf[gdf["_h3_cell"].notna()].groupby("_h3_cell")
    floors_by_cell = cell_groups["_floors"].mean().to_dict()
    commercial_ratio_by_cell = cell_groups["_commercial"].mean().to_dict()

    # Write signals
    signal_rows: list[dict] = []
    for h3_id in h3_ids:
        c = counts.get(h3_id, {"total": 0, "tagged": 0})
        total = c["total"]

        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        density = round(total / area_km2, 2) if total > 0 else 0.0
        avg_floors = round(float(floors_by_cell.get(h3_id, 1.0)), 2)
        comm_ratio = round(float(commercial_ratio_by_cell.get(h3_id, 0.0)), 4)

        signal_rows += [
            {"h3_id": h3_id, "signal": "BUILDING_COUNT",    "value": float(total),    "unit": "count"},
            {"h3_id": h3_id, "signal": "BUILDING_DENSITY",  "value": density,          "unit": "per_km2"},
            {"h3_id": h3_id, "signal": "AVG_FLOORS",        "value": avg_floors,       "unit": "floors"},
            {"h3_id": h3_id, "signal": "COMMERCIAL_RATIO",  "value": comm_ratio,       "unit": "ratio"},
            # Data confidence (static for OSM-derived structural signals)
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",   "value": _data_confidence(), "unit": "ratio"},
        ]

    written = write_signals(signal_rows, city_id=city_id, domain="buildings", source="osm")
    logger.info("[%s/buildings] %d cells × 5 signals = %d rows written.",
                city_id, len(h3_ids), written)
    record_ingest(city_id=city_id, domain="buildings", rows_written=written)
    return written
