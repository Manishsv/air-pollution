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
        aggregate_points_to_h3, aggregate_polygons_to_h3,
        cells_for_bbox, cell_area_km2,
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

    # Extract floors with **explicit missingness tracking** (methodology
    # §D.13 caveat). Earlier versions defaulted every missing `building:levels`
    # to 1 — biasing the mean systematically downward. Now we:
    #   * keep `AVG_FLOORS_OBSERVED` = mean over buildings with the tag
    #   * emit `FLOORS_MISSING_RATIO` separately so the agent can see it
    #   * keep `AVG_FLOORS` for back-compat but compute it the same way
    #     (no longer defaults to 1 — uses observed-only mean, or NaN→1.0
    #     fallback only when zero buildings have the tag in the cell)
    gdf = gdf.copy()
    if "building:levels" not in gdf.columns:
        gdf["_floors_raw"] = float("nan")
    else:
        gdf["_floors_raw"] = (
            gdf["building:levels"]
            .astype(str)
            .str.extract(r"(\d+)", expand=False)
            .astype(float)
        )
    gdf["_floors_observed"] = gdf["_floors_raw"].notna()

    # Commercial building flag
    building_col = "building" if "building" in gdf.columns else None
    if building_col:
        gdf["_commercial"] = gdf[building_col].isin(_COMMERCIAL_TAGS)
    else:
        gdf["_commercial"] = False

    # Spatial aggregation — hybrid centroid (small polygons) + area-weighted
    # (large polygons that span multiple cells). See methodology §1.2-B.
    # For typical urban building footprints (well under 25% of cell area)
    # this behaves identically to the legacy centroid-only path; only the
    # rare large polygons (industrial estates, malls, campuses) take the
    # area-weighted path and contribute fractional counts to adjacent cells.
    counts, _assignment_methods = aggregate_polygons_to_h3(
        gdf, h3_ids, city_id=city_id,
        resolution=DEFAULT_H3_RES,
        large_polygon_threshold=0.25,
        tag_column=building_col,
        tag_values=list(_COMMERCIAL_TAGS),
    )

    # Per-cell floor and commercial averages using centroid-based assignment
    import h3 as _h3
    gdf["_centroid"] = gdf.geometry.centroid
    gdf["_h3_cell"] = gdf["_centroid"].apply(
        lambda pt: _h3.latlng_to_cell(pt.y, pt.x, DEFAULT_H3_RES)
        if pt is not None and not pt.is_empty else None
    )
    cell_groups = gdf[gdf["_h3_cell"].notna()].groupby("_h3_cell")
    # AVG_FLOORS_OBSERVED: mean of `building:levels` over buildings where
    # the tag is present (NaN-skipping). Cells with zero observed levels
    # land in the dict with NaN.
    avg_floors_observed_by_cell = cell_groups["_floors_raw"].mean().to_dict()
    # FLOORS_MISSING_RATIO: fraction of buildings in the cell lacking the
    # explicit `building:levels` tag.
    floors_missing_ratio_by_cell = (1 - cell_groups["_floors_observed"].mean()).to_dict()
    commercial_ratio_by_cell = cell_groups["_commercial"].mean().to_dict()

    # Write signals
    signal_rows: list[dict] = []
    _math_isnan = lambda v: isinstance(v, float) and v != v   # noqa: E731
    for h3_id in h3_ids:
        c = counts.get(h3_id, {"total": 0, "tagged": 0})
        total = c["total"]

        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        density    = round(total / area_km2, 2) if total > 0 else 0.0
        avg_obs    = avg_floors_observed_by_cell.get(h3_id)
        missing_r  = floors_missing_ratio_by_cell.get(h3_id, 1.0)
        comm_ratio = round(float(commercial_ratio_by_cell.get(h3_id, 0.0)), 4)

        # AVG_FLOORS (back-compat): use observed mean; if all buildings in
        # this cell lack `building:levels`, fall back to 1.0 as before — but
        # the new FLOORS_MISSING_RATIO=1.0 makes the absence explicit so
        # the agent can downweight this value.
        if avg_obs is None or _math_isnan(avg_obs):
            avg_floors_legacy = 1.0
            avg_floors_observed_val = None   # nothing observed
        else:
            avg_floors_legacy = round(float(avg_obs), 2)
            avg_floors_observed_val = avg_floors_legacy

        # BUILDING_COUNT is now a float because large polygons contribute
        # fractional area-weighted counts to multiple cells (methodology §1.2-B).
        # Round to 2 decimals so the dashboard displays cleanly; cells with
        # only small polygons get whole-number counts unchanged.
        signal_rows += [
            {"h3_id": h3_id, "signal": "BUILDING_COUNT",       "value": round(float(total), 2), "unit": "count"},
            {"h3_id": h3_id, "signal": "BUILDING_DENSITY",     "value": density,         "unit": "per_km2"},
            {"h3_id": h3_id, "signal": "AVG_FLOORS",           "value": avg_floors_legacy, "unit": "floors"},
            {"h3_id": h3_id, "signal": "COMMERCIAL_RATIO",     "value": comm_ratio,      "unit": "ratio"},
            # New transparency signals (methodology §D.13)
            {"h3_id": h3_id, "signal": "FLOORS_MISSING_RATIO", "value": round(float(missing_r if missing_r is not None else 1.0), 4),
             "unit": "ratio"},
            # Data confidence (static for OSM-derived structural signals)
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",      "value": _data_confidence(), "unit": "ratio"},
        ]
        # AVG_FLOORS_OBSERVED — only emitted when at least one building in
        # the cell carries the explicit tag. Skipping when None keeps the
        # signal nullable (the cell genuinely has no observed evidence).
        if avg_floors_observed_val is not None:
            signal_rows.append({
                "h3_id": h3_id, "signal": "AVG_FLOORS_OBSERVED",
                "value": avg_floors_observed_val, "unit": "floors",
            })

    written = write_signals(
        signal_rows,
        city_id=city_id, domain="buildings", source="osm",
        geometry_assignment_method="hybrid_polygon",
    )
    logger.info(
        "[%s/buildings] %d cells × 6 signals = %d rows written.",
        city_id, len(h3_ids), written,
    )

    # ── GHSL built-volume / built-surface signals (methodology §D.13) ─────
    # OSM tells us "buildings are here"; GHSL tells us "how much building
    # mass is here" — independent of OSM's tag-coverage gaps.
    ghsl_written = _ingest_ghsl_built_volume(city_id, bbox, h3_ids, area_km2)

    total = written + ghsl_written
    record_ingest(city_id=city_id, domain="buildings", rows_written=total)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# GHSL built-volume — independent of OSM, derived from 100 m satellite raster
# ─────────────────────────────────────────────────────────────────────────────

def _ingest_ghsl_built_volume(
    city_id: str,
    bbox: dict,
    h3_ids: list[str],
    area_km2: float,
) -> int:
    """Read GHSL BUILT_V + BUILT_S for the bbox, bin to H3, emit signals.

    Signals (domain="buildings", source="ghsl"):
        BUILT_VOLUME_M3       m³        Sum of GHSL built-volume pixels in cell
        BUILT_SURFACE_M2      m²        Sum of GHSL built-surface pixels in cell
        AVG_BUILDING_HEIGHT_M m         BUILT_VOLUME_M3 / BUILT_SURFACE_M2
        BUILT_INTENSITY       ratio     Built surface / cell area (built-up fraction)
        DATA_CONFIDENCE       ratio     0.85 for satellite-derived (real_station=0.95)

    Returns rows written.  Returns 0 (with WARN log) if GHSL is unreachable
    or the bbox falls outside our tile index — never raises, since this is
    a complementary signal source.
    """
    import h3 as _h3
    from airos.drivers.connectors.ghsl.raster import read_ghsl_samples
    from airos.drivers.store.writer import write_signals, upsert_metadata
    from airos.drivers.store.ingestor import DEFAULT_H3_RES

    bbox_t = (bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"])

    vol_samples = read_ghsl_samples("BUILT_V", bbox_t)
    sur_samples = read_ghsl_samples("BUILT_S", bbox_t)

    if not vol_samples and not sur_samples:
        logger.warning("[%s/buildings] GHSL returned no samples — skipping volume signals.", city_id)
        return 0

    vol_by_cell: dict[str, float] = {}
    sur_by_cell: dict[str, float] = {}
    for s in vol_samples:
        cell = _h3.latlng_to_cell(s["lat"], s["lon"], DEFAULT_H3_RES)
        vol_by_cell[cell] = vol_by_cell.get(cell, 0.0) + s["value"]
    for s in sur_samples:
        cell = _h3.latlng_to_cell(s["lat"], s["lon"], DEFAULT_H3_RES)
        sur_by_cell[cell] = sur_by_cell.get(cell, 0.0) + s["value"]

    cell_area_m2 = area_km2 * 1_000_000.0
    rows: list[dict] = []
    for h3_id in h3_ids:
        vol = vol_by_cell.get(h3_id, 0.0)
        sur = sur_by_cell.get(h3_id, 0.0)
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        avg_h = round(vol / sur, 2) if sur > 0 else 0.0
        intensity = round(sur / cell_area_m2, 4) if cell_area_m2 > 0 else 0.0
        rows += [
            {"h3_id": h3_id, "signal": "BUILT_VOLUME_M3",       "value": round(vol, 2),  "unit": "m3"},
            {"h3_id": h3_id, "signal": "BUILT_SURFACE_M2",      "value": round(sur, 2),  "unit": "m2"},
            {"h3_id": h3_id, "signal": "AVG_BUILDING_HEIGHT_M", "value": avg_h,          "unit": "metres"},
            {"h3_id": h3_id, "signal": "BUILT_INTENSITY",       "value": intensity,      "unit": "ratio"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",       "value": 0.85,           "unit": "ratio"},
        ]

    written = write_signals(
        rows,
        city_id=city_id, domain="buildings", source="ghsl",
        geometry_assignment_method="raster_pixel_sum",
    )
    logger.info(
        "[%s/buildings] GHSL: %d cells × 5 signals = %d rows written.",
        city_id, len(h3_ids), written,
    )
    return written
