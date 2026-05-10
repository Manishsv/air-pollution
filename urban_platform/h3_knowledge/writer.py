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
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _store():
    from urban_platform.h3_knowledge.store import H3KnowledgeStore
    return H3KnowledgeStore.get()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_bucket(iso: str) -> str:
    """Truncate an ISO timestamp to the start of its hour (UTC)."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")
    except Exception:
        return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")


def _day_bucket(iso: str) -> str:
    """Truncate an ISO timestamp to its calendar date (UTC) as YYYY-MM-DD."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
    # Always ensure centroid is populated — derive from H3 cell ID if not supplied
    if centroid_lat is None or centroid_lon is None:
        try:
            import h3 as _h3
            _lat, _lon = _h3.cell_to_latlng(h3_id)
            centroid_lat = float(_lat)
            centroid_lon = float(_lon)
        except Exception:
            pass
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

# ---------------------------------------------------------------------------
# Data quality classification — derived from source name automatically.
# Callers can override per-row via r["data_quality"].
# ---------------------------------------------------------------------------
_SOURCE_DATA_QUALITY: dict[str, str] = {
    # Real monitoring stations
    "cpcb":         "real_station",
    "openaq":       "real_station",
    "iudx":         "real_station",
    # Satellite / remote sensing
    "gee":          "satellite_derived",
    "firms":        "satellite_derived",
    "modis":        "satellite_derived",
    "sentinel":     "satellite_derived",
    "viirs":        "satellite_derived",
    # Numerical weather / reanalysis models
    "openmeteo":    "model_estimate",
    "imd":          "model_estimate",
    "era5":         "model_estimate",
    "pipeline":     "model_estimate",
}

def _infer_data_quality(source: str) -> str:
    """Return data_quality tag for a source string, falling back to 'unknown'."""
    if not source:
        return "unknown"
    src = source.lower()
    # Exact match first, then prefix match
    if src in _SOURCE_DATA_QUALITY:
        return _SOURCE_DATA_QUALITY[src]
    for key, quality in _SOURCE_DATA_QUALITY.items():
        if src.startswith(key):
            return quality
    return "unknown"


def _get_active_driver(domain: str):
    """Return the active driver for a domain, or None if not available."""
    try:
        from urban_platform.sdk.driver_loader import get_active_drivers
        return get_active_drivers().get(domain)
    except Exception:
        return None


def write_signals(
    rows: list[dict[str, Any]],
    *,
    city_id: str,
    domain: str,
    level: int = 1,
    source: str = "pipeline",
    skip_conformance: bool = False,
) -> int:
    """Upsert signal rows.  One row per (h3_id, signal, hour).

    Each dict must have: h3_id, signal, value
    Optional: unit, observed_at (ISO string), source, level, data_quality

    data_quality is automatically inferred from the source name if not
    explicitly provided per-row.  Values: real_station | satellite_derived |
    model_estimate | unknown

    Conformance gate runs automatically unless skip_conformance=True.
    BLOCKING failures (e.g. missing DATA_CONFIDENCE) abort the write and
    return 0. Non-blocking warnings are logged but the write proceeds.
    """
    if not rows:
        return 0

    # ── Conformance gate ──────────────────────────────────────────────────
    if not skip_conformance:
        try:
            from urban_platform.sdk.conformance import validate_and_log
            driver = _get_active_driver(domain)
            result = validate_and_log(rows, driver=driver, domain=domain)
            if not result.ok:
                # Record the conformance failure in the ingest log
                _record_conformance(city_id, domain, ok=False, failures=result.failures)
                return 0
            if result.ok and (result.failures or result.warnings):
                _record_conformance(city_id, domain, ok=True, failures=result.warnings)
        except Exception as exc:
            logger.debug("Conformance gate raised (non-fatal): %s", exc)
    # ─────────────────────────────────────────────────────────────────────
    default_quality = _infer_data_quality(source)
    inserted = 0
    try:
        s = _store()
        now = _now_iso()
        for r in rows:
            h3_id = r.get("h3_id")
            if not h3_id or r.get("value") is None:
                continue
            observed_at = r.get("observed_at", now)
            row_source = r.get("source", source)
            data_quality = r.get("data_quality") or _infer_data_quality(row_source) or default_quality
            s.execute(
                """
                INSERT INTO h3_signals
                    (h3_id, city_id, domain, signal, hour_bucket,
                     value, unit, source, data_quality, level, observed_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (h3_id, city_id, domain, signal, hour_bucket) DO UPDATE SET
                    value        = excluded.value,
                    source       = excluded.source,
                    data_quality = excluded.data_quality,
                    observed_at  = excluded.observed_at,
                    fetched_at   = excluded.fetched_at
                """,
                [
                    h3_id, r.get("city_id", city_id), r.get("domain", domain),
                    r["signal"], _hour_bucket(observed_at),
                    float(r["value"]),
                    r.get("unit"), row_source, data_quality,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (h3_id, city_id, domain, day_bucket) DO UPDATE SET
                assessed_at    = excluded.assessed_at,
                risk_level     = excluded.risk_level,
                primary_index  = excluded.primary_index,
                primary_value  = excluded.primary_value,
                dominant_issue = excluded.dominant_issue,
                summary_json   = excluded.summary_json
            """,
            [
                h3_id, city_id, domain, _day_bucket(now), now,
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
    evidence: list | dict | None = None,
    safety_gates: list | None = None,
    blocked_uses: list | None = None,
) -> None:
    """Insert a decision packet.  Duplicate packet_id is silently ignored.

    Parameters
    ----------
    packet              : Full packet payload (stored as JSON blob for backward compat)
    evidence            : Structured evidence list for the Review Interface (§Evidence Panel)
    safety_gates        : List of safety gate evaluations — each with status/evidence
    blocked_uses        : List of prohibited use descriptions for reviewer acknowledgement
    """
    if not packet_id or not h3_id:
        return
    try:
        _store().execute(
            """
            INSERT INTO h3_packets
                (packet_id, h3_id, city_id, domain, created_at,
                 risk_level, confidence_score, field_verification_required,
                 packet_json, outcome_status,
                 evidence_json, safety_gates_json, blocked_uses_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            ON CONFLICT (packet_id) DO NOTHING
            """,
            [
                packet_id, h3_id, city_id, domain,
                created_at or _now_iso(),
                risk_level,
                float(confidence_score) if confidence_score is not None else None,
                1 if field_verification_required else 0,
                _safe_json(packet),
                _safe_json(evidence) if evidence is not None else None,
                _safe_json(safety_gates) if safety_gates is not None else None,
                _safe_json(blocked_uses) if blocked_uses is not None else None,
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
    hypothesis_chain: list[dict] | None = None,
    recommended_actions: list | None = None,
    uncertainty_notes: list | None = None,
    created_at: str | None = None,
    priority_tier: str | None = None,
    # Legacy alias — accepted for backward compat, mapped to hypothesis_chain
    causal_chain: list[dict] | None = None,
) -> str:
    insight_id = str(uuid.uuid4())
    resolved_chain = hypothesis_chain or causal_chain

    # Priority tier: use explicit value from agent if provided and valid,
    # otherwise fall back to confidence-based derivation.
    # The agent sets priority_tier based on RISK SEVERITY; confidence reflects
    # its analytical certainty. These are orthogonal — a high-severity risk
    # with sparse data gets priority=high, confidence=0.5.
    _VALID_TIERS = {"critical", "high", "medium", "low"}
    if priority_tier and priority_tier in _VALID_TIERS:
        tier = priority_tier
    elif confidence is not None:
        if confidence >= 0.75:
            tier = "high"
        elif confidence >= 0.45:
            tier = "medium"
        else:
            tier = "low"
    else:
        tier = "medium"
    try:
        _store().execute(
            """
            INSERT INTO h3_insights
                (insight_id, h3_id, city_id, agent_type, created_at,
                 domains_involved, finding, confidence, priority_tier,
                 hypothesis_chain_json,
                 recommended_actions_json, uncertainty_notes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                insight_id, h3_id, city_id, agent_type,
                created_at or _now_iso(),
                ",".join(domains_involved) if domains_involved else None,
                finding,
                float(confidence) if confidence is not None else None,
                tier,
                _safe_json(resolved_chain),
                _safe_json(recommended_actions),
                _safe_json(uncertainty_notes),
            ],
        )
    except Exception as exc:
        logger.warning("write_insight failed: %s", exc)
    return insight_id


def write_city_pattern(
    *,
    city_id: str,
    lookback_hours: int,
    n_insights: int,
    theme_count: int,
    summary: dict,
    pattern_id: str | None = None,
    created_at: str | None = None,
) -> str:
    """Write a City Pattern Agent synthesis result to city_patterns.

    Each call always inserts a new row — city patterns are historical records,
    not upserts.  Returns the pattern_id.

    Parameters
    ----------
    city_id        : City partition key
    lookback_hours : Time window of insights analysed
    n_insights     : Number of h3_expert insights included
    theme_count    : Number of themes identified by the agent
    summary        : Full JSON output from the City Pattern Agent
    pattern_id     : Optional UUID; generated if not supplied
    created_at     : Optional ISO timestamp; system UTC if not supplied
    """
    pid = pattern_id or str(uuid.uuid4())
    try:
        _store().execute(
            """
            INSERT INTO city_patterns
                (pattern_id, city_id, created_at,
                 lookback_hours, n_insights, theme_count, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [pid, city_id, created_at or _now_iso(),
             lookback_hours, n_insights, theme_count,
             _safe_json(summary)],
        )
        logger.debug(
            "write_city_pattern: %s themes for %s (n_insights=%d)",
            theme_count, city_id, n_insights,
        )
    except Exception as exc:
        logger.warning("write_city_pattern failed: %s", exc)
    return pid


def close_insight(
    *,
    insight_id: str,
    outcome_status: str,
    closed_by: str,
) -> None:
    """Record an officer's closure decision on an insight.

    outcome_status : confirmed | refuted | unverifiable
    closed_by      : Non-empty reviewer identity string (email, officer ID, etc.)
                     An empty or missing closed_by is rejected — anonymous closure
                     is a spec violation (REVIEW_CONTRACT §Close Operation Requirements).
    """
    if not closed_by or not closed_by.strip():
        raise ValueError(
            "close_insight: closed_by must be a non-empty reviewer identity string. "
            "Anonymous closure is prohibited by the Review Contract."
        )
    _VALID_OUTCOMES = {"confirmed", "refuted", "unverifiable"}
    if outcome_status not in _VALID_OUTCOMES:
        raise ValueError(
            f"close_insight: outcome_status must be one of {sorted(_VALID_OUTCOMES)}, "
            f"got {outcome_status!r}."
        )
    try:
        _store().execute(
            """
            UPDATE h3_insights
               SET outcome_status = ?,
                   closed_by      = ?,
                   closed_at      = ?
             WHERE insight_id = ?
               AND outcome_status = 'open'
            """,
            [outcome_status, closed_by.strip(), _now_iso(), insight_id],
        )
    except Exception as exc:
        logger.warning("close_insight failed: %s", exc)


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

def _record_conformance(
    city_id: str,
    domain: str,
    *,
    ok: bool,
    failures: list[str],
) -> None:
    """Persist conformance result to h3_ingest_log (best-effort)."""
    try:
        failures_json = json.dumps(failures) if failures else None
        _store().execute(
            """
            INSERT INTO h3_ingest_log
                (city_id, domain, last_ingested_at, rows_written, status,
                 conformance_ok, conformance_failures)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT (city_id, domain) DO UPDATE SET
                conformance_ok       = excluded.conformance_ok,
                conformance_failures = excluded.conformance_failures
            """,
            [city_id, domain, _now_iso(),
             "conformance_fail" if not ok else "ok",
             int(ok), failures_json],
        )
    except Exception as exc:
        logger.debug("_record_conformance failed (non-fatal): %s", exc)


def record_ingest(
    *,
    city_id: str,
    domain: str,
    rows_written: int = 0,
    status: str = "ok",
    error_msg: str | None = None,
    conformance_ok: bool | None = None,
    conformance_failures: list[str] | None = None,
) -> None:
    try:
        cf_json = json.dumps(conformance_failures) if conformance_failures else None
        cf_int = int(conformance_ok) if conformance_ok is not None else None
        _store().execute(
            """
            INSERT INTO h3_ingest_log
                (city_id, domain, last_ingested_at, rows_written, status, error_msg,
                 conformance_ok, conformance_failures)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (city_id, domain) DO UPDATE SET
                last_ingested_at     = excluded.last_ingested_at,
                rows_written         = excluded.rows_written,
                status               = excluded.status,
                error_msg            = excluded.error_msg,
                conformance_ok       = COALESCE(excluded.conformance_ok, conformance_ok),
                conformance_failures = COALESCE(excluded.conformance_failures, conformance_failures)
            """,
            [city_id, domain, _now_iso(), rows_written, status, error_msg,
             cf_int, cf_json],
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
    """Write signals + assessments + coverage uncertainty for a batch of cell dicts.

    Designed to be called from the batch ingestor, not the dashboard.
    Returns total signal rows written.

    Analysis gate
    -------------
    Analysis requests are only queued when:
      1. DATA_CONFIDENCE >= 0.6  (cell is data-ready — IDW result is predictive)
      2. AND the risk level has changed since the previous assessment, or there
         is no prior assessment for this cell.

    When DATA_CONFIDENCE < 0.6 the cell is flagged as a siting candidate instead
    (written to h3_siting_candidates via data_quality.flag_low_confidence_cell).
    This keeps the analysis queue focused on cells where the data is reliable.
    """
    from urban_platform.h3_knowledge.coverage import coverage_signals, distance_to_confidence, DOMAIN_DEFAULT_CONFIDENCE

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
        # Coverage: nearest_obs_km if available in cell dict, else domain default
        cov_rows = coverage_signals(h3_id, cell.get("nearest_obs_km"), domain)
        signal_rows.extend(cov_rows)

        # Derive data_confidence for the gate decision
        nearest_km = cell.get("nearest_obs_km")
        if nearest_km is not None:
            data_confidence = distance_to_confidence(nearest_km)
        else:
            data_confidence = DOMAIN_DEFAULT_CONFIDENCE.get(domain, 0.5)

        write_assessment(
            h3_id=h3_id, city_id=city_id, domain=domain,
            risk_level=risk,
            primary_index=signal_key.upper(),
            primary_value=float(value),
            dominant_issue=cell.get(issue_key) if issue_key else None,
            summary=cell,
        )

        # ── Analysis gate ──────────────────────────────────────────────────────
        # Only queue an analysis request when data is reliable AND risk has changed.
        # Low-confidence cells are flagged as siting candidates instead.
        _apply_analysis_gate(
            h3_id=h3_id,
            city_id=city_id,
            domain=domain,
            new_risk_level=risk,
            data_confidence=data_confidence,
            centroid_lat=cell.get("centroid_lat"),
            centroid_lng=cell.get("centroid_lon"),
        )

    return write_signals(signal_rows, city_id=city_id, domain=domain, source=source)


def _apply_analysis_gate(
    *,
    h3_id: str,
    city_id: str,
    domain: str,
    new_risk_level: str,
    data_confidence: float,
    centroid_lat: float | None = None,
    centroid_lng: float | None = None,
) -> None:
    """Decide whether to queue analysis or flag for siting.

    Gate logic:
      - data_confidence >= 0.6  AND  risk level changed (or first assessment)
        → queue an analysis request via submit_analysis_request
      - data_confidence < 0.6
        → flag as siting candidate via data_quality.flag_low_confidence_cell
        (no analysis request — IDW values are non-predictive at this range)

    Degrades gracefully: if prev_risk_level lookup fails, the gate treats the
    cell as first-time (no prior assessment) and queues analysis if confidence
    is sufficient.
    """
    _CONFIDENCE_GATE = 0.6

    if data_confidence >= _CONFIDENCE_GATE:
        # Look up the most-recent risk level for this cell+domain
        prev_risk_level: str | None = None
        try:
            s = _store()
            row = s.fetchone(
                """
                SELECT risk_level FROM h3_assessments
                WHERE h3_id = ? AND city_id = ? AND domain = ?
                ORDER BY day_bucket DESC
                LIMIT 1
                """,
                [h3_id, city_id, domain],
            )
            if row:
                prev_risk_level = row[0]
        except Exception as exc:
            logger.debug("_apply_analysis_gate prev_risk lookup failed: %s", exc)

        if prev_risk_level is None or prev_risk_level != new_risk_level:
            # First assessment or risk band changed — queue for analysis
            try:
                ok, msg = submit_analysis_request(h3_id, city_id)
                if ok:
                    logger.debug(
                        "Analysis queued [%s/%s/%s]: %s → %s",
                        city_id, domain, h3_id[:8], prev_risk_level, new_risk_level,
                    )
                else:
                    # Already queued / cooldown — not an error
                    logger.debug("Analysis not queued [%s/%s/%s]: %s", city_id, domain, h3_id[:8], msg)
            except Exception as exc:
                logger.debug("submit_analysis_request failed: %s", exc)
    else:
        # Low confidence — flag for sensor siting instead of queuing analysis
        try:
            from urban_platform.h3_knowledge.data_quality import flag_low_confidence_cell
            flag_low_confidence_cell(
                h3_id=h3_id,
                city_id=city_id,
                domain=domain,
                data_confidence=data_confidence,
                centroid_lat=centroid_lat,
                centroid_lng=centroid_lng,
            )
        except Exception as exc:
            logger.debug("flag_low_confidence_cell failed: %s", exc)


# ---------------------------------------------------------------------------
# Sensor siting — batch compute and persist
# ---------------------------------------------------------------------------

def compute_and_store_siting(
    city_id: str,
    domain: str,
    *,
    period_days: int = 90,
    top_n: int = 50,
) -> int:
    """Compute siting candidates from the last `period_days` of data and persist them.

    Results are written to h3_siting_candidates (UNIQUE on city+domain+h3+period_start,
    so re-running the same period is idempotent).  A watermark in h3_siting_log records
    when the last batch ran so the scheduler can enforce the monthly/quarterly cadence.

    Returns the number of candidates written.
    """
    from datetime import datetime, timezone, timedelta
    from urban_platform.h3_knowledge.coverage import DOMAIN_DEFAULT_CONFIDENCE

    now = datetime.now(timezone.utc)
    period_end   = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    period_start = (now - timedelta(days=period_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    period_start_date = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")

    s = _store()
    default_conf = DOMAIN_DEFAULT_CONFIDENCE.get(domain, 0.5)

    # ── Risk scores over the full period ─────────────────────────────────────
    risk_df = s.fetchdf(
        f"""
        SELECT
            a.h3_id,
            AVG(CASE a.risk_level
                    WHEN 'severe'   THEN 1.00
                    WHEN 'high'     THEN 0.75
                    WHEN 'moderate' THEN 0.40
                    WHEN 'good'     THEN 0.10
                    ELSE 0.25
                END) AS avg_risk_score,
            COUNT(*) AS assessment_count
        FROM h3_assessments a
        WHERE a.city_id   = ?
          AND a.domain    = ?
          AND a.day_bucket >= ?
        GROUP BY a.h3_id
        """,
        [city_id, domain, period_start_date],
    )

    if risk_df.empty:
        _record_siting_log(city_id, domain, period_days, 0, "partial",
                           "no assessments in period")
        return 0

    # ── Latest DATA_CONFIDENCE + NEAREST_OBS_KM signals ──────────────────────
    conf_df = s.fetchdf(
        """
        SELECT
            h3_id,
            MAX(CASE signal WHEN 'DATA_CONFIDENCE' THEN value END) AS data_confidence,
            MAX(CASE signal WHEN 'NEAREST_OBS_KM'  THEN value END) AS nearest_obs_km
        FROM h3_signals
        WHERE city_id = ?
          AND domain  = ?
          AND signal IN ('DATA_CONFIDENCE', 'NEAREST_OBS_KM')
        GROUP BY h3_id
        """,
        [city_id, domain],
    )

    # ── Cell coordinates ──────────────────────────────────────────────────────
    meta_df = s.fetchdf(
        "SELECT h3_id, centroid_lat, centroid_lon FROM h3_metadata WHERE city_id = ?",
        [city_id],
    )

    # ── Join & score ──────────────────────────────────────────────────────────
    import pandas as pd
    df = risk_df.merge(meta_df, on="h3_id", how="left")
    if not conf_df.empty:
        df = df.merge(conf_df, on="h3_id", how="left")
    else:
        df["data_confidence"] = None
        df["nearest_obs_km"]  = None

    df["data_confidence"] = df["data_confidence"].fillna(default_conf)
    df["coverage_gap"]    = (1.0 - df["data_confidence"]).clip(0.0, 1.0)
    df["siting_score"]    = (df["avg_risk_score"] * df["coverage_gap"]).round(4)

    df = (df
          .sort_values("siting_score", ascending=False)
          .head(top_n)
          .reset_index(drop=True))
    df["rank"] = df.index + 1

    # ── Persist ───────────────────────────────────────────────────────────────
    computed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        (
            city_id, domain, row["h3_id"], int(row["rank"]),
            computed_at, period_start, period_end, period_days,
            _safe(row.get("avg_risk_score")),
            _safe(row.get("data_confidence")),
            _safe(row.get("nearest_obs_km")),
            _safe(row.get("coverage_gap")),
            _safe(row.get("siting_score")),
            _safe(row.get("centroid_lat")),
            _safe(row.get("centroid_lon")),
            int(row.get("assessment_count", 0)),
        )
        for _, row in df.iterrows()
    ]

    sql = """
        INSERT OR REPLACE INTO h3_siting_candidates
            (city_id, domain, h3_id, rank, computed_at,
             period_start, period_end, period_days,
             avg_risk_score, data_confidence, nearest_obs_km,
             coverage_gap, siting_score,
             centroid_lat, centroid_lon, assessment_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    s.write_batch(sql, rows)

    _record_siting_log(city_id, domain, period_days, len(rows), "ok")
    logger.info(
        "[siting] %s/%s — %d candidates computed over %dd  "
        "(top score: %.3f)",
        city_id, domain, len(rows), period_days,
        df["siting_score"].max() if not df.empty else 0,
    )
    return len(rows)


def _safe(v):
    """Return float or None, guarding against NaN/pandas NA."""
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


def _record_siting_log(
    city_id: str, domain: str, period_days: int,
    candidates: int, status: str, error_msg: str | None = None,
) -> None:
    s = _store()
    s.execute(
        """
        INSERT OR REPLACE INTO h3_siting_log
            (city_id, domain, period_days, candidates, status, error_msg)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [city_id, domain, period_days, candidates, status, error_msg],
    )


# ---------------------------------------------------------------------------
# Async analysis request queue
# ---------------------------------------------------------------------------

def submit_analysis_request(h3_id: str, city_id: str) -> tuple[bool, str]:
    """Queue a cell for async analysis by the H3 Expert Agent.

    Returns (ok, message).  Rejected if:
      - A request is already pending/running for this cell.
      - A completed request exists within ANALYSIS_COOLDOWN_HOURS.
    """
    from urban_platform.h3_knowledge.schema import ANALYSIS_COOLDOWN_HOURS

    s = _store()

    # 1 — Check for active (pending/running) request
    active = s.fetchone(
        """
        SELECT request_id, status FROM h3_analysis_requests
        WHERE h3_id = ? AND city_id = ?
          AND status IN ('pending', 'running')
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        [h3_id, city_id],
    )
    if active:
        return False, f"Analysis already {active[1]} — check back in a few minutes."

    # 2 — Enforce cooldown after last completion
    recent = s.fetchone(
        f"""
        SELECT completed_at FROM h3_analysis_requests
        WHERE h3_id = ? AND city_id = ?
          AND status = 'completed'
          AND completed_at >= datetime('now', '-{ANALYSIS_COOLDOWN_HOURS} hours')
        ORDER BY completed_at DESC
        LIMIT 1
        """,
        [h3_id, city_id],
    )
    if recent:
        return False, (
            f"Analysis completed recently. "
            f"A new request can be submitted after the {ANALYSIS_COOLDOWN_HOURS}-hour cooldown."
        )

    # 3 — Insert
    request_id = str(uuid.uuid4())
    try:
        s.execute(
            """
            INSERT INTO h3_analysis_requests
                (request_id, h3_id, city_id, requested_at, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            [request_id, h3_id, city_id, _now_iso()],
        )
        logger.info("Analysis request queued: %s for %s/%s", request_id[:8], city_id, h3_id)
        return True, "Analysis queued — results appear on the next scheduler sweep (within 15 min)."
    except Exception as exc:
        logger.warning("submit_analysis_request failed: %s", exc)
        return False, f"Could not queue request: {exc}"


def update_request_status(
    request_id: str,
    status: str,
    *,
    insight_id: str | None = None,
    error_msg: str | None = None,
) -> None:
    """Update an analysis request status (pending → running → completed/failed)."""
    s = _store()
    now = _now_iso()
    if status == "running":
        s.execute(
            "UPDATE h3_analysis_requests SET status = ?, started_at = ? WHERE request_id = ?",
            [status, now, request_id],
        )
    else:
        s.execute(
            """
            UPDATE h3_analysis_requests
            SET status = ?, completed_at = ?, insight_id = ?, error_msg = ?
            WHERE request_id = ?
            """,
            [status, now, insight_id, error_msg, request_id],
        )
