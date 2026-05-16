"""Airshed-scale composition step — Phase 3 items 2+3.

Runs after city-level ingest. For each enabled AOI of kind=airshed
(or watershed / corridor), composes airshed-scale derived signals
from the underlying cell data that the per-city sweeps already wrote.

What it produces (per cell, stored back in h3_signals):

- `UPWIND_PM25_LOAD_REGIONAL` — sum of PM2.5 from cells up to ~200 km
  upwind, weighted by exp(-d/L) and a cosine cone. Distinct from
  UPWIND_PM25_LOAD_K10 (~7.5 km, metro-scale) because it operates
  over the full airshed bbox, not an H3 ring. This is what surfaces
  Punjab → Delhi advection during stubble-burning season.

Design notes
- The composition is *on top of* what the city sweeps already wrote.
  No re-ingest of source data. Cells are already in h3_signals; we
  read them spatially via the airshed bbox.
- Wind direction at each *target cell* (where we attribute the
  incoming load) is used to define "upwind" — different cells in
  the airshed can have different wind vectors and produce different
  receptor scores from the same source.
- Search radius scales with wind speed: more wind → faster travel →
  wider catchment, capped at 300 km.
- Vectorised with NumPy: per-target-cell cost is O(N) for N cells
  in the airshed; total is O(N²) but ~1 sec for 5,000 cells.
- Storage uses h3_signals exactly as before — no new schema. Each
  cell gets a single regional value per sweep, written under the
  airshed's id as `city_id` (preserves the existing dedup primary
  key while making the row distinguishable from per-city K2/K10).

Methodology §1.3 (AOIs as lenses) + §D.1 (wind-aware airborne).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from typing import Iterable

logger = logging.getLogger(__name__)

# Regional upwind parameters
_DEFAULT_TIME_HRS         = 12.0   # transport time scale (forward exp decay)
_MAX_RADIUS_KM            = 300.0  # cap on how far upwind we look
_MIN_RADIUS_KM            =  50.0  # floor — always look at least this far
_UPWIND_CONE_DEG          =  45.0  # ±45° angular tolerance for "upwind"


def _haversine_km_vec(lat1: float, lon1: float, lat2, lon2):
    """Vectorised great-circle distance — lat1/lon1 scalar, lat2/lon2 numpy."""
    import numpy as np
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _bearing_deg_vec(lat1: float, lon1: float, lat2, lon2):
    """Vectorised initial bearing from (lat1, lon1) toward each (lat2, lon2)."""
    import numpy as np
    p1 = math.radians(lat1)
    p2 = np.radians(lat2)
    dlon = np.radians(lon2 - lon1)
    x = np.sin(dlon) * np.cos(p2)
    y = math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dlon)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def _compute_regional_upwind(
    cells: list[dict],
) -> dict[str, float]:
    """Compute UPWIND_PM25_LOAD_REGIONAL for every cell in `cells`.

    Each entry must have keys: h3_id, lat, lon, pm25, wind_dir, wind_speed.
    Cells missing wind data are skipped (no regional attribution).
    """
    import numpy as np

    if not cells:
        return {}

    h3_ids   = np.array([c["h3_id"]     for c in cells])
    lats     = np.array([c["lat"]       for c in cells], dtype="float64")
    lons     = np.array([c["lon"]       for c in cells], dtype="float64")
    pm25s    = np.array([c["pm25"]      for c in cells], dtype="float64")
    wind_dir = [c.get("wind_dir")  for c in cells]
    wind_spd = [c.get("wind_speed") for c in cells]

    out: dict[str, float] = {}
    for i, cell in enumerate(cells):
        wd = wind_dir[i]
        ws = wind_spd[i]
        if wd is None:
            continue   # cannot define "upwind" without wind direction

        ws_eff = max(float(ws or 5.0), 1.0)
        L_km   = ws_eff * _DEFAULT_TIME_HRS
        radius = max(min(L_km * 2.0, _MAX_RADIUS_KM), _MIN_RADIUS_KM)

        # Distances + bearings from this target cell to every other cell.
        d = _haversine_km_vec(lats[i], lons[i], lats, lons)
        b = _bearing_deg_vec(lats[i], lons[i], lats, lons)

        # Angular difference from wind direction (where wind comes from = upwind).
        # Wrap to [-180, 180].
        ang = (b - float(wd) + 180.0) % 360.0 - 180.0
        ang = np.abs(ang)

        mask = (d > 0) & (d <= radius) & (ang <= _UPWIND_CONE_DEG) & np.isfinite(pm25s)
        if not mask.any():
            out[h3_ids[i]] = 0.0
            continue

        decay  = np.exp(-d[mask] / L_km)
        cos_w  = np.cos(np.radians(ang[mask]))
        weight = decay * cos_w
        load   = float((pm25s[mask] * weight).sum())
        out[h3_ids[i]] = round(load, 3)

    return out


def _airshed_cells_with_signals(
    aoi_id: str, db_path: str,
) -> list[dict]:
    """Pull every cell inside the AOI bbox with the inputs we need:
    PM2.5, wind direction, wind speed, plus centroid coords."""
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)

    from airos.drivers.store.schema import ro_connect
    conn = ro_connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, s2.signal, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('PM25', 'WIND_DIR_DEG', 'WIND_SPEED_KMH')
                  AND s2.value IS NOT NULL
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"],
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    by_cell: dict[str, dict] = {}
    for r in rows:
        cell = by_cell.setdefault(r["h3_id"], {
            "h3_id": r["h3_id"],
            "lat":   r["centroid_lat"],
            "lon":   r["centroid_lon"],
            "pm25":  float("nan"),
            "wind_dir":   None,
            "wind_speed": None,
        })
        if r["signal"] == "PM25":
            cell["pm25"] = float(r["value"])
        elif r["signal"] == "WIND_DIR_DEG":
            cell["wind_dir"] = float(r["value"])
        elif r["signal"] == "WIND_SPEED_KMH":
            cell["wind_speed"] = float(r["value"])

    # Need at minimum the centroid + PM25 OR wind; cells with neither are noise.
    return [c for c in by_cell.values()
            if math.isfinite(c["pm25"]) or c["wind_dir"] is not None]


def run_airshed_composition(*, db_path: str | None = None) -> dict[str, int]:
    """Compute airshed-scale derived signals for every enabled AOI of
    kind in {airshed, watershed, corridor}. Returns {aoi_id: rows_written}."""
    if db_path is None:
        from airos.drivers.store.schema import DB_PATH
        db_path = str(DB_PATH)

    from airos.os.aoi_registry import list_aois, get_aoi
    from airos.drivers.store.writer import write_signals

    summary: dict[str, int] = {}
    for aoi_id in list_aois():
        cfg = get_aoi(aoi_id)
        if cfg["kind"] not in ("airshed", "watershed", "corridor"):
            continue

        cells = _airshed_cells_with_signals(aoi_id, db_path)
        if not cells:
            logger.info("[airshed/%s] no input cells — skipping composition", aoi_id)
            summary[aoi_id] = 0
            continue

        # Only cells that have BOTH PM2.5 and wind direction can serve as
        # *targets* (we attribute regional load to them). Cells with PM2.5
        # but no wind dir still contribute to other cells' loads as sources.
        load_by_cell = _compute_regional_upwind(cells)

        rows = [{
            "h3_id":  h3_id,
            "signal": "UPWIND_PM25_LOAD_REGIONAL",
            "value":  load,
            "unit":   "µg/m³-equiv",
        } for h3_id, load in load_by_cell.items()]
        if not rows:
            summary[aoi_id] = 0
            continue

        # Write back to h3_signals with city_id = the AOI id so the row is
        # distinguishable from per-city K2/K10 rows. Skips the conformance
        # gate because this is a derived/composite signal not declared
        # in any driver's signal_names.
        written = write_signals(
            rows,
            city_id=aoi_id, domain="air", source="airshed_composite",
            geometry_assignment_method="airshed_bearing_aggregate",
            skip_conformance=True,
        )
        summary[aoi_id] = written
        logger.info(
            "[airshed/%s] composition: %d cells × UPWIND_PM25_LOAD_REGIONAL",
            aoi_id, written,
        )
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Summary statistics for the dashboard (Item 2 — composition / member_aois).
# Cheap to compute on-demand; not persisted today. Surfaced in the airshed
# panel header.
# ──────────────────────────────────────────────────────────────────────────────

def airshed_summary_stats(
    aoi_id: str, *, db_path: str | None = None,
) -> dict[str, float | int | None]:
    """Lightweight airshed-level aggregate stats for the dashboard.

    Returns: {
        "avg_pm25", "max_pm25", "p95_pm25",         # air quality
        "fire_count_24h", "frp_total_24h",          # active fires
        "cell_count_assessed",                       # coverage
        "high_risk_cells_pct",                       # what fraction is hot
        "population_exposed_high",                   # exposure
    }
    None values indicate missing inputs (no PM2.5 yet, no assessments yet, ...).
    """
    if db_path is None:
        from airos.drivers.store.schema import DB_PATH
        db_path = str(DB_PATH)

    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    p = (bbox["lat_min"], bbox["lat_max"], bbox["lon_min"], bbox["lon_max"])

    from airos.drivers.store.schema import ro_connect
    conn = ro_connect(db_path)
    try:
        pm = conn.execute(
            """
            SELECT s.value AS pm
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2 INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal = 'PM25' AND s2.value IS NOT NULL
                  AND s2.hour_bucket >= datetime('now', '-6 hours')
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id
            ) latest ON latest.h3_id = s.h3_id AND latest.hb = s.hour_bucket
            WHERE s.signal = 'PM25' AND s.value IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (*p, *p),
        ).fetchall()
        pm_values = [r["pm"] for r in pm if r["pm"] is not None]

        # Fires in last 24h
        fire_row = conn.execute(
            """
            SELECT COUNT(DISTINCT s.h3_id) AS n,
                   COALESCE(SUM(s.value), 0) AS frp_total
            FROM h3_signals s INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            WHERE s.signal = 'FRP' AND s.value > 0
              AND s.hour_bucket >= datetime('now', '-24 hours')
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            p,
        ).fetchone()

        # Assessment coverage and high-risk pct — collapse per-cell across
        # all domains: a cell is "high-risk" if ANY domain assesses it
        # high/severe. (Without this collapse, every domain counts the
        # cell separately and inflates the percentages 5-10×.)
        assess_rows = conn.execute(
            """
            SELECT a.h3_id, MAX(
                CASE a.risk_level
                    WHEN 'severe'   THEN 4
                    WHEN 'high'     THEN 3
                    WHEN 'moderate' THEN 2
                    WHEN 'low'      THEN 1
                    ELSE 0
                END
            ) AS max_rank
            FROM h3_assessments a
            INNER JOIN h3_metadata m ON m.h3_id = a.h3_id
            INNER JOIN (
                SELECT a2.h3_id, a2.domain, MAX(a2.day_bucket) AS db
                FROM h3_assessments a2
                INNER JOIN h3_metadata m2 ON m2.h3_id = a2.h3_id
                WHERE m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY a2.h3_id, a2.domain
            ) latest ON latest.h3_id = a.h3_id
                    AND latest.domain = a.domain
                    AND latest.db = a.day_bucket
            WHERE a.risk_level IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            GROUP BY a.h3_id
            """,
            (*p, *p),
        ).fetchall()

        # Population exposed to high or severe risk — count each cell once,
        # not once per high-risk domain.
        pop_high_row = conn.execute(
            """
            SELECT COALESCE(SUM(p.value), 0) AS pop
            FROM h3_signals p
            INNER JOIN h3_metadata m ON m.h3_id = p.h3_id
            INNER JOIN (
                SELECT DISTINCT a.h3_id
                FROM h3_assessments a
                INNER JOIN h3_metadata m2 ON m2.h3_id = a.h3_id
                WHERE a.risk_level IN ('high', 'severe')
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
            ) hot ON hot.h3_id = p.h3_id
            WHERE p.signal = 'POPULATION'
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (*p, *p),
        ).fetchone()
    finally:
        conn.close()

    def _percentile(values: list[float], q: float) -> float | None:
        if not values:
            return None
        s = sorted(values)
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * q
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)

    n_cells   = len(assess_rows)
    n_high    = sum(1 for r in assess_rows if (r["max_rank"] or 0) >= 3)

    return {
        "avg_pm25":            round(sum(pm_values) / len(pm_values), 1) if pm_values else None,
        "max_pm25":            round(max(pm_values), 1) if pm_values else None,
        "p95_pm25":            round(_percentile(pm_values, 0.95), 1) if pm_values else None,
        "fire_count_24h":      int(fire_row["n"] or 0) if fire_row else 0,
        "frp_total_24h":       round(float(fire_row["frp_total"] or 0), 1) if fire_row else 0,
        "cell_count_assessed": n_cells,
        "high_risk_cells_pct": round(100.0 * n_high / n_cells, 1) if n_cells else None,
        "population_exposed_high": int(pop_high_row["pop"] or 0) if pop_high_row else 0,
    }
