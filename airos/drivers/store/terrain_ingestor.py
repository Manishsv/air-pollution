"""Terrain domain ingestor — DEM elevation samples → per-H3-cell signals.

Signals written (domain="terrain"):
    ELEVATION_M       metres   Mean cell elevation above sea level (SRTM/Copernicus 30 m DEM).
    SLOPE_DEG         degrees  Mean slope steepness derived from H3 neighbourhood plane fit.
    ASPECT_DEG        degrees  Dominant slope direction (0=N, 90=E, 180=S, 270=W; -1=flat).
    RUGGEDNESS_INDEX  metres   Mean |elevation delta| vs k=1 H3 ring neighbours.
    DATA_CONFIDENCE   ratio    0.90 full coverage, 0.65 void-filled, 0.0 synthetic.
    TERRAIN_CLASS     ordinal  Rule-based morphological class written after DEM ingest.
                               Stored as integer ordinal (0–4); decode with TERRAIN_CLASS_LABELS.
                               0=valley  1=plain  2=hill  3=ridge  4=escarpment

Classification uses city-relative elevation percentiles + slope thresholds:
    escarpment  slope > 20°
    ridge       slope > 10°  AND  elevation in top 50% of city cells
    hill        elevation in top 35% of city cells  AND  slope > 2°
    valley      elevation in bottom 25% of city cells  AND  slope < 5°
    plain       everything else (default)

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
# TERRAIN_CLASS ordinal encoding
# ---------------------------------------------------------------------------
# h3_signals.value is REAL — store class as integer ordinal; decode in the panel.
TERRAIN_CLASS_LABELS: dict[int, str] = {
    0: "valley",
    1: "plain",
    2: "hill",
    3: "ridge",
    4: "escarpment",
}
TERRAIN_CLASS_ORDINAL: dict[str, int] = {v: k for k, v in TERRAIN_CLASS_LABELS.items()}


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
# Hex-D6 flow routing (methodology §D.17)
# ---------------------------------------------------------------------------
# Each cell drains to its steepest-downhill H3 neighbour. The downstream graph
# is acyclic by construction (strict less-than on elevation), so flow
# accumulation can be computed via Kahn's topological sort: source cells (no
# incoming flow) push their accumulation down to their downstream cell,
# decrementing the downstream cell's in-degree until it itself is ready.

def _compute_flow_graph(
    cell_elevation: dict[str, float | None],
    all_cells: list[str],
) -> tuple[dict[str, float], dict[str, int]]:
    """Return (flow_direction_deg, flow_accumulation) for every cell.

    flow_direction_deg : bearing in degrees (0=N, 90=E) from this cell's
        centroid to its downstream neighbour's centroid. Set to **-1** when
        the cell is a **sink** (no neighbour is lower) — the flow graph
        terminates there. Cells without elevation also get -1.

    flow_accumulation : count of cells whose runoff transitively reaches this
        cell, **including itself**. A truly isolated cell has 1; a major
        basin outlet aggregates the count of its entire upstream basin.
    """
    import math
    import h3 as _h3

    # 1. Build the downstream map by finding the steepest-downhill neighbour
    #    among each cell's 6 H3 neighbours.
    downstream: dict[str, str | None] = {}
    for cell in all_cells:
        elev = cell_elevation.get(cell)
        if elev is None:
            downstream[cell] = None
            continue
        neighbours = [n for n in _h3.grid_disk(cell, 1) if n != cell]
        best: str | None = None
        best_elev = elev   # strict less-than: only flow if neighbour is LOWER
        for n in neighbours:
            n_elev = cell_elevation.get(n)
            if n_elev is None:
                continue
            if n_elev < best_elev:
                best_elev = n_elev
                best = n
        downstream[cell] = best   # None = sink

    # 2. Topological-sort flow accumulation using Kahn's algorithm.
    upstream_of: dict[str, list[str]] = {c: [] for c in all_cells}
    for c, ds in downstream.items():
        if ds is not None and ds in upstream_of:
            upstream_of[ds].append(c)
    indegree: dict[str, int] = {c: len(upstream_of[c]) for c in all_cells}
    accumulation: dict[str, int] = {c: 1 for c in all_cells}
    queue = [c for c in all_cells if indegree[c] == 0]
    while queue:
        c = queue.pop()
        ds = downstream.get(c)
        if ds is None or ds not in accumulation:
            continue
        accumulation[ds] += accumulation[c]
        indegree[ds] -= 1
        if indegree[ds] == 0:
            queue.append(ds)

    # 3. Compute bearing from each cell to its downstream cell.
    flow_dir_deg: dict[str, float] = {}
    for c, ds in downstream.items():
        if ds is None:
            flow_dir_deg[c] = -1.0
            continue
        lat1, lon1 = _h3.cell_to_latlng(c)
        lat2, lon2 = _h3.cell_to_latlng(ds)
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dlam = math.radians(lon2 - lon1)
        y = math.sin(dlam) * math.cos(phi2)
        x = (math.cos(phi1) * math.sin(phi2)
             - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
        bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
        flow_dir_deg[c] = round(bearing, 1)

    return flow_dir_deg, accumulation


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

    # ── Step 3: compute flow direction + flow accumulation (§D.17) ────────
    # For each cell with elevation, find its steepest-downhill H3 neighbour
    # and compute the size of its upstream basin via topological traversal.
    flow_dir_deg, flow_accumulation = _compute_flow_graph(cell_elevation, all_cells)

    # ── Step 4: compute slope, aspect, ruggedness via neighbourhood ─────────
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

        # Flow routing values for this cell (may be None for cells with no
        # elevation; we only reach this branch when elev is not None, but
        # flow_dir_deg uses -1 for sinks).
        fdir = flow_dir_deg.get(h3_id, -1.0)
        facc = flow_accumulation.get(h3_id, 1)

        signal_rows += [
            {"h3_id": h3_id, "signal": "ELEVATION_M",       "value": round(elev, 1),    "unit": "metres"},
            {"h3_id": h3_id, "signal": "SLOPE_DEG",         "value": slope_deg,         "unit": "degrees"},
            {"h3_id": h3_id, "signal": "ASPECT_DEG",        "value": aspect_deg,        "unit": "degrees"},
            {"h3_id": h3_id, "signal": "RUGGEDNESS_INDEX",  "value": rug,               "unit": "metres"},
            # Hex-D6 flow routing (methodology §D.17). -1 = sink (no downstream neighbour).
            {"h3_id": h3_id, "signal": "FLOW_DIRECTION",    "value": float(fdir),       "unit": "degrees"},
            {"h3_id": h3_id, "signal": "FLOW_ACCUMULATION", "value": float(facc),       "unit": "count"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",   "value": conf,              "unit": "ratio"},
        ]

    written = write_signals(
        signal_rows, city_id=city_id, domain="terrain", source="srtm_copernicus",
        geometry_assignment_method="raster",
    )
    logger.info(
        "[%s/terrain] %d cells × 7 signals = %d rows written (incl. FLOW_DIRECTION + FLOW_ACCUMULATION).",
        city_id, len(all_cells), written,
    )

    # Classify immediately after ingest while the data is fresh.
    classified = classify_terrain(city_id)
    logger.info("[%s/terrain] %d TERRAIN_CLASS rows written.", city_id, classified)

    record_ingest(city_id=city_id, domain="terrain", rows_written=written + classified)
    return written + classified


# ---------------------------------------------------------------------------
# Rule-based terrain classifier
# ---------------------------------------------------------------------------

def classify_terrain(city_id: str) -> int:
    """Classify H3 cells for *city_id* and write TERRAIN_CLASS to h3_signals.

    Uses city-relative elevation percentiles so the thresholds adapt to each
    city's topographic range (Bangalore plateau vs. Delhi plain vs. Mumbai coast).

    TERRAIN_CLASS is stored as an integer ordinal — decode with TERRAIN_CLASS_LABELS:
        0 valley · 1 plain · 2 hill · 3 ridge · 4 escarpment

    Returns the number of TERRAIN_CLASS rows written (one per classified cell).
    """
    from airos.drivers.store.store import H3KnowledgeStore
    from airos.drivers.store.writer import write_signals

    store = H3KnowledgeStore.get()

    # ── 1. Load ELEVATION_M, SLOPE_DEG, DATA_CONFIDENCE for the city ──────
    df = store.fetchdf(
        """
        SELECT h3_id, signal, value
        FROM   h3_signals
        WHERE  city_id = ?
          AND  domain  = 'terrain'
          AND  signal  IN ('ELEVATION_M', 'SLOPE_DEG', 'DATA_CONFIDENCE')
          AND  value   IS NOT NULL
        """,
        [city_id],
    )
    if df is None or df.empty:
        logger.warning("[%s/terrain] classify_terrain: no signals found — skipping.", city_id)
        return 0

    # ── 2. Pivot to wide (one row per cell) ───────────────────────────────
    wide = (
        df.pivot_table(index="h3_id", columns="signal", values="value", aggfunc="last")
        .reset_index()
    )
    if "ELEVATION_M" not in wide.columns or "SLOPE_DEG" not in wide.columns:
        logger.warning("[%s/terrain] classify_terrain: missing required signals.", city_id)
        return 0

    wide = wide.dropna(subset=["ELEVATION_M"])
    if wide.empty:
        return 0

    # ── 3. Compute city-wide elevation percentile thresholds ─────────────
    elev = wide["ELEVATION_M"].values
    p25  = float(np.percentile(elev, 25))   # bottom quarter → valley candidates
    p65  = float(np.percentile(elev, 65))   # upper third → hill candidates
    p50  = float(np.percentile(elev, 50))   # median → ridge elevation gate

    logger.info(
        "[%s/terrain] elevation percentiles — p25=%.0fm  p50=%.0fm  p65=%.0fm",
        city_id, p25, p50, p65,
    )

    # ── 4. Classify each cell ─────────────────────────────────────────────
    def _classify(row) -> int:
        slope = float(row.get("SLOPE_DEG") or 0.0)
        e     = float(row["ELEVATION_M"])
        if slope > 20.0:
            return TERRAIN_CLASS_ORDINAL["escarpment"]
        if slope > 10.0 and e > p50:
            return TERRAIN_CLASS_ORDINAL["ridge"]
        if e > p65 and slope > 2.0:
            return TERRAIN_CLASS_ORDINAL["hill"]
        if e < p25 and slope < 5.0:
            return TERRAIN_CLASS_ORDINAL["valley"]
        return TERRAIN_CLASS_ORDINAL["plain"]

    wide["tc"] = wide.apply(_classify, axis=1)

    # ── 5. Build signal rows and write ────────────────────────────────────
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signal_rows = [
        {
            "h3_id":  row["h3_id"],
            "signal": "TERRAIN_CLASS",
            "value":  float(row["tc"]),
            "unit":   TERRAIN_CLASS_LABELS[int(row["tc"])],   # human label in unit field
        }
        for _, row in wide.iterrows()
    ]

    # skip_conformance=True: the classifier writes only TERRAIN_CLASS as a
    # targeted update — the other 5 signals are already in the store from
    # the DEM ingest. Running the full conformance gate on a single-signal
    # batch would always fail the "all declared signals present" check.
    written = write_signals(
        signal_rows, city_id=city_id, domain="terrain",
        source="terrain_classifier", skip_conformance=True,
    )

    counts = wide["tc"].value_counts().to_dict()
    summary = "  ".join(
        f"{TERRAIN_CLASS_LABELS[int(k)]}={v}"
        for k, v in sorted(counts.items())
    )
    logger.info("[%s/terrain] classified %d cells: %s", city_id, len(wide), summary)
    return written
