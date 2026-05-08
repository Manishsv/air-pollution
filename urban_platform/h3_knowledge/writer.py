"""Write helpers for the H3 Knowledge Store.

All writes use upsert semantics — running the same ingest job twice
produces the same number of rows, not double.

Deduplication keys:
  h3_signals     — (h3_id, city_id, domain, signal, hour_bucket)  → newer value wins
  h3_assessments — (h3_id, city_id, domain, day_bucket)           → newer value wins
  h3_packets     — packet_id                                       → DO NOTHING on duplicate
  h3_metadata    — (h3_id, city_id)                               → DO UPDATE last_active
  h3_ingest_log  — (city_id, domain)                              → DO UPDATE watermark
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _store():
    from urban_platform.h3_knowledge.store import H3KnowledgeStore
    return H3KnowledgeStore.get()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(obj: Any) -> str | None:
    if obj is None:
        return None
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


# ---------------------------------------------------------------------------
# Metadata upsert
# ---------------------------------------------------------------------------

def upsert_metadata(
    *,
    h3_id: str,
    city_id: str,
    resolution: int,
    centroid_lat: float | None = None,
    centroid_lon: float | None = None,
    land_use_class: str | None = None,
    known_features: list[str] | None = None,
) -> None:
    try:
        now = _now_iso()
        _store().execute(
            """
            INSERT INTO h3_metadata
                (h3_id, city_id, resolution, centroid_lat, centroid_lon,
                 land_use_class, known_features_json, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (h3_id, city_id) DO UPDATE SET
                centroid_lat        = COALESCE(excluded.centroid_lat,        h3_metadata.centroid_lat),
                centroid_lon        = COALESCE(excluded.centroid_lon,        h3_metadata.centroid_lon),
                land_use_class      = COALESCE(excluded.land_use_class,      h3_metadata.land_use_class),
                known_features_json = COALESCE(excluded.known_features_json, h3_metadata.known_features_json),
                last_active         = excluded.last_active
            """,
            [h3_id, city_id, resolution,
             centroid_lat, centroid_lon, land_use_class,
             _safe_json(known_features), now, now],
        )
    except Exception as exc:
        logger.warning("upsert_metadata failed: %s", exc)


# ---------------------------------------------------------------------------
# Level 0/1 — signals (one row per cell/signal/hour — deduped)
# ---------------------------------------------------------------------------

def write_signals(
    rows: list[dict[str, Any]],
    *,
    city_id: str,
    domain: str,
    level: int = 1,
    source: str = "pipeline",
) -> int:
    """Upsert signal rows.  One row per (h3_id, signal, hour).

    Each dict must have: h3_id, signal, value
    Optional: unit, observed_at (ISO string), source, level
    """
    if not rows:
        return 0
    inserted = 0
    try:
        s = _store()
        now = _now_iso()
        for r in rows:
            h3_id = r.get("h3_id")
            if not h3_id or r.get("value") is None:
                continue
            observed_at = r.get("observed_at", now)
            s.execute(
                """
                INSERT INTO h3_signals
                    (h3_id, city_id, domain, signal, hour_bucket,
                     value, unit, source, level, observed_at, fetched_at)
                VALUES (
                    ?, ?, ?, ?, date_trunc('hour', ?::TIMESTAMPTZ),
                    ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT (h3_id, city_id, domain, signal, hour_bucket) DO UPDATE SET
                    value       = excluded.value,
                    source      = excluded.source,
                    observed_at = excluded.observed_at,
                    fetched_at  = excluded.fetched_at
                """,
                [
                    h3_id, r.get("city_id", city_id), r.get("domain", domain),
                    r["signal"], observed_at,
                    float(r["value"]),
                    r.get("unit"), r.get("source", source),
                    r.get("level", level), observed_at, now,
                ],
            )
            inserted += 1
        logger.debug("write_signals: %d rows upserted [%s/%s]", inserted, city_id, domain)
    except Exception as exc:
        logger.warning("write_signals failed: %s", exc)
    return inserted


# ---------------------------------------------------------------------------
# Level 2 — assessments (one row per cell/domain/day — deduped)
# ---------------------------------------------------------------------------

def write_assessment(
    *,
    h3_id: str,
    city_id: str,
    domain: str,
    risk_level: str,
    primary_index: str | None = None,
    primary_value: float | None = None,
    dominant_issue: str | None = None,
    summary: dict | None = None,
    assessed_at: str | None = None,
) -> None:
    """Upsert an assessment.  Only one row per (h3_id, city_id, domain, day).
    If the same cell is assessed twice in the same day, the newer value wins.
    """
    try:
        now = assessed_at or _now_iso()
        _store().execute(
            """
            INSERT INTO h3_assessments
                (h3_id, city_id, domain, day_bucket, assessed_at,
                 risk_level, primary_index, primary_value, dominant_issue, summary_json)
            VALUES (
                ?, ?, ?, date_trunc('day', ?::TIMESTAMPTZ)::DATE, ?,
                ?, ?, ?, ?, ?
            )
            ON CONFLICT (h3_id, city_id, domain, day_bucket) DO UPDATE SET
                assessed_at    = excluded.assessed_at,
                risk_level     = excluded.risk_level,
                primary_index  = excluded.primary_index,
                primary_value  = excluded.primary_value,
                dominant_issue = excluded.dominant_issue,
                summary_json   = excluded.summary_json
            """,
            [
                h3_id, city_id, domain, now, now,
                risk_level, primary_index,
                float(primary_value) if primary_value is not None else None,
                dominant_issue, _safe_json(summary),
            ],
        )
    except Exception as exc:
        logger.warning("write_assessment failed: %s", exc)


# ---------------------------------------------------------------------------
# Level 3 — packets (idempotent on packet_id)
# ---------------------------------------------------------------------------

def write_packet(
    *,
    packet_id: str,
    h3_id: str,
    city_id: str,
    domain: str,
    risk_level: str,
    confidence_score: float | None = None,
    field_verification_required: bool = False,
    packet: dict,
    created_at: str | None = None,
) -> None:
    """Insert a decision packet.  Duplicate packet_id is silently ignored."""
    if not packet_id or not h3_id:
        return
    try:
        _store().execute(
            """
            INSERT INTO h3_packets
                (packet_id, h3_id, city_id, domain, created_at,
                 risk_level, confidence_score, field_verification_required,
                 packet_json, outcome_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT (packet_id) DO NOTHING
            """,
            [
                packet_id, h3_id, city_id, domain,
                created_at or _now_iso(),
                risk_level,
                float(confidence_score) if confidence_score is not None else None,
                bool(field_verification_required),
                _safe_json(packet),
            ],
        )
    except Exception as exc:
        logger.warning("write_packet failed: %s", exc)


def update_packet_outcome(*, packet_id: str, outcome_status: str) -> None:
    try:
        _store().execute(
            "UPDATE h3_packets SET outcome_status = ? WHERE packet_id = ?",
            [outcome_status, packet_id],
        )
    except Exception as exc:
        logger.warning("update_packet_outcome failed: %s", exc)


# ---------------------------------------------------------------------------
# Level 4 — agent insights (always new, no dedup)
# ---------------------------------------------------------------------------

def write_insight(
    *,
    h3_id: str,
    city_id: str,
    agent_type: str,
    domains_involved: list[str],
    finding: str,
    confidence: float | None = None,
    causal_chain: list[dict] | None = None,
    created_at: str | None = None,
) -> str:
    insight_id = str(uuid.uuid4())
    try:
        _store().execute(
            """
            INSERT INTO h3_insights
                (insight_id, h3_id, city_id, agent_type, created_at,
                 domains_involved, finding, confidence, causal_chain_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                insight_id, h3_id, city_id, agent_type,
                created_at or _now_iso(),
                ",".join(domains_involved) if domains_involved else None,
                finding,
                float(confidence) if confidence is not None else None,
                _safe_json(causal_chain),
            ],
        )
    except Exception as exc:
        logger.warning("write_insight failed: %s", exc)
    return insight_id


# ---------------------------------------------------------------------------
# Level 5 — field outcomes (human-entered, always new)
# ---------------------------------------------------------------------------

def write_outcome(
    *,
    packet_id: str,
    h3_id: str,
    city_id: str,
    domain: str,
    outcome_type: str,
    finding: str | None = None,
    resolved_by: str | None = None,
) -> str:
    outcome_id = str(uuid.uuid4())
    try:
        _store().execute(
            """
            INSERT INTO h3_outcomes
                (outcome_id, packet_id, h3_id, city_id, domain,
                 recorded_at, outcome_type, finding, resolved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [outcome_id, packet_id, h3_id, city_id, domain,
             _now_iso(), outcome_type, finding, resolved_by],
        )
        update_packet_outcome(packet_id=packet_id, outcome_status=outcome_type)
    except Exception as exc:
        logger.warning("write_outcome failed: %s", exc)
    return outcome_id


# ---------------------------------------------------------------------------
# Ingest log — watermark per (city, domain)
# ---------------------------------------------------------------------------

def record_ingest(
    *,
    city_id: str,
    domain: str,
    rows_written: int = 0,
    status: str = "ok",
    error_msg: str | None = None,
) -> None:
    try:
        _store().execute(
            """
            INSERT INTO h3_ingest_log
                (city_id, domain, last_ingested_at, rows_written, status, error_msg)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (city_id, domain) DO UPDATE SET
                last_ingested_at = excluded.last_ingested_at,
                rows_written     = excluded.rows_written,
                status           = excluded.status,
                error_msg        = excluded.error_msg
            """,
            [city_id, domain, _now_iso(), rows_written, status, error_msg],
        )
    except Exception as exc:
        logger.warning("record_ingest failed: %s", exc)


def get_last_ingest(city_id: str, domain: str) -> datetime | None:
    """Return the last successful ingest time, or None if never run."""
    row = _store().fetchone(
        "SELECT last_ingested_at FROM h3_ingest_log WHERE city_id = ? AND domain = ? AND status = 'ok'",
        [city_id, domain],
    )
    if row and row[0]:
        ts = row[0]
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(str(ts))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Bulk helper — used by ingestor only (not panels)
# ---------------------------------------------------------------------------

def ingest_assessment_cells(
    cells: list[dict],
    *,
    city_id: str,
    domain: str,
    signal_key: str,
    risk_key: str,
    issue_key: str | None = None,
    unit: str = "",
    source: str = "pipeline",
    resolution: int = 8,
) -> int:
    """Write signals + assessments for a batch of cell dicts.

    Designed to be called from the batch ingestor, not the dashboard.
    Returns total signal rows written.
    """
    signal_rows: list[dict] = []
    for cell in cells:
        h3_id = cell.get("h3_id")
        value = cell.get(signal_key)
        risk  = cell.get(risk_key, "unknown")
        if not h3_id or value is None:
            continue
        upsert_metadata(
            h3_id=h3_id, city_id=city_id, resolution=resolution,
            centroid_lat=cell.get("centroid_lat"),
            centroid_lon=cell.get("centroid_lon"),
        )
        signal_rows.append({
            "h3_id": h3_id,
            "signal": signal_key.upper(),
            "value": value,
            "unit": unit,
            "source": source,
            "level": 1,
        })
        write_assessment(
            h3_id=h3_id, city_id=city_id, domain=domain,
            risk_level=risk,
            primary_index=signal_key.upper(),
            primary_value=float(value),
            dominant_issue=cell.get(issue_key) if issue_key else None,
            summary=cell,
        )
    return write_signals(signal_rows, city_id=city_id, domain=domain, source=source)
