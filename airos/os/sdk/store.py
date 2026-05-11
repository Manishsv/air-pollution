"""
airos.os.sdk.store — live store query helpers (QUERY mode).

These functions read from the live H3 Knowledge Store (SQLite) written by the
AirOS pipeline.  They require the pipeline to have run at least once.

Contrast with the DISCOVER functions in ``airos.os.sdk`` (read from
``specifications/`` — no pipeline required) and the INGEST API (HTTP POST).

Typical usage
-------------
::

    from airos.os.sdk import store

    # What cells have been assessed in the last 24 h?
    assessed = store.get_assessments("bangalore")

    # Latest city-wide pattern summary
    patterns = store.get_city_patterns("bangalore")

    # Current health snapshot
    health = store.get_city_health_summary("bangalore")

    # Signals for a specific cell
    sigs = store.get_signals("bangalore", h3_id="886189a049fffff")

    # Field tasks awaiting verification
    tasks = store.get_field_tasks("bangalore")

    # Per-domain driver breakdown
    drivers = store.get_domain_drivers("bangalore")

    # Recent decision packets for a domain
    packets = store.get_packets("bangalore", domain="air_quality")

    # Store-wide row counts / freshness
    stats = store.get_stats("bangalore")

All functions return plain Python dicts or pandas DataFrames (see individual
docstrings).  Use ``AirOSClient`` for the full runtime query surface
(decision packets, observations, recommendations, events, metrics, audit).
"""

from __future__ import annotations

from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Internal import — deferred so the store module can be imported even when
# the store has never been initialised (it will raise at call time, not import).
# ---------------------------------------------------------------------------

def _reader():
    import airos.drivers.store.reader as r
    return r


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def get_signals(
    city_id: str,
    *,
    h3_id: str | None = None,
    domain: str | None = None,
    lookback_days: int = 7,
    limit: int = 500,
) -> pd.DataFrame:
    """Return recent signals for *city_id*, optionally filtered by cell or domain.

    Columns: h3_id, domain, signal, value, unit, source, level, observed_at.

    Parameters
    ----------
    city_id:
        City identifier (e.g. ``"bangalore"``).
    h3_id:
        Restrict to a single H3 cell.
    domain:
        Restrict to a single domain (e.g. ``"air_quality"``).
    lookback_days:
        How many days back to include (default 7).
    limit:
        Maximum rows returned (default 500).
    """
    from airos.drivers.store.store import H3KnowledgeStore
    s = H3KnowledgeStore.get()

    domain_clause = "AND domain = ?" if domain else ""
    h3_clause = "AND h3_id = ?" if h3_id else ""
    params: list[Any] = [city_id]
    if h3_id:
        params.append(h3_id)
    if domain:
        params.append(domain)

    return s.fetchdf(
        f"""
        SELECT h3_id, domain, signal, value, unit, source, level, observed_at
        FROM h3_signals
        WHERE city_id = ?
          {h3_clause}
          {domain_clause}
          AND observed_at >= datetime('now', '-{int(lookback_days)} days')
        ORDER BY observed_at DESC
        LIMIT {int(limit)}
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

def get_assessments(
    city_id: str,
    *,
    domain: str | None = None,
    risk_level: str | None = None,
    lookback_hours: int = 24,
    limit: int = 200,
) -> pd.DataFrame:
    """Return the most recent assessment per cell (and domain) for *city_id*.

    Columns: h3_id, domain, risk_level, primary_index, primary_value,
    confidence, assessed_at.

    Parameters
    ----------
    domain:
        Filter to a single domain.
    risk_level:
        Filter to ``"low"`` / ``"moderate"`` / ``"high"`` / ``"severe"``.
    lookback_hours:
        Only include assessments from the last N hours (default 24).
    limit:
        Maximum rows (default 200).
    """
    from airos.drivers.store.store import H3KnowledgeStore
    s = H3KnowledgeStore.get()

    domain_clause = "AND a.domain = ?" if domain else ""
    risk_clause = "AND a.risk_level = ?" if risk_level else ""
    params: list[Any] = [city_id]
    if domain:
        params.append(domain)
    if risk_level:
        params.append(risk_level)

    return s.fetchdf(
        f"""
        SELECT a.h3_id, a.domain, a.risk_level, a.primary_index,
               a.primary_value, a.confidence, a.assessed_at
        FROM h3_assessments a
        JOIN (
            SELECT h3_id, domain, MAX(assessed_at) AS latest
            FROM h3_assessments
            WHERE city_id = ?
              AND assessed_at >= datetime('now', '-{int(lookback_hours)} hours')
            GROUP BY h3_id, domain
        ) AS latest_row
          ON a.h3_id = latest_row.h3_id
         AND a.domain = latest_row.domain
         AND a.assessed_at = latest_row.latest
        WHERE a.city_id = ?
          {domain_clause}
          {risk_clause}
        ORDER BY a.assessed_at DESC
        LIMIT {int(limit)}
        """,
        [city_id] + params,
    )


# ---------------------------------------------------------------------------
# City patterns
# ---------------------------------------------------------------------------

def get_city_patterns(city_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return the most recent city-level AI pattern summaries for *city_id*.

    Each record contains: pattern_id, city_id, created_at, lookback_hours,
    n_insights, theme_count, summary (parsed dict).

    These are generated by ``CityPatternAgent`` after each pipeline sweep.
    """
    return _reader().get_city_patterns(city_id, limit=limit)


# ---------------------------------------------------------------------------
# City health snapshot
# ---------------------------------------------------------------------------

def get_city_health_summary(city_id: str) -> dict[str, Any]:
    """Return a health snapshot dict for *city_id*.

    Keys: total_cells, cells_assessed_24h, open_insights, critical_insights,
    field_tasks_pending, domain_risk (dict domain→worst risk level),
    latest_pattern_at.

    Useful for dashboards and alerting integrations.
    """
    return _reader().get_city_health_summary(city_id)


# ---------------------------------------------------------------------------
# Domain drivers
# ---------------------------------------------------------------------------

def get_domain_drivers(city_id: str) -> list[dict[str, Any]]:
    """Return a per-domain breakdown of risk drivers for *city_id*.

    Each record: domain, worst_risk, n_severe, n_high, n_moderate, n_low,
    top_issue, top_issue_cells, avg_value, max_value, primary_index.

    Use this to understand which domains are driving city-wide risk and
    how many cells are affected at each tier.
    """
    return _reader().get_domain_driver_summary(city_id)


# ---------------------------------------------------------------------------
# Decision packets
# ---------------------------------------------------------------------------

def get_packets(
    city_id: str,
    *,
    domain: str | None = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return recent decision / action packets for *city_id*.

    Columns: h3_id, domain, risk_level, action, priority, assigned_to,
    created_at.

    Parameters
    ----------
    domain:
        Restrict to a single domain.
    top_n:
        Maximum rows (default 20).
    """
    return _reader().get_packets_for_domain(city_id, domain=domain, top_n=top_n)


# ---------------------------------------------------------------------------
# Field tasks
# ---------------------------------------------------------------------------

def get_field_tasks(city_id: str, *, limit: int = 10) -> pd.DataFrame:
    """Return pending field-verification packets for *city_id*.

    Columns: h3_id, domain, risk_level, action, priority, created_at.

    These are unacknowledged packets that require on-ground verification.
    """
    return _reader().get_field_tasks(city_id, limit=limit)


# ---------------------------------------------------------------------------
# Ward / domain risk
# ---------------------------------------------------------------------------

def get_ward_domain_risk(
    city_id: str,
    domain: str,
    *,
    top_n: int = 10,
) -> pd.DataFrame:
    """Return the top-N highest-risk cells for *domain* in *city_id*.

    Columns: h3_id, risk_level, primary_value, assessed_at, area_name (if
    available from metadata).

    Useful for ward-level drill-down by domain.
    """
    return _reader().get_ward_domain_risk(city_id, domain, top_n=top_n)


# ---------------------------------------------------------------------------
# Store statistics
# ---------------------------------------------------------------------------

def get_stats(city_id: str | None = None) -> dict[str, Any]:
    """Return store-wide row counts and freshness metadata.

    Keys: n_signals, n_assessments, n_packets, n_insights, n_patterns,
    n_cells, latest_signal_at, latest_assessment_at.

    Pass ``city_id`` to restrict counts to a single city.
    """
    return _reader().get_store_stats(city_id)


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

def get_cell_metadata(h3_id: str, city_id: str) -> dict[str, Any]:
    """Return metadata for a single H3 cell.

    Keys: centroid_lat, centroid_lon, area_name, land_use_class (and others
    present in h3_metadata).  Returns an empty dict if the cell has no
    metadata record.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    try:
        df = H3KnowledgeStore.get().fetchdf(
            "SELECT * FROM h3_metadata WHERE h3_id = ? AND city_id = ?",
            [h3_id, city_id],
        )
        return df.iloc[0].to_dict() if not df.empty else {}
    except Exception:
        return {}


def get_insights(
    city_id: str | None,
    *,
    h3_id: str | None = None,
    min_confidence: float = 0.0,
    domains: list[str] | None = None,
    days_back: int = 7,
    priority_tier: str | None = None,
    outcome_status: str | None = "open",
    limit: int = 300,
) -> pd.DataFrame:
    """Return AI-generated insights with metadata JOIN.

    Columns: insight_id, h3_id, city_id, created_at, domains_involved,
    finding, confidence, priority_tier, outcome_status, closed_by, closed_at,
    hypothesis_chain_json, area_name, land_use_class, centroid_lat,
    centroid_lon, risk_score, risk_level.

    Parameters
    ----------
    city_id:
        City filter. Pass ``None`` to query all cities.
    min_confidence:
        Minimum confidence threshold (0–1).
    domains:
        If provided, post-filter to insights whose ``domains_involved``
        contains at least one of the listed domain names.
    days_back:
        How many days back to include (default 7).
    priority_tier:
        Filter to ``"high"`` / ``"medium"`` / ``"low"``.
    outcome_status:
        Filter by status (``"open"``, ``"confirmed"``, ``"refuted"``,
        ``"unverifiable"``).  Pass ``None`` for all.
    limit:
        Maximum rows (default 300).
    """
    from airos.drivers.store.store import H3KnowledgeStore
    from datetime import datetime, timezone, timedelta

    s = H3KnowledgeStore.get()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    where: list[str] = ["i.created_at >= ?", "i.confidence >= ?"]
    params: list[Any] = [cutoff, min_confidence]

    if city_id:
        where.append("i.city_id = ?")
        params.append(city_id)
    if h3_id:
        where.append("i.h3_id = ?")
        params.append(h3_id)
    if priority_tier:
        where.append("i.priority_tier = ?")
        params.append(priority_tier)
    if outcome_status:
        where.append("i.outcome_status = ?")
        params.append(outcome_status)

    _SCORE_RISK = {4: "severe", 3: "high", 2: "moderate", 1: "low", 0: "unknown"}

    df = s.fetchdf(f"""
        SELECT
            i.insight_id, i.h3_id, i.city_id, i.created_at,
            i.domains_involved, i.finding, i.confidence,
            i.priority_tier, i.outcome_status,
            i.closed_by, i.closed_at, i.hypothesis_chain_json,
            m.area_name, m.land_use_class, m.centroid_lat, m.centroid_lon,
            coalesce(max(CASE a.risk_level
                WHEN 'severe'   THEN 4
                WHEN 'high'     THEN 3
                WHEN 'moderate' THEN 2
                WHEN 'low'      THEN 1
                ELSE 0 END), 0) AS risk_score
        FROM h3_insights i
        LEFT JOIN h3_metadata m
            ON i.h3_id = m.h3_id AND i.city_id = m.city_id
        LEFT JOIN h3_assessments a
            ON i.h3_id = a.h3_id AND i.city_id = a.city_id
            AND a.day_bucket >= date('now', '-3 days')
        WHERE {" AND ".join(where)}
        GROUP BY i.insight_id, i.h3_id, i.city_id, i.created_at,
                 i.domains_involved, i.finding, i.confidence,
                 i.priority_tier, i.outcome_status, i.closed_by, i.closed_at,
                 i.hypothesis_chain_json, m.area_name, m.land_use_class,
                 m.centroid_lat, m.centroid_lon
        ORDER BY
            CASE i.priority_tier
                WHEN 'high'   THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low'    THEN 3
                ELSE 4 END,
            i.confidence DESC,
            i.created_at ASC
        LIMIT {int(limit)}
    """, params)

    if not df.empty:
        df["risk_level"] = df["risk_score"].map(_SCORE_RISK).fillna("unknown")
        if domains:
            df = df[df["domains_involved"].apply(
                lambda v: any(d in str(v) for d in domains) if pd.notna(v) else False
            )]
    return df


# ---------------------------------------------------------------------------
# Cell-level detail queries
# ---------------------------------------------------------------------------

def get_cell_neighbors(h3_id: str, city_id: str) -> list[dict[str, Any]]:
    """Return the latest risk_level per domain for the 1-ring H3 neighbours.

    Each record: h3_id, domain, risk_level.
    """
    try:
        import h3 as h3lib
        from airos.drivers.store.store import H3KnowledgeStore
        ring = list(h3lib.grid_disk(h3_id, 1) - {h3_id})
        if not ring:
            return []
        phs = ",".join("?" * len(ring))
        df = H3KnowledgeStore.get().fetchdf(
            f"""
            SELECT h3_id, domain, risk_level,
                   ROW_NUMBER() OVER (PARTITION BY h3_id, domain
                                      ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE h3_id IN ({phs}) AND city_id = ?
            """,
            ring + [city_id],
        )
        return df[df["rn"] == 1].drop(columns=["rn"]).to_dict(orient="records")
    except Exception:
        return []


def get_cell_assessments(h3_id: str, city_id: str) -> list[dict[str, Any]]:
    """Return the latest assessment per domain for a single H3 cell.

    Each record: domain, risk_level, assessed_at, primary_index, primary_value.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    df = H3KnowledgeStore.get().fetchdf(
        """
        SELECT domain, risk_level, assessed_at, primary_index, primary_value
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY domain ORDER BY assessed_at DESC
            ) AS rn
            FROM h3_assessments WHERE h3_id = ? AND city_id = ?
        ) WHERE rn = 1
        """,
        [h3_id, city_id],
    )
    return df.to_dict(orient="records")


def get_cell_signal_evidence(h3_id: str, city_id: str) -> dict[str, Any]:
    """Return signal evidence for a cell: latest values + 30-day percentile stats.

    Returns a dict with key ``"rows"`` (list of signal records).  Each record
    has: domain, signal, value, unit, data_quality, observed_at, and optionally
    ``pct_rank_30d`` and ``mean_30d`` when enough history exists.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    try:
        s = H3KnowledgeStore.get()
        latest_df = s.fetchdf(
            """
            SELECT domain, signal, value, unit, data_quality, observed_at
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY domain, signal ORDER BY observed_at DESC
                ) AS rn
                FROM h3_signals
                WHERE h3_id = ? AND city_id = ?
                  AND observed_at >= datetime('now', '-3 days')
            ) WHERE rn = 1
            """,
            [h3_id, city_id],
        )
        stats_df = s.fetchdf(
            """
            SELECT domain, signal,
                   COUNT(*) AS n, AVG(value) AS mean,
                   GROUP_CONCAT(value) AS vals_csv
            FROM h3_signals
            WHERE h3_id = ? AND city_id = ?
              AND observed_at >= datetime('now', '-30 days')
              AND value IS NOT NULL
            GROUP BY domain, signal
            """,
            [h3_id, city_id],
        )
        stats: dict = {}
        for row in stats_df.to_dict(orient="records"):
            try:
                vals = sorted(float(v) for v in (row["vals_csv"] or "").split(",") if v)
            except Exception:
                vals = []
            stats[(row["domain"], row["signal"])] = {
                "n": row["n"], "mean": row["mean"], "vals": vals,
            }
        result: list[dict] = []
        for row in latest_df.to_dict(orient="records"):
            entry = dict(row)
            key = (row["domain"], row["signal"])
            st_info = stats.get(key, {})
            vals = st_info.get("vals", [])
            n = st_info.get("n", 0)
            cur = row.get("value")
            if cur is not None and vals and n >= 10:
                entry["pct_rank_30d"] = round(sum(1 for v in vals if v <= cur) / len(vals) * 100)
                entry["mean_30d"] = round(st_info.get("mean", 0), 3)
            result.append(entry)
        return {"rows": result}
    except Exception as exc:
        return {"rows": [], "error": str(exc)}


def get_prior_outcomes(
    h3_id: str,
    city_id: str,
    *,
    exclude_insight_id: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return prior closed insights for a cell (excluding the current one).

    Each record: insight_id, agent_type, created_at, domains_involved,
    finding, confidence, outcome_status, closed_by, closed_at.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    df = H3KnowledgeStore.get().fetchdf(
        """
        SELECT insight_id, agent_type, created_at, domains_involved,
               finding, confidence, outcome_status, closed_by, closed_at
        FROM h3_insights
        WHERE h3_id = ? AND city_id = ?
          AND insight_id != ?
          AND outcome_status != 'open'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        [h3_id, city_id, exclude_insight_id, limit],
    )
    return df.to_dict(orient="records")


def get_cell_packets(h3_id: str, city_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return recent decision packets for a single H3 cell.

    Each record: packet_id, domain, created_at, risk_level, outcome_status,
    safety_gates (list), blocked_uses (list).
    """
    import json
    from airos.drivers.store.store import H3KnowledgeStore
    df = H3KnowledgeStore.get().fetchdf(
        """
        SELECT packet_id, domain, created_at, risk_level, outcome_status,
               safety_gates_json, blocked_uses_json
        FROM h3_packets
        WHERE h3_id = ? AND city_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        [h3_id, city_id, limit],
    )
    rows = []
    for r in df.to_dict(orient="records"):
        for col in ("safety_gates_json", "blocked_uses_json"):
            key = col.replace("_json", "")
            raw = r.pop(col, None)
            try:
                r[key] = json.loads(raw) if raw else []
            except Exception:
                r[key] = []
        rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# Map cells (complex CTE)
# ---------------------------------------------------------------------------

def get_map_cells(city_id: str, *, days_back: int = 3) -> pd.DataFrame:
    """Return H3 cells for map rendering: worst risk + top metric + latest insight.

    Columns: h3_id, city_id, risk_score, domains, domain_count, top_domain,
    top_index, top_value, dominant_issue, lat, lon, area_name, land_use_class,
    finding, confidence, insight_id, insight_at.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    return H3KnowledgeStore.get().fetchdf(f"""
        WITH cell_risk AS (
            SELECT h3_id, city_id,
                   max(CASE risk_level
                       WHEN 'severe'   THEN 4 WHEN 'high' THEN 3
                       WHEN 'moderate' THEN 2 WHEN 'low'  THEN 1
                       ELSE 0 END) AS risk_score,
                   GROUP_CONCAT(DISTINCT domain) AS domains,
                   count(DISTINCT domain)         AS domain_count
            FROM h3_assessments
            WHERE city_id = ?
              AND day_bucket >= date('now', '-{int(days_back)} days')
            GROUP BY h3_id, city_id
        ),
        top_assess AS (
            SELECT h3_id, city_id, domain AS top_domain,
                   primary_index AS top_index, primary_value AS top_value,
                   dominant_issue
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY h3_id, city_id
                           ORDER BY CASE risk_level
                               WHEN 'severe' THEN 4 WHEN 'high' THEN 3
                               WHEN 'moderate' THEN 2 WHEN 'low' THEN 1
                               ELSE 0 END DESC
                       ) AS rn
                FROM h3_assessments
                WHERE city_id = ?
                  AND day_bucket >= date('now', '-{int(days_back)} days')
            ) WHERE rn = 1
        ),
        latest_insight AS (
            SELECT h3_id, city_id, finding, confidence, insight_id, created_at
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY h3_id, city_id ORDER BY created_at DESC
                ) AS rn
                FROM h3_insights WHERE city_id = ?
            ) WHERE rn = 1
        )
        SELECT cr.h3_id, cr.city_id, cr.risk_score, cr.domains, cr.domain_count,
               ta.top_domain, ta.top_index, ta.top_value, ta.dominant_issue,
               m.centroid_lat AS lat, m.centroid_lon AS lon,
               m.area_name, m.land_use_class,
               li.finding, li.confidence, li.insight_id,
               li.created_at AS insight_at
        FROM cell_risk cr
        LEFT JOIN top_assess ta
            ON cr.h3_id = ta.h3_id AND cr.city_id = ta.city_id
        LEFT JOIN h3_metadata m
            ON cr.h3_id = m.h3_id AND cr.city_id = m.city_id
        LEFT JOIN latest_insight li
            ON cr.h3_id = li.h3_id AND cr.city_id = li.city_id
    """, [city_id, city_id, city_id])


# ---------------------------------------------------------------------------
# Ingest log & raw signals
# ---------------------------------------------------------------------------

def get_ingest_log(
    city_id: str | None,
    domains: list[str] | None = None,
) -> pd.DataFrame:
    """Return ingest log rows, optionally filtered by city and/or domain list.

    Columns: city_id, domain, last_ingested_at, rows_written, status, error_msg.

    Pass ``city_id=None`` to return all cities.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    s = H3KnowledgeStore.get()
    where_clauses: list[str] = []
    params: list[Any] = []
    if city_id is not None:
        where_clauses.append("city_id = ?")
        params.append(city_id)
    if domains:
        ph = ",".join("?" * len(domains))
        where_clauses.append(f"domain IN ({ph})")
        params.extend(domains)
    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return s.fetchdf(
        f"SELECT city_id, domain, last_ingested_at, rows_written, status, error_msg "
        f"FROM h3_ingest_log {where} ORDER BY city_id, domain",
        params,
    )


def get_latest_signals_table(
    city_id: str,
    domains: list[str] | None = None,
) -> pd.DataFrame:
    """Return the latest signal value per (h3_id, domain, signal) for *city_id*.

    Columns: h3_id, domain, signal, value, unit, hour_bucket, source.
    Optionally restrict to *domains*.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    s = H3KnowledgeStore.get()
    if domains:
        ph = ",".join("?" * len(domains))
        return s.fetchdf(
            f"""
            SELECT s.h3_id, s.domain, s.signal, s.value, s.unit, s.hour_bucket, s.source
            FROM h3_signals s
            INNER JOIN (
                SELECT h3_id, domain, signal, MAX(hour_bucket) AS max_hb
                FROM h3_signals
                WHERE city_id = ? AND domain IN ({ph})
                GROUP BY h3_id, domain, signal
            ) latest
              ON s.h3_id = latest.h3_id AND s.domain = latest.domain
             AND s.signal = latest.signal AND s.hour_bucket = latest.max_hb
            WHERE s.city_id = ?
            ORDER BY s.h3_id, s.domain, s.signal
            """,
            [city_id, *domains, city_id],
        )
    return s.fetchdf(
        """
        SELECT s.h3_id, s.domain, s.signal, s.value, s.unit, s.hour_bucket, s.source
        FROM h3_signals s
        INNER JOIN (
            SELECT h3_id, domain, signal, MAX(hour_bucket) AS max_hb
            FROM h3_signals WHERE city_id = ?
            GROUP BY h3_id, domain, signal
        ) latest
          ON s.h3_id = latest.h3_id AND s.domain = latest.domain
         AND s.signal = latest.signal AND s.hour_bucket = latest.max_hb
        WHERE s.city_id = ?
        ORDER BY s.h3_id, s.domain, s.signal
        """,
        [city_id, city_id],
    )


# ---------------------------------------------------------------------------
# Analysis request queue
# ---------------------------------------------------------------------------

def get_analysis_queue() -> pd.DataFrame:
    """Return analysis request counts grouped by status.

    Columns: status, count.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    try:
        return H3KnowledgeStore.get().fetchdf(
            "SELECT status, count(*) AS count FROM h3_analysis_requests "
            "GROUP BY status ORDER BY status"
        )
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Observations (from observation store)
# ---------------------------------------------------------------------------

def get_recent_observations(
    domain: str,
    city_id: str,
    *,
    max_age_hours: int = 1,
) -> pd.DataFrame:
    """Return recent cached observations for *domain* in *city_id*.

    Wraps ``ObservationStoreReader.read_recent()``.  Returns an empty DataFrame
    if no observations are available or the observation store has not been
    populated.

    Parameters
    ----------
    domain:
        Domain key (e.g. ``"air"``, ``"heat"``, ``"flood"``).
    city_id:
        City identifier.
    max_age_hours:
        Maximum age of observations in hours (default 1).
    """
    try:
        from airos.drivers.observation_store.reader import ObservationStoreReader
        return ObservationStoreReader().read_recent(domain, city_id, max_age_hours=max_age_hours)
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------

def get_quality_summary(city_id: str) -> dict[str, Any]:
    """Return a data quality summary for *city_id*.

    Wraps ``airos.drivers.store.data_quality.get_city_quality_summary()``.
    Returns an empty dict if quality metrics are unavailable.
    """
    try:
        from airos.drivers.store.data_quality import get_city_quality_summary
        return get_city_quality_summary(city_id) or {}
    except Exception:
        return {}


def get_cell_confidence(
    city_id: str,
    domain: str | None = None,
) -> pd.DataFrame:
    """Return per-cell DATA_CONFIDENCE from the latest ingested hour bucket.

    Wraps ``airos.drivers.store.data_quality.get_cell_confidence()``.
    Returns an empty DataFrame if data quality metrics are unavailable.

    Parameters
    ----------
    city_id:
        City identifier (e.g. ``"bangalore"``).
    domain:
        Optional domain filter (e.g. ``"air"``). Returns all domains if omitted.
    """
    try:
        from airos.drivers.store.data_quality import get_cell_confidence as _fn
        return _fn(city_id, domain)
    except Exception:
        return pd.DataFrame()


def get_domain_signals_latest(city_id: str, domain: str) -> pd.DataFrame:
    """Return the latest signal value per (h3_id, signal) for a single domain.

    Uses ``observed_at`` for deduplication (most recent reading per cell+signal).
    Columns: h3_id, signal, value, unit, observed_at.

    This is the standard path for domain-specific panels (terrain, nightlights,
    etc.) that need a pivotable wide table per city.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    try:
        return H3KnowledgeStore.get().fetchdf(
            """
            SELECT h3_id, signal, value, unit, observed_at
            FROM (
                SELECT h3_id, signal, value, unit, observed_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY h3_id, signal
                           ORDER BY observed_at DESC
                       ) AS rn
                FROM h3_signals
                WHERE city_id = ? AND domain = ?
            ) WHERE rn = 1
            ORDER BY h3_id, signal
            """,
            [city_id, domain],
        )
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# City registry
# ---------------------------------------------------------------------------

def list_cities() -> list[str]:
    """Return all registered city IDs.

    Tries ``airos.drivers.place.city_registry`` first, then falls back to
    ``airos.os.city_config.CITIES``, then returns ``["bangalore"]``.
    """
    try:
        from airos.drivers.place.city_registry import all_city_ids
        cities = all_city_ids()
        if cities:
            return cities
    except Exception:
        pass
    try:
        from airos.os.city_config import CITIES
        return list(CITIES.keys())
    except Exception:
        pass
    return ["bangalore"]


# ---------------------------------------------------------------------------
# Latest AQI (citizen view helper)
# ---------------------------------------------------------------------------

def get_latest_aqi(city_id: str) -> float | None:
    """Return the most recent AQI signal value for *city_id*, or ``None``.

    Checks common AQI signal names: ``AQI``, ``aqi``, ``pm25_aqi``, etc.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    try:
        row = H3KnowledgeStore.get().fetchone(
            """
            SELECT value FROM h3_signals
            WHERE city_id = ? AND domain = 'air'
              AND signal IN ('AQI','aqi','pm25_aqi','PM25_AQI','PM2.5_AQI')
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            [city_id],
        )
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None
