"""Read helpers for H3 Knowledge Store — used by agents and dashboard.

All SQL is SQLite-compatible:
  - datetime('now', '-N days/hours') replaces now() - INTERVAL
  - ROW_NUMBER() OVER (...) subquery replaces DISTINCT ON (...)
  - GROUP_CONCAT replaces string_agg
"""
from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _store():
    from airos.drivers.store.store import H3KnowledgeStore
    return H3KnowledgeStore.get()


def _parse_json(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


# ---------------------------------------------------------------------------
# Core agent context builder
# ---------------------------------------------------------------------------

def get_h3_context(
    h3_id: str,
    city_id: str,
    *,
    signals_lookback_days: int = 7,
    max_packets: int = 10,
    max_insights: int = 5,
    include_neighbors: bool = True,
    prefetched_forecast: dict | None = None,
) -> dict[str, Any]:
    """Return a rich context dict for an H3 Expert Agent.

    Parameters
    ----------
    prefetched_forecast:
        If provided, skip the OpenMeteo forecast API call and use this dict
        directly (format: {"weather": {...}, "aq": {...}}).  Pass this when
        running multiple cells for the same city so the forecast is only
        fetched once per sweep.
    """
    s = _store()

    # --- metadata
    meta_df = s.fetchdf(
        "SELECT * FROM h3_metadata WHERE h3_id = ? AND city_id = ?",
        [h3_id, city_id],
    )
    metadata = meta_df.to_dict(orient="records")[0] if not meta_df.empty else {}
    if metadata.get("known_features_json"):
        metadata["known_features"] = _parse_json(metadata.pop("known_features_json"))

    # --- signals (last N days) — SQLite datetime arithmetic
    signals_df = s.fetchdf(
        f"""
        SELECT h3_id, domain, signal, value, unit, source, level, observed_at
        FROM h3_signals
        WHERE h3_id = ? AND city_id = ?
          AND observed_at >= datetime('now', '-{signals_lookback_days} days')
        ORDER BY observed_at DESC
        LIMIT 500
        """,
        [h3_id, city_id],
    )
    signals = signals_df.to_dict(orient="records")

    # --- assessments — latest per domain (ROW_NUMBER instead of DISTINCT ON)
    assess_df = s.fetchdf(
        """
        SELECT domain, assessed_at, risk_level, primary_index,
               primary_value, dominant_issue, summary_json
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY domain ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE h3_id = ? AND city_id = ?
        ) WHERE rn = 1
        """,
        [h3_id, city_id],
    )
    assessments = []
    for row in assess_df.to_dict(orient="records"):
        row.pop("rn", None)
        if row.get("summary_json"):
            row["summary"] = _parse_json(row.pop("summary_json"))
        assessments.append(row)

    # --- packets
    packets_df = s.fetchdf(
        f"""
        SELECT packet_id, domain, created_at, risk_level, confidence_score,
               field_verification_required, outcome_status, packet_json
        FROM h3_packets
        WHERE h3_id = ? AND city_id = ?
        ORDER BY created_at DESC
        LIMIT {max_packets}
        """,
        [h3_id, city_id],
    )
    packets = []
    for row in packets_df.to_dict(orient="records"):
        if row.get("packet_json"):
            row["packet"] = _parse_json(row.pop("packet_json"))
        packets.append(row)

    # --- insights (with outcome tracking + hypothesis framing)
    insights_df = s.fetchdf(
        f"""
        SELECT insight_id, agent_type, created_at, domains_involved,
               finding, confidence, priority_tier, outcome_status,
               hypothesis_chain_json,
               recommended_actions_json, uncertainty_notes_json
        FROM h3_insights
        WHERE h3_id = ? AND city_id = ?
        ORDER BY created_at DESC
        LIMIT {max_insights}
        """,
        [h3_id, city_id],
    )
    insights = []
    for row in insights_df.to_dict(orient="records"):
        if row.get("hypothesis_chain_json"):
            row["hypothesis_chain"] = _parse_json(row.pop("hypothesis_chain_json"))
        else:
            row.pop("hypothesis_chain_json", None)
        if row.get("recommended_actions_json"):
            row["recommended_actions"] = _parse_json(row.pop("recommended_actions_json"))
        else:
            row.pop("recommended_actions_json", None)
        if row.get("uncertainty_notes_json"):
            row["uncertainty_notes"] = _parse_json(row.pop("uncertainty_notes_json"))
        else:
            row.pop("uncertainty_notes_json", None)
        if row.get("domains_involved"):
            row["domains_involved"] = row["domains_involved"].split(",")
        insights.append(row)

    # --- data staleness — last observed_at per domain for this cell
    # Surfaces to the agent so it knows if an assessment is based on stale data.
    staleness_df = s.fetchdf(
        """
        SELECT domain,
               MAX(observed_at)  AS last_observed_at,
               COUNT(*)          AS reading_count
        FROM h3_signals
        WHERE h3_id = ? AND city_id = ?
        GROUP BY domain
        """,
        [h3_id, city_id],
    )
    staleness: dict[str, dict] = {}
    if not staleness_df.empty:
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        for row in staleness_df.to_dict(orient="records"):
            try:
                last = datetime.fromisoformat(
                    row["last_observed_at"].replace("Z", "+00:00")
                )
                age_h = (now_utc - last).total_seconds() / 3600
            except Exception:
                age_h = None
            staleness[row["domain"]] = {
                "last_observed_at": row["last_observed_at"],
                "age_hours": round(age_h, 1) if age_h is not None else None,
                "stale": age_h is not None and age_h > 24,
            }

    # --- 30-day historical baseline — per-domain percentile context
    # Lets the agent tell apart "bad week" from "genuinely anomalous vs cell history"
    # N-guard: require >= 30 readings before reporting percentile rank —
    # below that threshold the rank is statistically unreliable.
    _BASELINE_MIN_N = 30

    def _pct(vals: list[float], p: float) -> float:
        """Return the p-th percentile of a pre-sorted list."""
        if not vals:
            return 0.0
        idx = max(0, int(len(vals) * p / 100) - 1)
        return round(vals[idx], 3)

    # Build latest-value lookup (domain → (signal_name, value)) once —
    # reused by both all-day and circadian baseline sections.
    latest_by_domain: dict[str, tuple[str, float]] = {}
    for sig in signals:
        d = sig.get("domain", "?")
        if d not in latest_by_domain and sig.get("value") is not None:
            latest_by_domain[d] = (sig.get("signal", "?"), sig["value"])

    baseline_df = s.fetchdf(
        """
        SELECT domain, signal,
               COUNT(*)                            AS n_readings,
               AVG(value)                          AS mean,
               MIN(value)                          AS min_val,
               MAX(value)                          AS max_val,
               GROUP_CONCAT(value)                 AS values_csv,
               SUM(CASE WHEN data_quality = 'real_station'     THEN 1 ELSE 0 END) AS n_real_station,
               SUM(CASE WHEN data_quality = 'model_estimate'   THEN 1 ELSE 0 END) AS n_model_estimate,
               SUM(CASE WHEN data_quality = 'satellite_derived' THEN 1 ELSE 0 END) AS n_satellite
        FROM h3_signals
        WHERE h3_id = ? AND city_id = ?
          AND observed_at >= datetime('now', '-30 days')
          AND value IS NOT NULL
        GROUP BY domain, signal
        """,
        [h3_id, city_id],
    )
    historical_baseline: dict[str, dict] = {}
    if not baseline_df.empty:
        for row in baseline_df.to_dict(orient="records"):
            domain = row["domain"]
            signal_name = row["signal"]
            n = row["n_readings"]
            if n < 5:
                continue  # fewer than 5 readings — not worth reporting at all

            # Parse and sort values to compute percentiles
            # (GROUP_CONCAT without ORDER BY — sort in Python for portability)
            try:
                sorted_vals = sorted(
                    float(v) for v in (row.get("values_csv") or "").split(",") if v
                )
            except Exception:
                sorted_vals = []

            # Provenance mix — what fraction of readings are real vs modelled
            n_real = row.get("n_real_station", 0) or 0
            n_model = row.get("n_model_estimate", 0) or 0
            n_sat = row.get("n_satellite", 0) or 0
            provenance_note = None
            if n > 0:
                mix_parts = []
                if n_real:
                    mix_parts.append(f"{n_real/n*100:.0f}% real_station")
                if n_sat:
                    mix_parts.append(f"{n_sat/n*100:.0f}% satellite_derived")
                if n_model:
                    mix_parts.append(f"{n_model/n*100:.0f}% model_estimate")
                provenance_note = ", ".join(mix_parts) if mix_parts else "unknown provenance"

            entry: dict[str, Any] = {
                "signal": signal_name,
                "n": n,
                "mean": round(row["mean"], 3),
                "min": round(row["min_val"], 3),
                "max": round(row["max_val"], 3),
                "p75": _pct(sorted_vals, 75),
                "p90": _pct(sorted_vals, 90),
                "provenance": provenance_note,
                "percentile_rank_reliable": n >= _BASELINE_MIN_N,
            }
            # Attach current value + percentile rank only if N meets the guard
            if domain in latest_by_domain:
                cur_sig, cur_val = latest_by_domain[domain]
                if cur_sig == signal_name:
                    entry["current"] = round(cur_val, 3)
                    if n >= _BASELINE_MIN_N and sorted_vals:
                        pct_rank = (
                            sum(1 for v in sorted_vals if v <= cur_val)
                            / len(sorted_vals) * 100
                        )
                        entry["percentile_rank"] = round(pct_rank, 0)
                    else:
                        # Too few readings — report raw value without a rank
                        entry["percentile_rank"] = None
            historical_baseline[domain] = entry

    # --- circadian baseline — same-hour-of-day stats over 30 days
    # Compares the current reading against readings taken at a similar time of
    # day (±2 hours UTC) over the past 30 days.  Removes the diurnal cycle so
    # a 2am PM2.5 spike is judged against other 2am readings rather than the
    # all-day mean.  Returned as a parallel dict keyed by domain.
    #
    # Hour window: current UTC hour ± 2 (wraps modulo 24 → 5 candidate hours).
    # N-guard: same _BASELINE_MIN_N threshold as all-day baseline.
    from datetime import datetime, timezone as _tz
    _now_h = datetime.now(_tz.utc).hour
    _circ_hours = [(_now_h + d) % 24 for d in range(-2, 3)]  # 5 hours
    _circ_placeholders = ",".join(str(h) for h in _circ_hours)

    circ_df = s.fetchdf(
        f"""
        SELECT domain, signal,
               COUNT(*)                            AS n_readings,
               AVG(value)                          AS mean,
               MIN(value)                          AS min_val,
               MAX(value)                          AS max_val,
               GROUP_CONCAT(value)                 AS values_csv
        FROM h3_signals
        WHERE h3_id = ? AND city_id = ?
          AND observed_at >= datetime('now', '-30 days')
          AND value IS NOT NULL
          AND CAST(strftime('%H', observed_at) AS INTEGER) IN ({_circ_placeholders})
        GROUP BY domain, signal
        """,
        [h3_id, city_id],
    )
    circadian_baseline: dict[str, dict] = {}
    if not circ_df.empty:
        for row in circ_df.to_dict(orient="records"):
            domain = row["domain"]
            signal_name = row["signal"]
            n = row["n_readings"]
            if n < 5:
                continue

            try:
                sorted_vals = sorted(
                    float(v) for v in (row.get("values_csv") or "").split(",") if v
                )
            except Exception:
                sorted_vals = []

            entry: dict[str, Any] = {
                "signal": signal_name,
                "n": n,
                "hour_window_utc": f"{_circ_hours[0]:02d}–{_circ_hours[-1]:02d}",
                "mean": round(row["mean"], 3),
                "min": round(row["min_val"], 3),
                "max": round(row["max_val"], 3),
                "p75": _pct(sorted_vals, 75),
                "p90": _pct(sorted_vals, 90),
                "percentile_rank_reliable": n >= _BASELINE_MIN_N,
            }
            # Attach current value + same-hour percentile rank
            if domain in latest_by_domain:
                cur_sig, cur_val = latest_by_domain[domain]
                if cur_sig == signal_name:
                    entry["current"] = round(cur_val, 3)
                    if n >= _BASELINE_MIN_N and sorted_vals:
                        pct_rank = (
                            sum(1 for v in sorted_vals if v <= cur_val)
                            / len(sorted_vals) * 100
                        )
                        entry["percentile_rank"] = round(pct_rank, 0)
                    else:
                        entry["percentile_rank"] = None
            circadian_baseline[domain] = entry

    # --- forecast — weather + AQ for next 48 h (OpenMeteo, no key needed)
    # If a pre-fetched city-level forecast is supplied (e.g. from run_top_risk_cells
    # which fetches once per city), use it directly — no HTTP call needed.
    # Otherwise fetch from the cell centroid; fails silently on network issues.
    if prefetched_forecast is not None:
        forecast: dict[str, Any] = prefetched_forecast
    else:
        forecast = {}
        centroid_lat = metadata.get("centroid_lat")
        centroid_lon = metadata.get("centroid_lon")
        if centroid_lat is None or centroid_lon is None:
            try:
                import h3
                centroid_lat, centroid_lon = h3.cell_to_latlng(h3_id)
            except Exception:
                pass
        if centroid_lat is not None and centroid_lon is not None:
            try:
                from airos.drivers.connectors.weather.open_meteo_forecast import fetch_cell_forecast
                forecast = fetch_cell_forecast(centroid_lat, centroid_lon, hours=48)
            except Exception as exc:
                logger.debug("Forecast fetch skipped: %s", exc)

    context: dict[str, Any] = {
        "h3_id": h3_id,
        "city_id": city_id,
        "metadata": metadata,
        "signals": signals,
        "assessments": assessments,
        "packets": packets,
        "insights": insights,
        "staleness": staleness,
        "historical_baseline": historical_baseline,
        "circadian_baseline": circadian_baseline,
        "forecast": forecast,
    }

    if include_neighbors:
        context["neighbors"] = get_neighbors_summary(h3_id, city_id)

    return context


# ---------------------------------------------------------------------------
# Signals history
# ---------------------------------------------------------------------------

def get_signals_history(
    h3_id: str,
    city_id: str,
    *,
    domain: str | None = None,
    signal: str | None = None,
    lookback_days: int = 30,
) -> pd.DataFrame:
    filters = [
        "h3_id = ?",
        "city_id = ?",
        f"observed_at >= datetime('now', '-{lookback_days} days')",
    ]
    params: list = [h3_id, city_id]
    if domain:
        filters.append("domain = ?")
        params.append(domain)
    if signal:
        filters.append("signal = ?")
        params.append(signal)
    where = " AND ".join(filters)
    return _store().fetchdf(
        f"SELECT * FROM h3_signals WHERE {where} ORDER BY observed_at",
        params,
    )


# ---------------------------------------------------------------------------
# Recent packets
# ---------------------------------------------------------------------------

def get_recent_packets(
    city_id: str,
    *,
    domain: str | None = None,
    risk_levels: list[str] | None = None,
    outcome_status: str | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    filters = ["city_id = ?"]
    params: list = [city_id]
    if domain:
        filters.append("domain = ?")
        params.append(domain)
    if risk_levels:
        placeholders = ",".join(["?" for _ in risk_levels])
        filters.append(f"risk_level IN ({placeholders})")
        params.extend(risk_levels)
    if outcome_status:
        filters.append("outcome_status = ?")
        params.append(outcome_status)
    where = " AND ".join(filters)
    return _store().fetchdf(
        f"""
        SELECT packet_id, h3_id, domain, created_at, risk_level,
               confidence_score, field_verification_required, outcome_status
        FROM h3_packets
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT {limit}
        """,
        params,
    )


# ---------------------------------------------------------------------------
# Neighbor summary
# ---------------------------------------------------------------------------

def get_neighbors_summary(
    h3_id: str,
    city_id: str,
    *,
    ring: int = 1,
) -> dict[str, Any]:
    try:
        import h3
        neighbors = list(h3.grid_disk(h3_id, ring) - {h3_id})
    except Exception:
        return {}

    if not neighbors:
        return {}

    placeholders = ",".join(["?" for _ in neighbors])
    assess_df = _store().fetchdf(
        f"""
        SELECT h3_id, domain, risk_level, primary_index, primary_value
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
            FROM h3_assessments
            WHERE h3_id IN ({placeholders}) AND city_id = ?
        ) WHERE rn = 1
        """,
        neighbors + [city_id],
    )

    if assess_df.empty:
        return {"neighbor_count": len(neighbors), "assessments": []}

    return {
        "neighbor_count": len(neighbors),
        "ring": ring,
        "assessments": assess_df.to_dict(orient="records"),
        "risk_distribution": assess_df["risk_level"].value_counts().to_dict(),
    }


# ---------------------------------------------------------------------------
# City-wide summary
# ---------------------------------------------------------------------------

def get_city_summary(
    city_id: str,
    *,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    s = _store()

    risk_df = s.fetchdf(
        f"""
        SELECT domain, risk_level, count(*) AS cell_count
        FROM (
            SELECT h3_id, domain, risk_level
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
                FROM h3_assessments
                WHERE city_id = ?
                  AND assessed_at >= datetime('now', '-{lookback_hours} hours')
            ) WHERE rn = 1
        ) latest
        GROUP BY domain, risk_level
        ORDER BY domain, risk_level
        """,
        [city_id],
    )

    pending_df = s.fetchdf(
        """
        SELECT domain, count(*) AS pending_count
        FROM h3_packets
        WHERE city_id = ? AND outcome_status = 'pending'
        GROUP BY domain
        """,
        [city_id],
    )

    insight_df = s.fetchdf(
        f"""
        SELECT h3_id, finding, confidence, domains_involved, created_at
        FROM h3_insights
        WHERE city_id = ?
          AND created_at >= datetime('now', '-{lookback_hours} hours')
        ORDER BY confidence DESC
        LIMIT 20
        """,
        [city_id],
    )

    return {
        "city_id": city_id,
        "lookback_hours": lookback_hours,
        "risk_by_domain": risk_df.to_dict(orient="records"),
        "pending_packets_by_domain": pending_df.to_dict(orient="records"),
        "top_insights": insight_df.to_dict(orient="records"),
    }


# ---------------------------------------------------------------------------
# Domain-filtered packet lookup (used by H3 Expert Agent tool)
# ---------------------------------------------------------------------------

def get_packets_for_domain(
    h3_id: str,
    city_id: str,
    domain: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the most recent decision packets for a specific cell+domain.

    Used by the H3 Expert Agent's ``get_packets_for_domain`` tool to calibrate
    the current insight against prior reviewer decisions for the same domain.

    Parameters
    ----------
    h3_id  : Target H3 cell index
    city_id: City partition key
    domain : Domain filter (e.g. "air", "flood")
    limit  : Maximum rows to return (default 5, per Agent Interface spec)

    Returns
    -------
    List of packet dicts, each with packet_id, domain, created_at,
    risk_level, confidence_score, field_verification_required,
    outcome_status, and decoded packet payload.
    """
    df = _store().fetchdf(
        f"""
        SELECT packet_id, domain, created_at, risk_level, confidence_score,
               field_verification_required, outcome_status, packet_json
        FROM h3_packets
        WHERE h3_id = ? AND city_id = ? AND domain = ?
        ORDER BY created_at DESC
        LIMIT {int(limit)}
        """,
        [h3_id, city_id, domain],
    )
    result = []
    for row in df.to_dict(orient="records"):
        if row.get("packet_json"):
            row["packet"] = _parse_json(row.pop("packet_json"))
        else:
            row.pop("packet_json", None)
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# City-level pattern reader (commissioner / strategic view)
# ---------------------------------------------------------------------------

def get_city_patterns(
    city_id: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the most recent city-level pattern summaries for *city_id*.

    Each record has:
        pattern_id, city_id, created_at, lookback_hours,
        n_insights, theme_count, summary   (parsed JSON dict)
    """
    try:
        df = _store().fetchdf(
            f"""
            SELECT pattern_id, city_id, created_at, lookback_hours,
                   n_insights, theme_count, summary_json
            FROM city_patterns
            WHERE city_id = ?
            ORDER BY created_at DESC
            LIMIT {int(limit)}
            """,
            [city_id],
        )
        records = []
        for row in df.to_dict(orient="records"):
            if row.get("summary_json"):
                row["summary"] = _parse_json(row.pop("summary_json"))
            else:
                row.pop("summary_json", None)
                row["summary"] = {}
            records.append(row)
        return records
    except Exception as exc:
        logger.warning("get_city_patterns failed for %s: %s", city_id, exc)
        return []


def get_city_health_summary(city_id: str) -> dict[str, Any]:
    """Return a lightweight city-health snapshot used by the Commissioner view.

    Returns
    -------
    {
        "city_id": str,
        "total_cells": int,
        "cells_assessed_24h": int,
        "open_insights": int,
        "critical_insights": int,       # priority_tier == 'high'
        "field_tasks_pending": int,     # packets with field_verification_required=1
        "domain_risk": {domain: worst_risk_level, ...},
        "latest_pattern_at": str | None,
        "latest_pattern_themes": int,
    }
    """
    s = _store()
    out: dict[str, Any] = {
        "city_id": city_id,
        "total_cells": 0,
        "cells_assessed_24h": 0,
        "open_insights": 0,
        "critical_insights": 0,
        "field_tasks_pending": 0,
        "domain_risk": {},
        "latest_pattern_at": None,
        "latest_pattern_themes": 0,
    }
    try:
        row = s.fetchone(
            "SELECT COUNT(*) FROM h3_metadata WHERE city_id = ?", [city_id]
        )
        out["total_cells"] = int(row[0]) if row else 0

        row = s.fetchone(
            "SELECT COUNT(DISTINCT h3_id) FROM h3_assessments "
            "WHERE city_id = ? AND assessed_at >= datetime('now', '-1 day')",
            [city_id],
        )
        out["cells_assessed_24h"] = int(row[0]) if row else 0

        row = s.fetchone(
            "SELECT COUNT(*) FROM h3_insights "
            "WHERE city_id = ? AND outcome_status = 'open'",
            [city_id],
        )
        out["open_insights"] = int(row[0]) if row else 0

        row = s.fetchone(
            "SELECT COUNT(*) FROM h3_insights "
            "WHERE city_id = ? AND outcome_status = 'open' AND priority_tier = 'high'",
            [city_id],
        )
        out["critical_insights"] = int(row[0]) if row else 0

        row = s.fetchone(
            "SELECT COUNT(*) FROM h3_packets "
            "WHERE city_id = ? AND field_verification_required = 1 "
            "AND outcome_status = 'pending'",
            [city_id],
        )
        out["field_tasks_pending"] = int(row[0]) if row else 0

        # Worst risk per domain (from latest assessment per cell)
        _RISK_ORDER = "CASE risk_level "
        _RISK_ORDER += "WHEN 'severe' THEN 4 WHEN 'high' THEN 3 "
        _RISK_ORDER += "WHEN 'moderate' THEN 2 WHEN 'low' THEN 1 ELSE 0 END"
        domain_df = s.fetchdf(
            f"""
            SELECT domain, risk_level
            FROM (
                SELECT domain, risk_level,
                       ROW_NUMBER() OVER (
                           PARTITION BY domain
                           ORDER BY {_RISK_ORDER} DESC, assessed_at DESC
                       ) AS rn
                FROM h3_assessments
                WHERE city_id = ?
                  AND assessed_at >= datetime('now', '-2 days')
            ) WHERE rn = 1
            """,
            [city_id],
        )
        out["domain_risk"] = dict(zip(domain_df["domain"], domain_df["risk_level"]))

        row = s.fetchone(
            "SELECT created_at, theme_count FROM city_patterns "
            "WHERE city_id = ? ORDER BY created_at DESC LIMIT 1",
            [city_id],
        )
        if row:
            out["latest_pattern_at"] = row[0]
            out["latest_pattern_themes"] = int(row[1]) if row[1] else 0

    except Exception as exc:
        logger.warning("get_city_health_summary failed for %s: %s", city_id, exc)
    return out


def get_ward_domain_risk(
    city_id: str,
    domain: str,
    *,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return top-N highest-risk H3 cells for a domain, for the Dept-Head view.

    Columns: h3_id, area_name, risk_level, primary_value, dominant_issue,
             assessed_at, centroid_lat, centroid_lon
    """
    s = _store()
    _RISK_ORDER = (
        "CASE a.risk_level "
        "WHEN 'severe' THEN 4 WHEN 'high' THEN 3 "
        "WHEN 'moderate' THEN 2 WHEN 'low' THEN 1 ELSE 0 END"
    )
    df = s.fetchdf(
        f"""
        SELECT a.h3_id,
               COALESCE(m.area_name, a.h3_id) AS area_name,
               a.risk_level,
               a.primary_value,
               a.dominant_issue,
               a.assessed_at,
               m.centroid_lat,
               m.centroid_lon
        FROM (
            SELECT h3_id, city_id, domain, risk_level, primary_value,
                   dominant_issue, assessed_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY h3_id
                       ORDER BY assessed_at DESC
                   ) AS rn
            FROM h3_assessments
            WHERE city_id = ? AND domain = ?
              AND assessed_at >= datetime('now', '-2 days')
        ) a
        LEFT JOIN h3_metadata m ON m.h3_id = a.h3_id AND m.city_id = ?
        WHERE a.rn = 1
        ORDER BY {_RISK_ORDER} DESC, a.assessed_at DESC
        LIMIT {int(top_n)}
        """,
        [city_id, domain, city_id],
    )
    return df


def get_field_tasks(
    city_id: str,
    *,
    limit: int = 50,
) -> pd.DataFrame:
    """Return pending field-verification packets for the Ward Officer view.

    Columns: packet_id, h3_id, domain, risk_level, created_at,
             area_name, centroid_lat, centroid_lon, dominant_issue
    """
    s = _store()
    df = s.fetchdf(
        f"""
        SELECT p.packet_id,
               p.h3_id,
               p.domain,
               p.risk_level,
               p.created_at,
               p.confidence_score,
               COALESCE(m.area_name, p.h3_id) AS area_name,
               m.centroid_lat,
               m.centroid_lon
        FROM h3_packets p
        LEFT JOIN h3_metadata m ON m.h3_id = p.h3_id AND m.city_id = p.city_id
        WHERE p.city_id = ?
          AND p.field_verification_required = 1
          AND p.outcome_status = 'pending'
        ORDER BY
            CASE p.risk_level
                WHEN 'severe' THEN 4 WHEN 'high' THEN 3
                WHEN 'moderate' THEN 2 WHEN 'low' THEN 1 ELSE 0
            END DESC,
            p.created_at DESC
        LIMIT {int(limit)}
        """,
        [city_id],
    )
    return df


# ---------------------------------------------------------------------------
# Store health
# ---------------------------------------------------------------------------

def get_store_stats(city_id: str | None = None) -> dict[str, Any]:
    """Return row counts for all Knowledge Store tables.

    Parameters
    ----------
    city_id : Optional city filter.  When provided, counts are scoped to that
              city's partition only (for tables that have a city_id column).
              Tables without a city_id column (e.g. city_patterns) return
              global counts regardless of this parameter.
    """
    try:
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        counts = store.table_counts()

        if city_id:
            # Augment with city-scoped counts for the primary partitioned tables
            _CITY_TABLES = [
                "h3_signals",
                "h3_assessments",
                "h3_packets",
                "h3_insights",
                "h3_ingest_log",
                "h3_metadata",
                "h3_analysis_requests",
                "h3_siting_candidates",
            ]
            city_counts: dict[str, Any] = {}
            for table in _CITY_TABLES:
                try:
                    row = store.fetchone(
                        f"SELECT COUNT(*) FROM {table} WHERE city_id = ?",
                        [city_id],
                    )
                    city_counts[table] = int(row[0]) if row else 0
                except Exception:
                    pass  # table may not exist in this schema version
            counts = {**counts, "city_id": city_id, "city_counts": city_counts}

        return counts
    except Exception as exc:
        logger.warning("get_store_stats failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Sensor siting recommendations  (reads pre-computed batch results)
# ---------------------------------------------------------------------------

def get_siting_recommendations(
    city_id: str,
    domain: str,
    *,
    top_n: int = 10,
) -> pd.DataFrame:
    """Return pre-computed sensor placement candidates from the last batch run.

    Results come from h3_siting_candidates, which is populated by
    run_siting_batch() on a monthly cadence (via the scheduler).
    The dashboard should NEVER compute siting scores live — sensor placement
    decisions are based on 90 days of sustained data, not yesterday's readings.

    Returns a DataFrame with columns:
        h3_id, rank, centroid_lat, centroid_lon, computed_at,
        period_start, period_end, period_days,
        avg_risk_score, data_confidence, nearest_obs_km,
        coverage_gap, siting_score, assessment_count

    Returns an empty DataFrame (with schema columns) when no batch has run yet.
    """
    s = _store()
    df = s.fetchdf(
        f"""
        SELECT
            h3_id, rank, centroid_lat, centroid_lon,
            computed_at, period_start, period_end, period_days,
            avg_risk_score, data_confidence, nearest_obs_km,
            coverage_gap, siting_score, assessment_count
        FROM h3_siting_candidates
        WHERE city_id = ?
          AND domain  = ?
          -- Only the most recent batch: pick max computed_at
          AND computed_at = (
              SELECT MAX(computed_at) FROM h3_siting_candidates
              WHERE city_id = ? AND domain = ?
          )
        ORDER BY rank
        LIMIT {top_n}
        """,
        [city_id, domain, city_id, domain],
    )
    return df


def get_siting_log(city_id: str | None = None) -> pd.DataFrame:
    """Return the siting batch log — when each domain was last computed."""
    s = _store()
    if city_id:
        return s.fetchdf(
            "SELECT * FROM h3_siting_log WHERE city_id = ? ORDER BY domain",
            [city_id],
        )
    return s.fetchdf("SELECT * FROM h3_siting_log ORDER BY city_id, domain")


# ---------------------------------------------------------------------------
# Async analysis request queue
# ---------------------------------------------------------------------------

def get_pending_requests(limit: int = 3) -> pd.DataFrame:
    """Return the oldest pending analysis requests (for the scheduler to process)."""
    return _store().fetchdf(
        f"""
        SELECT request_id, h3_id, city_id, requested_at
        FROM h3_analysis_requests
        WHERE status = 'pending'
        ORDER BY requested_at
        LIMIT {limit}
        """,
    )


def get_request_status(h3_id: str, city_id: str) -> dict:
    """Return the most recent analysis request for a cell (or empty dict if none)."""
    df = _store().fetchdf(
        """
        SELECT request_id, status, requested_at, started_at, completed_at,
               insight_id, error_msg
        FROM h3_analysis_requests
        WHERE h3_id = ? AND city_id = ?
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        [h3_id, city_id],
    )
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


# ---------------------------------------------------------------------------
# Cross-domain co-occurrence statistics
# ---------------------------------------------------------------------------

def get_domain_cross_correlation(
    city_id: str,
    domain_a: str,
    domain_b: str,
    *,
    risk_threshold: str = "high",
    lookback_days: int = 30,
    min_cells: int = 5,
) -> dict:
    """Return co-occurrence stats between two domains across all H3 cells.

    Answers: "In how many cells does elevated domain_a co-occur with
    elevated domain_b, compared to what random chance would predict?"

    Uses h3_assessments (latest assessment per domain per cell) to count:
      - n_a:    cells with domain_a ≥ risk_threshold
      - n_b:    cells with domain_b ≥ risk_threshold
      - n_both: cells where BOTH are elevated simultaneously
      - n_total: total assessed cells in city

    Returns a lift score: lift = (n_both / n_total) / ((n_a / n_total) * (n_b / n_total))
      lift > 1.5 → strong co-occurrence (meaningful)
      lift > 3.0 → very strong (worth flagging)
      lift ≈ 1.0 → independent (no relationship)
      lift < 0.7 → anti-correlated (rare)

    Parameters
    ----------
    risk_threshold:
        Minimum risk level to count as "elevated". One of: low, moderate, high, severe.
        Default "high" — only severe/high cells count.
    min_cells:
        Minimum number of co-occurring cells required before reporting stats
        (prevents spurious lift from tiny samples).
    """
    s = _store()

    # Numeric threshold for comparison (CASE value)
    _RISK_SCORE = {"low": 1, "moderate": 2, "high": 3, "severe": 4}
    threshold_score = _RISK_SCORE.get(risk_threshold, 3)

    # Build threshold IN clause: include all levels >= threshold
    valid_levels = [k for k, v in _RISK_SCORE.items() if v >= threshold_score]
    level_phs = ",".join(f"'{lv}'" for lv in valid_levels)

    # Latest assessment per (h3_id, domain) using ROW_NUMBER.
    # n_both uses an INNER JOIN on elevated cells — SQLite INTERSECT inside a
    # scalar subquery is unreliable (can return NULL).
    base_sql = f"""
        WITH latest AS (
            SELECT h3_id, domain, risk_level
            FROM (
                SELECT h3_id, domain, risk_level,
                       ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
                FROM h3_assessments
                WHERE city_id = ?
                  AND assessed_at >= date('now', '-{lookback_days} days')
            ) WHERE rn = 1
        ),
        elevated_a AS (
            SELECT DISTINCT h3_id FROM latest
            WHERE domain = ? AND risk_level IN ({level_phs})
        ),
        elevated_b AS (
            SELECT DISTINCT h3_id FROM latest
            WHERE domain = ? AND risk_level IN ({level_phs})
        ),
        co_elevated AS (
            SELECT a.h3_id FROM elevated_a a JOIN elevated_b b ON a.h3_id = b.h3_id
        )
        SELECT
            (SELECT COUNT(*) FROM elevated_a)  AS n_a,
            (SELECT COUNT(*) FROM elevated_b)  AS n_b,
            (SELECT COUNT(*) FROM co_elevated) AS n_both,
            COUNT(DISTINCT h3_id)              AS n_total
        FROM latest
    """

    df = s.fetchdf(base_sql, [city_id, domain_a, domain_b])
    if df.empty:
        return {"error": "No assessment data found", "city_id": city_id}

    row = df.iloc[0]
    n_a    = int(row["n_a"]    or 0)
    n_b    = int(row["n_b"]    or 0)
    n_both = int(row["n_both"] or 0)
    n_total = int(row["n_total"] or 0)

    # Lift calculation (avoid division by zero)
    if n_total == 0 or n_a == 0 or n_b == 0:
        lift = None
        interpretation = "insufficient data"
    else:
        p_a = n_a / n_total
        p_b = n_b / n_total
        p_both = n_both / n_total
        lift = round(p_both / (p_a * p_b), 2) if (p_a * p_b) > 0 else None
        if lift is None:
            interpretation = "insufficient data"
        elif n_both < min_cells:
            interpretation = f"too few co-occurring cells (n={n_both} < {min_cells}) — unreliable"
        elif lift >= 3.0:
            interpretation = "very strong co-occurrence — likely causal link"
        elif lift >= 1.5:
            interpretation = "moderate co-occurrence — worth investigating"
        elif lift >= 0.7:
            interpretation = "near-independent — domains not strongly linked"
        else:
            interpretation = "anti-correlated — elevated A associates with lower B"

    # Also fetch example cells where both are elevated (for spatial grounding)
    example_df = s.fetchdf(
        f"""
        WITH latest AS (
            SELECT h3_id, domain, risk_level
            FROM (
                SELECT h3_id, domain, risk_level,
                       ROW_NUMBER() OVER (PARTITION BY h3_id, domain ORDER BY assessed_at DESC) AS rn
                FROM h3_assessments
                WHERE city_id = ?
                  AND assessed_at >= date('now', '-{lookback_days} days')
            ) WHERE rn = 1
        )
        SELECT DISTINCT h3_id
        FROM latest
        WHERE domain = ? AND risk_level IN ({level_phs})
          AND h3_id IN (
              SELECT h3_id FROM latest WHERE domain = ? AND risk_level IN ({level_phs})
          )
        LIMIT 5
        """,
        [city_id, domain_a, domain_b],
    )
    example_cells = example_df["h3_id"].tolist() if not example_df.empty else []

    return {
        "city_id": city_id,
        "domain_a": domain_a,
        "domain_b": domain_b,
        "risk_threshold": risk_threshold,
        "lookback_days": lookback_days,
        "n_total_cells": n_total,
        "n_elevated_a": n_a,
        "n_elevated_b": n_b,
        "n_co_elevated": n_both,
        "lift": lift,
        "interpretation": interpretation,
        "example_co_elevated_cells": example_cells,
    }
