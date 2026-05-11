"""Terrain domain ingestor — DEM elevation samples → per-H3-cell signals.

Signals written (domain="terrain"):
    ELEVATION_M       metres   Mean cell elevation above sea level (SRTM/Copernicus 30 m DEM).
    SLOPE_DEG         degrees  Mean slope steepness derived from H3 neighbourhood plane fit.
    ASPECT_DEG        degrees  Dominant slope direction (0=N, 90=E, 180=S, 270=W; -1=flat).
    RUGGEDNESS_INDEX  metres   Mean |elevation delta| vs k=1 H3 ring neighbours.
    DATA_CONFIDENCE   ratio    0.90 full coverage, 0.65 void-filled, 0.0 synthetic.

NOT written by this ingestor:
    TERRAIN_CLASS — agent-layer derived signal (H3 Expert Agent classifies after ingest).

Slope and aspect are computed from the H3 neighbourhood:
    For each cell, retrieve the mean elevation of its 6 k=1 ring neighbours, convert
    lat/lon offsets to metres, then fit a least-squares plane z = ax + by + c over
    the 7 points (centre + 6 neighbours). Slope = arctan(√(a²+b²)); aspect is the
    uphill-facing compass bearing derived from the gradient (a, b).

Refresh cadence: 90 days (terrain is effectively static).
Data confidence: 0.90 (full SRTM/Copernicus coverage); 0.65 (void-filled pixels present).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from airos.drivers.connectors.terrain.srtm import fetch_dem_samples  # noqa: E402 — kept here for mockability

logger = logging.getLogger(__name__)

# Threshold fraction of void/void_filled samples above which DATA_CONFIDENCE
# drops from 0.90 to 0.65 for a cell.
_VOID_FRACTION_THRESHOLD = 0.10   # > 10% void-filled → reduced confidence
_SYNTHETIC_SOURCE_ID     = "synthetic_fallback"


# ---------------------------------------------------------------------------
# Internal: grid-point → H3 cell assignment
# ---------------------------------------------------------------------------

def _assign_h3(
    samples: list[dict[str, Any]],
    resolution: int,
) -> dict[str, list[dict[str, Any]]]:
    """Group samples by H3 cell at the given resolution."""
    import h3 as _h3
    cell_map: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        lat, lon = s["lat"], s["lon"]
        cell = _h3.latlng_to_cell(lat, lon, resolution)
        cell_map.setdefault(cell, []).append(s)
    return cell_map


# ---------------------------------------------------------------------------
# Internal: per-cell signal computation
# ---------------------------------------------------------------------------

def _cell_elevation(samples: list[dict[str, Any]]) -> tuple[float | None, float]:
    """
    Compute mean elevation and DATA_CONFIDENCE for a single cell.

    Excludes suspected_artefact and null-elevation samples from the mean.
    Returns (elevation_m, confidence).
    """
    usable = [
        s["elevation_m"] for s in samples
        if s["quality_flag"] not in ("suspected_artefact",)
        and s["elevation_m"] is not None
    ]
    if not usable:
        return None, 0.0

    void_count = sum(
        1 for s in samples
        if s["quality_flag"] in ("void", "void_filled")
    )
    is_synthetic = any(
        _SYNTHETIC_SOURCE_ID in s.get("provenance", {}).get("source_id", "")
        for s in samples
    )

    if is_synthetic:
        confidence = 0.0
    elif void_count / len(samples) > _VOID_FRACTION_THRESHOLD:
        confidence = 0.65
    else:
        confidence = 0.90

    return float(np.mean(usable)), confidence


def _slope_aspect(
    centre_lat: float,
    centre_lon: float,
    centre_elev: float,
    neighbour_elevs: dict[str, float],   # h3_id → elevation_m
) -> tuple[float, float]:
    """
    Fit a least-squares plane through the centre cell and its H3 neighbours,
    then return (slope_deg, aspect_deg).

    Each point is expressed in (x, y, z) metres with the centre at origin.
    Returns (0.0, -1.0) if fewer than 3 neighbours have elevation data.
    """
    import h3 as _h3

    if len(neighbour_elevs) < 3:
        return 0.0, -1.0

    # Convert lat/lon to local x,y offsets in metres from centre
    cos_lat = math.cos(math.radians(centre_lat))
    pts: list[tuple[float, float, float]] = [(0.0, 0.0, centre_elev)]

    for n_id, n_elev in neighbour_elevs.items():
        n_lat, n_lon = _h3.cell_to_latlng(n_id)
        x = (n_lon - centre_lon) * 111320.0 * cos_lat   # east/west metres
        y = (n_lat - centre_lat) * 111320.0              # north/south metres
        pts.append((x, y, n_elev))

    # Least-squares plane z = ax + by + c  →  [a, b, c]
    A = np.array([[p[0], p[1], 1.0] for p in pts])
    z = np.array([p[2] for p in pts])
    try:
        coeffs, _, _, _ = np.linalg.lstsq(A, z, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0, -1.0

    a, b = float(coeffs[0]), float(coeffs[1])   # dz/dx, dz/dy

    # Slope: arctan of gradient magnitude (radians → degrees)
    gradient_magnitude = math.hypot(a, b)
    slope_deg = round(math.degrees(math.atan(gradient_magnitude)), 2)

    # Aspect: compass bearing of the uphill direction
    # atan2(dz/dx, dz/dy) gives bearing from north, clockwise
    # We want the uphill face: gradient points in direction (a, b)
    if gradient_magnitude < 1e-6:
        aspect_deg = -1.0   # flat
    else:
        # atan2(east_component, north_component) → bearing from north
        bearing = math.degrees(math.atan2(a, b)) % 360.0
        aspect_deg = round(bearing, 1)

    return slope_deg, aspect_deg


def _ruggedness(
    centre_elev: float,
    neighbour_elevs: dict[str, float],
) -> float:
    """
    Terrain Ruggedness Index — mean absolute elevation difference
    between the centre cell and its k=1 ring neighbours.
    """
    if not neighbour_elevs:
        return 0.0
    diffs = [abs(centre_elev - e) for e in neighbour_elevs.values()]
    return round(float(np.mean(diffs)), 2)


# ---------------------------------------------------------------------------
# Public: ingest_terrain
# ---------------------------------------------------------------------------

def ingest_terrain(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch DEM samples for the city bbox and write per-cell terrain signals.

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
    from airos.drivers.store.writer import write_signals, upsert_metadata, record_ingest
    from airos.drivers.store.geo_agg import cells_for_bbox
    import h3 as _h3

    try:
        _check_interval("terrain", city_id, force)
    except Exception as e:
        logger.info("[%s/terrain] %s", city_id, e)
        return 0

    logger.info("[%s/terrain] Fetching DEM samples …", city_id)
    samples = fetch_dem_samples(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
    )

    if not samples:
        logger.warning("[%s/terrain] No DEM samples returned.", city_id)
        record_ingest(city_id=city_id, domain="terrain", rows_written=0,
                      status="partial", error_msg="connector returned empty")
        return 0

    ok_count = sum(1 for s in samples if s["quality_flag"] == "ok")
    logger.info("[%s/terrain] %d samples fetched (%d ok). Aggregating to H3 …",
                city_id, len(samples), ok_count)

    # ── Step 1: assign each sample to an H3 cell ───────────────────────────
    cell_samples = _assign_h3(samples, DEFAULT_H3_RES)

    # Ensure every bbox cell is represented (even if no samples fell inside)
    all_cells = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )

    # ── Step 2: compute mean elevation per cell ─────────────────────────────
    cell_elevation: dict[str, float | None] = {}
    cell_confidence: dict[str, float]       = {}

    for h3_id in all_cells:
        cell_samps = cell_samples.get(h3_id, [])
        elev, conf = _cell_elevation(cell_samps) if cell_samps else (None, 0.0)
        cell_elevation[h3_id] = elev
        cell_confidence[h3_id] = conf

    # ── Step 3: compute slope, aspect, ruggedness via neighbourhood ─────────
    # Build neighbour elevation lookup (reuse already-computed means)
    signal_rows: list[dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for h3_id in all_cells:
        elev = cell_elevation[h3_id]
        conf = cell_confidence[h3_id]

        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        if elev is None:
            # No usable samples — write nulls so the cell appears in the store
            signal_rows += [
                {"h3_id": h3_id, "signal": "ELEVATION_M",       "value": None,   "unit": "metres"},
                {"h3_id": h3_id, "signal": "SLOPE_DEG",         "value": None,   "unit": "degrees"},
                {"h3_id": h3_id, "signal": "ASPECT_DEG",        "value": None,   "unit": "degrees"},
                {"h3_id": h3_id, "signal": "RUGGEDNESS_INDEX",  "value": None,   "unit": "metres"},
                {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",   "value": 0.0,    "unit": "ratio"},
            ]
            continue

        # Gather neighbour elevations for slope/aspect/ruggedness
        neighbour_ids = [n for n in _h3.grid_disk(h3_id, 1) if n != h3_id]
        neighbour_elevs: dict[str, float] = {
            n: cell_elevation[n]
            for n in neighbour_ids
            if cell_elevation.get(n) is not None
        }

        slope_deg, aspect_deg = _slope_aspect(
            *_h3.cell_to_latlng(h3_id),
            elev,
            neighbour_elevs,
        )
        rug = _ruggedness(elev, neighbour_elevs)

        signal_rows += [
            {"h3_id": h3_id, "signal": "ELEVATION_M",      "value": round(elev, 1), "unit": "metres"},
            {"h3_id": h3_id, "signal": "SLOPE_DEG",         "value": slope_deg,      "unit": "degrees"},
            {"h3_id": h3_id, "signal": "ASPECT_DEG",        "value": aspect_deg,     "unit": "degrees"},
            {"h3_id": h3_id, "signal": "RUGGEDNESS_INDEX",  "value": rug,            "unit": "metres"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",   "value": conf,           "unit": "ratio"},
        ]

    written = write_signals(signal_rows, city_id=city_id, domain="terrain", source="srtm_copernicus")
    logger.info(
        "[%s/terrain] %d cells × 5 signals = %d rows written.",
        city_id, len(all_cells), written,
    )
    record_ingest(city_id=city_id, domain="terrain", rows_written=written)
    return written
