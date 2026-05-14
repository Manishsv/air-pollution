"""Census domain ingestor — GHSL_POP residential population → per-H3-cell signals.

Source: GHS_POP_E2020_GLOBE_R2023A_54009_100 (Joint Research Centre, CC-BY 4.0).
The product gives the count of residential population per 100 m × 100 m pixel.

Signals written (domain="census", source="ghsl_pop"):
    POPULATION                people   Sum of GHSL_POP pixels with centroid in the cell
    POPULATION_DENSITY_PER_KM2 per_km2  POPULATION / cell_area_km2
    VULNERABLE_POPULATION_EST people    POPULATION × 0.18 (rough under-5 + over-65 fraction
                                       from NFHS-5; replace with a real age-stratified
                                       layer when a 2021 census equivalent ships)
    DATA_CONFIDENCE           ratio    0.80 (modelled at 100 m, reference year 2020)

Why GHSL_POP and not WorldPop:
    WorldPop's HTTPS endpoint does not honour HTTP range requests, so windowed
    /vsicurl reads fail.  GHSL is served from the same JRC tile store as the
    BUILT_V / BUILT_S products we already use, which DOES honour ranges — so
    we get both products for free.  See methodology §D.21 for the trace.

Refresh cadence: yearly (population baseline is slow-moving; the next GHSL
update is the 2025 epoch release).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Rough vulnerable-population fraction (under-5 + over-65 in urban India).
# NFHS-5 (2019-21) gives ~11.5% under-5 and ~6.5% over-65 for urban India.
# This is a placeholder; once a real age-stratified raster ships, replace
# this multiplier with per-cell strata. The signal name carries the `_EST`
# suffix so the dashboard / agents know it is a coarse estimate.
_VULN_FRACTION = 0.18


def ingest_census(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch GHSL_POP for the city bbox and write per-cell census signals."""
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import (
        write_signals, upsert_metadata, record_ingest,
    )
    from airos.drivers.store.geo_agg import cells_for_bbox, cell_area_km2
    from airos.drivers.connectors.ghsl.raster import read_ghsl_samples
    import h3 as _h3

    try:
        _check_interval("census", city_id, force)
    except Exception as e:
        logger.info("[%s/census] %s", city_id, e)
        return 0

    bbox_t = (bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"])
    logger.info("[%s/census] Reading GHSL_POP for bbox …", city_id)
    pop_samples = read_ghsl_samples("POP", bbox_t)

    if not pop_samples:
        logger.warning("[%s/census] GHSL_POP returned no samples.", city_id)
        record_ingest(city_id=city_id, domain="census", rows_written=0,
                      status="partial", error_msg="ghsl_pop empty")
        return 0

    h3_ids = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )
    area_km2 = cell_area_km2(DEFAULT_H3_RES)

    pop_by_cell: dict[str, float] = {}
    for s in pop_samples:
        cell = _h3.latlng_to_cell(s["lat"], s["lon"], DEFAULT_H3_RES)
        pop_by_cell[cell] = pop_by_cell.get(cell, 0.0) + s["value"]

    rows: list[dict] = []
    for h3_id in h3_ids:
        pop = pop_by_cell.get(h3_id, 0.0)
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        density = round(pop / area_km2, 2) if area_km2 > 0 else 0.0
        vuln = round(pop * _VULN_FRACTION, 2)
        rows += [
            {"h3_id": h3_id, "signal": "POPULATION",                "value": round(pop, 2),  "unit": "people"},
            {"h3_id": h3_id, "signal": "POPULATION_DENSITY_PER_KM2","value": density,        "unit": "per_km2"},
            {"h3_id": h3_id, "signal": "VULNERABLE_POPULATION_EST", "value": vuln,           "unit": "people"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",           "value": 0.80,           "unit": "ratio"},
        ]

    written = write_signals(
        rows,
        city_id=city_id, domain="census", source="ghsl_pop",
        geometry_assignment_method="raster_pixel_sum",
    )
    logger.info(
        "[%s/census] %d cells × 4 signals = %d rows written (total pop ≈ %.0f).",
        city_id, len(h3_ids), written, sum(pop_by_cell.values()),
    )
    record_ingest(city_id=city_id, domain="census", rows_written=written)
    return written
