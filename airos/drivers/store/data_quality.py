"""Data quality and sensor siting utilities for the H3 Knowledge Store.

Public API
----------
get_cell_confidence(city_id, domain=None) -> pd.DataFrame
    Per-cell DATA_CONFIDENCE signal, optionally filtered by domain.

get_ward_data_quality(city_id) -> pd.DataFrame
    Ward-level (H3 res-7 parent) summary: fraction of cells that are "ready"
    (DATA_CONFIDENCE >= 0.6).

get_coverage_gaps(city_id, confidence_threshold=0.6) -> pd.DataFrame
    Cluster low-confidence cells into gap records, each with a centroid,
    estimated impact radius, and recommended sensor type.

populate_siting_candidates(city_id) -> int
    Run get_coverage_gaps and upsert results to h3_siting_candidates.

get_city_quality_summary(city_id) -> dict
    Aggregated quality stats for the whole city.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds and constants
# ---------------------------------------------------------------------------

CONFIDENCE_READY_THRESHOLD = 0.6   # cells at or above this are "data-ready"
IDW_5KM_RADIUS_CELLS = 12          # approximate number of H3-res-8 cells inside 5 km

# Sensor type recommendations per domain (or combination of domains)
_SENSOR_TYPE: dict[str, str] = {
    "air":          "Low-cost PM2.5/PM10 sensor (e.g. PurpleAir, SPS30)",
    "flood":        "Rain gauge + ultrasonic drain level sensor",
    "heat":         "Compact weather station (temp, humidity, solar)",
    "noise":        "Class-2 noise logger (outdoor rated)",
    "multi":        "Multi-parameter environmental station",
    "default":      "Environmental monitoring node",
}


def _store():
    """Lazy import to avoid circular dependency at module load time."""
    from airos.drivers.store.store import H3KnowledgeStore
    return H3KnowledgeStore.get()


def _recommended_sensor(domains: list[str]) -> str:
    """Map a list of affected domains to a recommended sensor type string."""
    unique = [d.lower() for d in domains if d]
    if len(unique) > 1:
        return _SENSOR_TYPE["multi"]
    if unique:
        return _SENSOR_TYPE.get(unique[0], _SENSOR_TYPE["default"])
    return _SENSOR_TYPE["default"]


# ---------------------------------------------------------------------------
# 1. Per-cell confidence
# ---------------------------------------------------------------------------

def get_cell_confidence(
    city_id: str,
    domain: Optional[str] = None,
) -> pd.DataFrame:
    """Return per-cell DATA_CONFIDENCE from the latest ingested hour bucket.

    Parameters
    ----------
    city_id : str
        City identifier (e.g. "bangalore").
    domain : str or None
        If given, restrict to a single domain; otherwise return all domains.

    Returns
    -------
    pd.DataFrame with columns:
        h3_id, domain, avg_confidence, latest_hour_bucket
    """
    s = _store()

    domain_filter = "AND domain = ?" if domain else ""
    params: list = [city_id]
    if domain:
        params.append(domain)

    sql = f"""
        SELECT
            h3_id,
            domain,
            AVG(value)      AS avg_confidence,
            MAX(hour_bucket) AS latest_hour_bucket
        FROM h3_signals
        WHERE city_id = ?
          AND signal  = 'DATA_CONFIDENCE'
          {domain_filter}
        GROUP BY h3_id, domain
        ORDER BY domain, h3_id
    """
    df = s.fetchdf(sql, params)
    return df if not df.empty else pd.DataFrame(
        columns=["h3_id", "domain", "avg_confidence", "latest_hour_bucket"]
    )


# ---------------------------------------------------------------------------
# 2. Ward-level quality summary
# ---------------------------------------------------------------------------

def get_ward_data_quality(city_id: str) -> pd.DataFrame:
    """Summarise data readiness by ward (approximated as H3 resolution-7 parent).

    Uses h3.cell_to_parent(h3_id, 7) to assign res-8 cells to their res-7 parent
    (roughly ward-scale, ~5.2 km²).  Returns the fraction of cells with
    DATA_CONFIDENCE >= CONFIDENCE_READY_THRESHOLD for each (ward, domain) pair.

    Returns
    -------
    pd.DataFrame with columns:
        ward_id, ward_name, domain, pct_cells_ready, total_cells, ready_cells
    """
    try:
        import h3
    except ImportError:
        logger.warning("h3 library not available — get_ward_data_quality returning empty")
        return pd.DataFrame(
            columns=["ward_id", "ward_name", "domain",
                     "pct_cells_ready", "total_cells", "ready_cells"]
        )

    conf_df = get_cell_confidence(city_id)
    if conf_df.empty:
        return pd.DataFrame(
            columns=["ward_id", "ward_name", "domain",
                     "pct_cells_ready", "total_cells", "ready_cells"]
        )

    # Assign each cell to its res-7 parent (ward proxy)
    def _parent(h3_id: str) -> str:
        try:
            return h3.cell_to_parent(h3_id, 7)
        except Exception:
            return "unknown"

    conf_df = conf_df.copy()
    conf_df["ward_id"]  = conf_df["h3_id"].apply(_parent)
    conf_df["is_ready"] = conf_df["avg_confidence"] >= CONFIDENCE_READY_THRESHOLD

    agg = (
        conf_df
        .groupby(["ward_id", "domain"])
        .agg(
            total_cells=("h3_id", "count"),
            ready_cells=("is_ready", "sum"),
        )
        .reset_index()
    )
    agg["pct_cells_ready"] = (agg["ready_cells"] / agg["total_cells"]).round(4)
    # Use ward_id as ward_name (real ward names require a polygon registry)
    agg["ward_name"] = agg["ward_id"]

    cols = ["ward_id", "ward_name", "domain", "pct_cells_ready", "total_cells", "ready_cells"]
    return agg[cols].sort_values(["domain", "pct_cells_ready"])


# ---------------------------------------------------------------------------
# 3. Coverage gap detection
# ---------------------------------------------------------------------------

def get_coverage_gaps(
    city_id: str,
    confidence_threshold: float = CONFIDENCE_READY_THRESHOLD,
) -> pd.DataFrame:
    """Identify clusters of low-confidence cells and return gap records.

    Algorithm
    ---------
    1. Fetch cells whose latest DATA_CONFIDENCE < confidence_threshold.
    2. Group nearby cells into clusters: start from an unvisited low-confidence
       cell, flood-fill using h3.grid_disk(h3_id, 1) — cells within one ring
       (~0.86 km edge-to-edge at res 8) are considered adjacent.
    3. For each cluster compute:
       - centroid: mean lat/lng of member cell centres
       - estimated_impact_cells: cells within a ~5 km IDW benefit radius
       - recommended_sensor_type: based on which domains are affected
    4. Return one row per cluster per domain.

    Returns
    -------
    pd.DataFrame with columns:
        gap_id, city_id, domain, centroid_lat, centroid_lng,
        affected_cells, affected_domains, estimated_impact_cells,
        recommended_sensor_type
    """
    try:
        import h3
    except ImportError:
        logger.warning("h3 library not available — get_coverage_gaps returning empty")
        return pd.DataFrame(columns=[
            "gap_id", "city_id", "domain", "centroid_lat", "centroid_lng",
            "centroid_cell", "affected_cells", "affected_domains",
            "estimated_impact_cells", "recommended_sensor_type",
        ])

    s = _store()

    # ── Step 1: fetch low-confidence cells from the most-recent bucket ────────
    sql = """
        SELECT
            h3_id,
            domain,
            value AS confidence
        FROM h3_signals
        WHERE city_id = ?
          AND signal  = 'DATA_CONFIDENCE'
          AND value   < ?
          AND hour_bucket = (
              SELECT MAX(hour_bucket)
              FROM   h3_signals s2
              WHERE  s2.city_id = h3_signals.city_id
                AND  s2.domain  = h3_signals.domain
                AND  s2.signal  = 'DATA_CONFIDENCE'
          )
        ORDER BY domain, h3_id
    """
    gap_df = s.fetchdf(sql, [city_id, confidence_threshold])

    if gap_df.empty:
        return pd.DataFrame(columns=[
            "gap_id", "city_id", "domain", "centroid_lat", "centroid_lng",
            "centroid_cell", "affected_cells", "affected_domains",
            "estimated_impact_cells", "recommended_sensor_type",
        ])

    # ── Step 2: cluster per domain via grid_disk flood-fill ──────────────────
    def _cluster_cells(cell_set: set[str]) -> list[list[str]]:
        """BFS / flood-fill: group cells that are within ring-1 of each other."""
        remaining = set(cell_set)
        clusters: list[list[str]] = []
        while remaining:
            seed = next(iter(remaining))
            cluster: list[str] = []
            frontier = {seed}
            while frontier:
                current = frontier.pop()
                if current not in remaining:
                    continue
                remaining.discard(current)
                cluster.append(current)
                # Expand: cells within ring-1 that are also low-confidence
                try:
                    neighbours = set(h3.grid_disk(current, 1)) - {current}
                except Exception:
                    neighbours = set()
                frontier |= neighbours & remaining
            clusters.append(cluster)
        return clusters

    # ── Step 3: build gap records ─────────────────────────────────────────────
    records: list[dict] = []
    gap_counter = 0

    for domain, domain_df in gap_df.groupby("domain"):
        cell_set: set[str] = set(domain_df["h3_id"].tolist())
        clusters = _cluster_cells(cell_set)

        for cluster in clusters:
            gap_counter += 1
            gap_id = f"{city_id}_{domain}_{gap_counter:04d}"

            # Centroid: mean lat/lng of cell centres
            lats, lngs = [], []
            for cid in cluster:
                try:
                    lat, lng = h3.cell_to_latlng(cid)
                    lats.append(lat)
                    lngs.append(lng)
                except Exception:
                    pass

            centroid_lat = float(sum(lats) / len(lats)) if lats else 0.0
            centroid_lng = float(sum(lngs) / len(lngs)) if lngs else 0.0

            # Estimated impact: cells within ~5 km IDW radius benefit from a new sensor
            # h3.grid_disk(centroid_approx, k) where k ~ 5 km / 0.86 km ≈ 6 rings
            estimated_impact = IDW_5KM_RADIUS_CELLS
            if lats:
                try:
                    # Use the cluster's own cells as proxy — all cells in the cluster
                    # plus their ~5 km neighbourhood represent the benefit footprint
                    centroid_cell = h3.latlng_to_cell(centroid_lat, centroid_lng, 8)
                    benefit_disk  = h3.grid_disk(centroid_cell, 6)   # ~5 km radius
                    estimated_impact = len(benefit_disk)
                except Exception:
                    estimated_impact = IDW_5KM_RADIUS_CELLS

            records.append({
                "gap_id":                  gap_id,
                "city_id":                 city_id,
                "domain":                  str(domain),
                "centroid_lat":            round(centroid_lat, 6),
                "centroid_lng":            round(centroid_lng, 6),
                "centroid_cell":           centroid_cell or "",
                "affected_cells":          len(cluster),
                "affected_domains":        str(domain),
                "estimated_impact_cells":  estimated_impact,
                "recommended_sensor_type": _recommended_sensor([str(domain)]),
            })

    if not records:
        return pd.DataFrame(columns=[
            "gap_id", "city_id", "domain", "centroid_lat", "centroid_lng",
            "centroid_cell", "affected_cells", "affected_domains",
            "estimated_impact_cells", "recommended_sensor_type",
        ])

    result_df = pd.DataFrame(records)
    result_df = result_df.sort_values(
        ["domain", "affected_cells"], ascending=[True, False]
    ).reset_index(drop=True)
    return result_df


# ---------------------------------------------------------------------------
# 4. Persist siting candidates
# ---------------------------------------------------------------------------

def populate_siting_candidates(city_id: str) -> int:
    """Compute coverage gaps and upsert them into h3_siting_candidates.

    Uses the simplified gap-cluster schema rather than the risk-weighted
    historical siting algorithm in writer.compute_and_store_siting().  Call
    this for a quick, real-time snapshot of where sensors are most needed.

    Returns
    -------
    int : number of candidate rows written (0 on failure or no gaps found)
    """
    s = _store()
    gaps_df = get_coverage_gaps(city_id)

    if gaps_df.empty:
        logger.info("[data_quality] %s — no coverage gaps found", city_id)
        return 0

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # period_start / period_end / period_days: use a 24-hour window to mark
    # this as a real-time snapshot, distinct from the 90-day historical siting
    period_end   = now_iso
    period_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    period_days  = 1

    rows = []
    for rank, (_, row) in enumerate(gaps_df.iterrows(), start=1):
        rows.append((
            city_id,
            str(row["domain"]),
            str(row["gap_id"]),      # h3_id — reuse gap_id as unique identifier
            rank,
            now_iso,
            period_start,
            period_end,
            period_days,
            None,                    # avg_risk_score — not computed in real-time gap mode
            None,                    # data_confidence
            None,                    # nearest_obs_km
            None,                    # coverage_gap
            float(row["affected_cells"]) / max(float(row["estimated_impact_cells"]), 1),
            float(row["centroid_lat"]),
            float(row["centroid_lng"]),
            int(row["affected_cells"]),
        ))

    sql = """
        INSERT OR REPLACE INTO h3_siting_candidates
            (city_id, domain, h3_id, rank, computed_at,
             period_start, period_end, period_days,
             avg_risk_score, data_confidence, nearest_obs_km,
             coverage_gap, siting_score,
             centroid_lat, centroid_lon, assessment_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    written = s.write_batch(sql, rows)
    logger.info(
        "[data_quality] %s — %d siting candidates written from %d gap clusters",
        city_id, written, len(gaps_df),
    )
    return written


# ---------------------------------------------------------------------------
# 5. City-level quality summary
# ---------------------------------------------------------------------------

def get_city_quality_summary(city_id: str) -> dict:
    """Return a quality dashboard dict for the city.

    Returns
    -------
    dict with keys:
        total_cells         : int — total distinct H3 cells with any signal
        domains_available   : list[str] — domains that have DATA_CONFIDENCE data
        per_domain          : dict[domain → {pct_ready, gap_count, top_gap_impact}]
        overall_pct_ready   : float — fraction of cells that are data-ready
        siting_candidates_count : int — rows currently in h3_siting_candidates
    """
    s = _store()

    # ── Total cells ───────────────────────────────────────────────────────────
    row = s.fetchone(
        "SELECT COUNT(DISTINCT h3_id) FROM h3_signals WHERE city_id = ?",
        [city_id],
    )
    total_cells: int = int(row[0]) if row else 0

    # ── Confidence per domain ─────────────────────────────────────────────────
    conf_df = get_cell_confidence(city_id)
    if conf_df.empty:
        domains_available: list[str] = []
        per_domain: dict[str, dict] = {}
        overall_pct_ready: float = 0.0
    else:
        domains_available = sorted(conf_df["domain"].unique().tolist())

        # Mark each cell as ready or not
        conf_df = conf_df.copy()
        conf_df["is_ready"] = conf_df["avg_confidence"] >= CONFIDENCE_READY_THRESHOLD

        overall_ready   = int(conf_df["is_ready"].sum())
        overall_total   = len(conf_df)
        overall_pct_ready = round(overall_ready / overall_total, 4) if overall_total > 0 else 0.0

        # Gap clusters for per-domain enrichment
        gaps_df = get_coverage_gaps(city_id)

        per_domain = {}
        for domain in domains_available:
            dom_df  = conf_df[conf_df["domain"] == domain]
            n_ready = int(dom_df["is_ready"].sum())
            n_total = len(dom_df)
            pct     = round(n_ready / n_total, 4) if n_total > 0 else 0.0

            dom_gaps = gaps_df[gaps_df["domain"] == domain] if not gaps_df.empty else pd.DataFrame()
            gap_count = len(dom_gaps)
            top_gap_impact = 0
            if not dom_gaps.empty and "estimated_impact_cells" in dom_gaps.columns:
                top_gap_impact = int(dom_gaps["estimated_impact_cells"].max())

            per_domain[domain] = {
                "pct_ready":      pct,
                "gap_count":      gap_count,
                "top_gap_impact": top_gap_impact,
            }

    # ── Siting candidates count ───────────────────────────────────────────────
    sc_row = s.fetchone(
        "SELECT COUNT(*) FROM h3_siting_candidates WHERE city_id = ?",
        [city_id],
    )
    siting_candidates_count = int(sc_row[0]) if sc_row else 0

    return {
        "total_cells":              total_cells,
        "domains_available":        domains_available,
        "per_domain":               per_domain,
        "overall_pct_ready":        overall_pct_ready,
        "siting_candidates_count":  siting_candidates_count,
    }


# ---------------------------------------------------------------------------
# Lightweight siting flag — called from ingestor (not full populate_siting)
# ---------------------------------------------------------------------------

def flag_low_confidence_cell(
    h3_id: str,
    city_id: str,
    domain: str,
    data_confidence: float,
    centroid_lat: float | None = None,
    centroid_lng: float | None = None,
) -> None:
    """Upsert a single low-confidence cell into h3_siting_candidates.

    Called by the ingest gate when DATA_CONFIDENCE < 0.6, rather than
    running the full cluster algorithm.  Uses INSERT OR REPLACE keyed on
    (city_id, domain, h3_id, period_start) — the period_start is set to the
    current calendar day so the row is refreshed each ingest cycle.

    Parameters
    ----------
    h3_id           : H3 cell identifier
    city_id         : city identifier
    domain          : domain name
    data_confidence : the actual confidence value (< 0.6)
    centroid_lat    : cell centroid latitude (derived from H3 if None)
    centroid_lng    : cell centroid longitude (derived from H3 if None)
    """
    from datetime import datetime, timezone

    # Derive centroid from H3 if not supplied
    if centroid_lat is None or centroid_lng is None:
        try:
            import h3 as _h3
            _lat, _lng = _h3.cell_to_latlng(h3_id)
            centroid_lat = float(_lat)
            centroid_lng = float(_lng)
        except Exception:
            centroid_lat = centroid_lat or 0.0
            centroid_lng = centroid_lng or 0.0

    now     = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    day_iso = now.strftime("%Y-%m-%dT00:00:00Z")

    s = _store()
    try:
        s.execute(
            """
            INSERT OR REPLACE INTO h3_siting_candidates
                (city_id, domain, h3_id, rank, computed_at,
                 period_start, period_end, period_days,
                 avg_risk_score, data_confidence, nearest_obs_km,
                 coverage_gap, siting_score,
                 centroid_lat, centroid_lon, assessment_count)
            VALUES (?, ?, ?, 0, ?,
                    ?, ?, 1,
                    NULL, ?, NULL,
                    ?, ?,
                    ?, ?, 0)
            """,
            [
                city_id, domain, h3_id, now_iso,
                day_iso, now_iso,
                float(data_confidence),
                round(1.0 - float(data_confidence), 4),
                round(1.0 - float(data_confidence), 4),  # siting_score = coverage_gap
                float(centroid_lat), float(centroid_lng),
            ],
        )
    except Exception as exc:
        logger.debug("flag_low_confidence_cell failed: %s", exc)
