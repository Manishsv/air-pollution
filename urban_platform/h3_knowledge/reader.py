"""Read helpers for H3 Knowledge Store — used by agents and dashboard."""
from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _store():
    from urban_platform.h3_knowledge.store import H3KnowledgeStore
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
) -> dict[str, Any]:
    """Return a rich context dict for an H3 Expert Agent.

    Structure:
        {
          "metadata": {...},
          "signals": [...],           # last N days, all domains
          "assessments": [...],       # one per domain, most recent
          "packets": [...],           # latest decision packets
          "insights": [...],          # prior agent insights
          "neighbors": {...},         # neighbor summary (optional)
        }
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

    # --- signals (last N days)
    signals_df = s.fetchdf(
        f"""
        SELECT h3_id, domain, signal, value, unit, source, level, observed_at
        FROM h3_signals
        WHERE h3_id = ? AND city_id = ?
          AND observed_at >= now() - INTERVAL '{signals_lookback_days} days'
        ORDER BY observed_at DESC
        LIMIT 500
        """,
        [h3_id, city_id],
    )
    signals = signals_df.to_dict(orient="records")

    # --- assessments — latest per domain
    assess_df = s.fetchdf(
        """
        SELECT DISTINCT ON (domain)
            domain, assessed_at, risk_level, primary_index,
            primary_value, dominant_issue, summary_json
        FROM h3_assessments
        WHERE h3_id = ? AND city_id = ?
        ORDER BY domain, assessed_at DESC
        """,
        [h3_id, city_id],
    )
    assessments = []
    for row in assess_df.to_dict(orient="records"):
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

    # --- insights
    insights_df = s.fetchdf(
        f"""
        SELECT insight_id, agent_type, created_at, domains_involved,
               finding, confidence, causal_chain_json
        FROM h3_insights
        WHERE h3_id = ? AND city_id = ?
        ORDER BY created_at DESC
        LIMIT {max_insights}
        """,
        [h3_id, city_id],
    )
    insights = []
    for row in insights_df.to_dict(orient="records"):
        if row.get("causal_chain_json"):
            row["causal_chain"] = _parse_json(row.pop("causal_chain_json"))
        if row.get("domains_involved"):
            row["domains_involved"] = row["domains_involved"].split(",")
        insights.append(row)

    context: dict[str, Any] = {
        "h3_id": h3_id,
        "city_id": city_id,
        "metadata": metadata,
        "signals": signals,
        "assessments": assessments,
        "packets": packets,
        "insights": insights,
    }

    if include_neighbors:
        context["neighbors"] = get_neighbors_summary(h3_id, city_id)

    return context


# ---------------------------------------------------------------------------
# Signals history — for time-series in the dashboard
# ---------------------------------------------------------------------------

def get_signals_history(
    h3_id: str,
    city_id: str,
    *,
    domain: str | None = None,
    signal: str | None = None,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """Return time-series of signals for an H3 cell."""
    filters = ["h3_id = ?", "city_id = ?", f"observed_at >= now() - INTERVAL '{lookback_days} days'"]
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
# Recent packets — for dashboard views
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
# Neighbor summary — spatial context for agents
# ---------------------------------------------------------------------------

def get_neighbors_summary(
    h3_id: str,
    city_id: str,
    *,
    ring: int = 1,
) -> dict[str, Any]:
    """Return a compact summary of risk levels for k-ring neighbors."""
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
        SELECT DISTINCT ON (h3_id, domain)
            h3_id, domain, risk_level, primary_index, primary_value
        FROM h3_assessments
        WHERE h3_id IN ({placeholders}) AND city_id = ?
        ORDER BY h3_id, domain, assessed_at DESC
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
# City-wide health summary — for city intelligence agent
# ---------------------------------------------------------------------------

def get_city_summary(
    city_id: str,
    *,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """Aggregate risk distribution per domain for the whole city."""
    s = _store()

    risk_df = s.fetchdf(
        f"""
        SELECT domain, risk_level, count(*) AS cell_count
        FROM (
            SELECT DISTINCT ON (h3_id, domain)
                h3_id, domain, risk_level
            FROM h3_assessments
            WHERE city_id = ?
              AND assessed_at >= now() - INTERVAL '{lookback_hours} hours'
            ORDER BY h3_id, domain, assessed_at DESC
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
          AND created_at >= now() - INTERVAL '{lookback_hours} hours'
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
# Store health / table counts (used by dashboard sidebar)
# ---------------------------------------------------------------------------

def get_store_stats() -> dict[str, int]:
    """Return row counts for all tables."""
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().table_counts()
    except Exception as exc:
        logger.warning("get_store_stats failed: %s", exc)
        return {}
