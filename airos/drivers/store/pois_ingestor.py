"""POI domain ingestor — OSM points-of-interest → per-H3-cell category counts.

Adds structural context that helps the cause classifier and the LLM attribute
elevated-pollution events to specific source types (industrial, kiln, fuel
station, etc.) rather than generic land-use proxies.

Signals written (domain="pois", source="osm"):
    POI_INDUSTRIAL_COUNT       Industrial facilities (landuse, works, chimney)
    POI_CONSTRUCTION_COUNT     Active or tagged construction sites
    POI_FUEL_STATION_COUNT     Petrol/diesel pumps (VOC + idling source)
    POI_KILN_COUNT             Brick kilns and standalone kilns (biomass PM)
    POI_EATERY_COUNT           Restaurants, dhabas, cafes (cooking emissions)
    POI_CREMATORIUM_COUNT      Crematoria (intermittent biomass burning)
    POI_WASTE_FACILITY_COUNT   Transfer stations, recycling, disposal sites
    POI_MARKET_COUNT           Markets and large retail (activity + waste)
    POI_TRANSIT_TERMINAL_COUNT Bus stations etc. (diesel idling clusters)
    POI_HOSPITAL_COUNT         Vulnerable-population exposure indicator
    POI_SCHOOL_COUNT           Vulnerable-population exposure indicator
    DATA_CONFIDENCE            Static OSM coverage confidence

Refresh cadence: quarterly (POIs change slowly; OSM coverage updates monthly).
Data confidence: 0.6 (OSM POI coverage in Indian cities varies — major
                       industries usually present, small kilns often missing).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Categories we emit signals for, in priority order (first match wins
# when a feature carries multiple tag keys).
POI_CATEGORIES = [
    "KILN", "CREMATORIUM", "FUEL_STATION", "WASTE_FACILITY",
    "INDUSTRIAL", "CONSTRUCTION", "EATERY", "MARKET",
    "TRANSIT_TERMINAL", "HOSPITAL", "SCHOOL",
]

# OSM tag union used in a single Overpass query.
# osmnx treats multiple keys as a union (feature matching ANY pair is returned).
_OSM_TAG_QUERY = {
    "amenity": [
        "fuel", "restaurant", "cafe", "fast_food", "food_court",
        "crematorium", "marketplace", "bus_station",
        "hospital", "clinic",
        "school", "college", "university", "kindergarten",
        "waste_transfer_station", "waste_disposal", "recycling",
    ],
    "landuse":  ["industrial", "construction"],
    "man_made": ["works", "chimney", "kiln"],
    "building": ["construction", "industrial", "warehouse"],
    "industrial": True,
    "shop":     ["supermarket", "mall"],
}

_DATA_CONFIDENCE = 0.6


def _val(row, key) -> str:
    """Get a tag value as lowercase string, or empty string."""
    v = row.get(key)
    if v is None:
        return ""
    # osmnx returns NaN for missing tags
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return ""
    except Exception:
        pass
    return str(v).lower().strip()


def _classify(row) -> Optional[str]:
    """Map a feature's OSM tags to the **single most-specific** POI_CATEGORY.

    Kept as the priority-ordered top match for back-compat with the
    `POI_*_COUNT` per-cell aggregate signals. For features that fit multiple
    categories (e.g. a market that's also a transit hub), use
    `_classify_all_tags()` which returns the full set so consumers can
    decide whether to use primary or secondary tags.
    """
    tags = _classify_all_tags(row)
    return tags[0] if tags else None


def _classify_all_tags(row) -> list[str]:
    """Return every category this feature matches, in priority order.

    Methodology §D.16: a hospital with an eatery, a market that doubles as
    a transit hub, or industrial land carrying a waste facility can fit
    multiple categories. The single-category collapse loses this. This
    helper returns `primary_category` (index 0) plus any `secondary_tags`
    (indices 1..N) so downstream code can preserve the full label set.
    """
    amenity   = _val(row, "amenity")
    landuse   = _val(row, "landuse")
    man_made  = _val(row, "man_made")
    building  = _val(row, "building")
    industrial_tag = _val(row, "industrial")
    shop      = _val(row, "shop")

    tags: list[str] = []

    # Priority-ordered checks. Each appends to the list independently;
    # the FIRST match becomes the primary, the rest are secondary.
    if man_made == "kiln" or industrial_tag == "brick_yard":
        tags.append("KILN")
    if amenity == "crematorium":
        tags.append("CREMATORIUM")
    if amenity == "fuel":
        tags.append("FUEL_STATION")
    if amenity in ("waste_transfer_station", "waste_disposal", "recycling"):
        tags.append("WASTE_FACILITY")
    if (
        landuse == "industrial"
        or man_made in ("works", "chimney")
        or industrial_tag
        or building in ("industrial", "warehouse")
    ):
        tags.append("INDUSTRIAL")
    if landuse == "construction" or building == "construction":
        tags.append("CONSTRUCTION")
    if amenity in ("restaurant", "cafe", "fast_food", "food_court"):
        tags.append("EATERY")
    if amenity == "marketplace" or shop in ("supermarket", "mall"):
        tags.append("MARKET")
    if amenity == "bus_station":
        tags.append("TRANSIT_TERMINAL")
    if amenity in ("hospital", "clinic"):
        tags.append("HOSPITAL")
    if amenity in ("school", "college", "university", "kindergarten"):
        tags.append("SCHOOL")
    return tags


def ingest_pois(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch OSM POIs for the bbox, classify, aggregate to H3, write signals.

    Returns
    -------
    int — number of signal rows written
    """
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import write_signals, upsert_metadata, record_ingest
    from airos.drivers.store.geo_agg import cells_for_bbox
    from airos.drivers.connectors.geospatial.overpass_bbox import fetch_features_for_bbox
    import h3 as _h3

    try:
        _check_interval("pois", city_id, force)
    except Exception as e:
        logger.info("[%s/pois] %s", city_id, e)
        return 0

    logger.info("[%s/pois] Fetching OSM POIs …", city_id)
    gdf = fetch_features_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        tags=_OSM_TAG_QUERY,
    )

    h3_ids = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )

    # Initialise per-cell counters
    counts: dict[str, dict[str, int]] = {
        h: {cat: 0 for cat in POI_CATEGORIES} for h in h3_ids
    }

    poi_point_rows: list[dict] = []

    if gdf is None or gdf.empty:
        logger.info("[%s/pois] Overpass returned no features.", city_id)
    else:
        logger.info("[%s/pois] %d candidate features fetched. Classifying …",
                    city_id, len(gdf))

        # Compute centroid for each feature (works for points + polygons)
        gdf = gdf.copy()
        gdf["_centroid"] = gdf.geometry.centroid

        # Per-feature category + h3 mapping (multi-tag aware — §D.16).
        # `all_tags[0]` is the primary category (used for the count signal
        # and back-compat with single-category consumers). `all_tags[1:]`
        # are secondary tags persisted in `poi_points.secondary_tags_json`
        # so the cause classifier and dossier can reason over multiplicity.
        classified = 0
        for idx, row in gdf.iterrows():
            all_tags = _classify_all_tags(row)
            if not all_tags:
                continue
            cat = all_tags[0]
            secondary = all_tags[1:]
            pt = row["_centroid"]
            if pt is None or pt.is_empty:
                continue
            try:
                cell = _h3.latlng_to_cell(pt.y, pt.x, DEFAULT_H3_RES)
            except Exception:
                continue
            cell_counts = counts.get(cell)
            if cell_counts is None:
                continue   # feature outside city bbox cells
            cell_counts[cat] += 1
            classified += 1

            # OSM index is a (element_type, osmid) tuple → derive a stable id
            try:
                osm_type, osm_id = idx
                poi_id = f"{osm_type}_{osm_id}"
            except Exception:
                poi_id = f"poi_{cell}_{classified}"

            poi_point_rows.append({
                "poi_id":    poi_id,
                "city_id":   city_id,
                "secondary_tags": secondary,
                "h3_id":     cell,
                "category":  cat,
                "name":      _val(row, "name") or None,
                "latitude":  float(pt.y),
                "longitude": float(pt.x),
            })

        logger.info("[%s/pois] %d features classified into POI categories.",
                    city_id, classified)

    # Write individual POI points (for map display)
    _write_poi_points(city_id, poi_point_rows)

    # Write signals
    signal_rows: list[dict] = []
    for h3_id in h3_ids:
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        cell_counts = counts[h3_id]
        for cat in POI_CATEGORIES:
            signal_rows.append({
                "h3_id": h3_id,
                "signal": f"POI_{cat}_COUNT",
                "value": float(cell_counts[cat]),
                "unit": "count",
            })
        signal_rows.append({
            "h3_id": h3_id,
            "signal": "DATA_CONFIDENCE",
            "value": _DATA_CONFIDENCE,
            "unit": "ratio",
        })

    written = write_signals(
        signal_rows,
        city_id=city_id, domain="pois", source="osm",
        geometry_assignment_method="centroid",
    )
    logger.info(
        "[%s/pois] %d cells × %d signals = %d rows written.",
        city_id, len(h3_ids), len(POI_CATEGORIES) + 1, written,
    )
    record_ingest(city_id=city_id, domain="pois", rows_written=written)
    return written


def _write_poi_points(city_id: str, rows: list[dict]) -> int:
    """Replace this city's poi_points with the freshly classified set."""
    if not rows:
        logger.info("[%s/pois] No POI points to persist.", city_id)
        return 0

    import json
    import sqlite3
    from airos.drivers.store.schema import DB_PATH, DDL_POI_POINTS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Make sure table + indexes exist (first-time creation on this DB).
        conn.executescript(DDL_POI_POINTS)
        # The Tranche C `secondary_tags_json` column is added via migration in
        # store.py; on a fresh DB the CREATE above already includes it.
        # Re-ingestion replaces all of this city's POIs in one transaction.
        conn.execute("DELETE FROM poi_points WHERE city_id = ?", (city_id,))
        conn.executemany(
            """
            INSERT OR REPLACE INTO poi_points
                (poi_id, city_id, h3_id, category, secondary_tags_json,
                 name, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["poi_id"], r["city_id"], r["h3_id"], r["category"],
                    json.dumps(r.get("secondary_tags") or []) or None,
                    r.get("name"), r["latitude"], r["longitude"],
                )
                for r in rows
            ],
        )
        conn.commit()
        logger.info(
            "[%s/pois] %d POI points persisted; %d had >1 category tag.",
            city_id, len(rows),
            sum(1 for r in rows if r.get("secondary_tags")),
        )
        return len(rows)
    finally:
        conn.close()
