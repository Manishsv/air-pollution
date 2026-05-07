"""
AIR Climate Suite — Decision Object emitter.

AIR's responsibility ends here: build a Decision Object from a decision
packet and emit it. Routing, workflow, notification, and lifecycle
management are handled downstream (AIRNet, DIGIT3 Workflow).

Decision Object schema
──────────────────────
{
    "decision_id":      str (uuid4),
    "domain":           "air" | "heat" | "flood",
    "city_id":          str,
    "ward_id":          str | null,   # populated by Boundary service when available
    "h3_cell":          str,
    "proposed_action":  str,          # human-readable action proposal
    "severity":         "low" | "moderate" | "high" | "critical",
    "score":            float,        # 0–1 domain risk score
    "status":           "proposed",   # AIR only ever emits "proposed"
    "evidence":         dict,         # full decision packet
    "emitted_at":       ISO8601 str,
    "valid_until":      ISO8601 str,  # freshness window (default 1h)
    "source_app":       "air_aq" | "air_heat" | "air_flood",
}

Transport
─────────
Default: append-only JSONL file at data/events/decisions.jsonl
Future:  swap _transport() to POST to AIRNet /airnet/v1/events
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Thresholds (AIR decides what crosses into a Decision) ───────────────────

_AIR_ALERT_CATEGORIES  = {"poor", "very_poor", "severe"}
_HEAT_RISK_THRESHOLD   = 0.65
_FLOOD_RISK_THRESHOLD  = 0.55

# ── Severity mapping ─────────────────────────────────────────────────────────

def _air_severity(aqi_category: str) -> str:
    return {
        "poor":      "moderate",
        "very_poor": "high",
        "severe":    "critical",
    }.get(aqi_category, "low")


def _score_severity(score: float) -> str:
    if score >= 0.85: return "critical"
    if score >= 0.70: return "high"
    if score >= 0.55: return "moderate"
    return "low"


# ── Transport ────────────────────────────────────────────────────────────────

def _transport(decision: dict) -> None:
    """
    Emit the Decision Object.

    Current: append to local JSONL event log.
    Future:  POST to AIRNet /airnet/v1/events — swap here, callers unchanged.
    """
    airnet_url = os.environ.get("AIRNET_EVENTS_URL", "").strip()

    if airnet_url:
        try:
            import requests
            resp = requests.post(
                airnet_url,
                json={"event_type": "decision_proposed", "payload": decision},
                timeout=5,
            )
            resp.raise_for_status()
            logger.info("Decision emitted to AIRNet: %s", decision["decision_id"])
            return
        except Exception as exc:
            logger.warning("AIRNet emit failed (%s) — falling back to local log", exc)

    # Local JSONL fallback
    log_path = Path(os.environ.get("DECISION_LOG_PATH", "data/events/decisions.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(decision) + "\n")
    logger.info("Decision logged: %s [%s/%s]",
                decision["decision_id"], decision["domain"], decision["severity"])


# ── Decision builder ─────────────────────────────────────────────────────────

def _build_decision(
    domain: str,
    source_app: str,
    city_id: str,
    h3_cell: str,
    severity: str,
    score: float,
    proposed_action: str,
    evidence: dict,
    valid_hours: int = 1,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "decision_id":    str(uuid.uuid4()),
        "domain":         domain,
        "source_app":     source_app,
        "city_id":        city_id,
        "ward_id":        None,   # populated by Boundary service downstream
        "h3_cell":        h3_cell,
        "proposed_action": proposed_action,
        "severity":       severity,
        "score":          round(score, 4),
        "status":         "proposed",
        "evidence":       evidence,
        "emitted_at":     now.isoformat(),
        "valid_until":    (now + timedelta(hours=valid_hours)).isoformat(),
    }


# ── Public emitters ──────────────────────────────────────────────────────────

def emit_air_decisions(packets: list[dict], city_id: str) -> int:
    """
    Emit a Decision Object for each air quality packet above threshold.
    Returns the number of decisions emitted.
    """
    emitted = 0
    for packet in packets:
        aa  = packet.get("aqi_assessment") or {}
        cat = aa.get("aqi_category", "")
        if cat not in _AIR_ALERT_CATEGORIES:
            continue
        score    = aa.get("aqi_score") or 0.0
        h3_cell  = packet.get("h3_id", "")
        severity = _air_severity(cat)
        action   = (
            f"Investigate air quality violation in {city_id} "
            f"(H3: {h3_cell[:12]}…) — AQI category: {cat.replace('_', ' ')}"
        )
        decision = _build_decision(
            domain="air", source_app="air_aq",
            city_id=city_id, h3_cell=h3_cell,
            severity=severity, score=score,
            proposed_action=action, evidence=packet,
        )
        _transport(decision)
        emitted += 1
    return emitted


def emit_heat_decisions(candidates: list[dict], city_id: str) -> int:
    """
    Emit a Decision Object for each heat intervention candidate above threshold.
    Returns the number of decisions emitted.
    """
    emitted = 0
    for candidate in candidates:
        score = candidate.get("risk_score") or 0.0
        if score < _HEAT_RISK_THRESHOLD:
            continue
        h3_cell  = candidate.get("h3_id", "")
        severity = _score_severity(score)
        interventions = ", ".join(candidate.get("suggested_interventions", []))
        action = (
            f"Urban heat intervention required in {city_id} "
            f"(H3: {h3_cell[:12]}…) — risk score {score:.2f}. "
            f"Suggested: {interventions or 'review required'}"
        )
        decision = _build_decision(
            domain="heat", source_app="air_heat",
            city_id=city_id, h3_cell=h3_cell,
            severity=severity, score=score,
            proposed_action=action, evidence=candidate,
        )
        _transport(decision)
        emitted += 1
    return emitted


def emit_flood_decisions(packets: list[dict], city_id: str) -> int:
    """
    Emit a Decision Object for each flood packet above threshold.
    Returns the number of decisions emitted.
    """
    emitted = 0
    for packet in packets:
        fra   = packet.get("flood_risk_assessment") or {}
        score = fra.get("flood_risk_score") or 0.0
        if score < _FLOOD_RISK_THRESHOLD:
            continue
        h3_cell  = packet.get("h3_id", "")
        level    = fra.get("risk_level", "")
        severity = _score_severity(score)
        action   = (
            f"Flood risk response required in {city_id} "
            f"(H3: {h3_cell[:12]}…) — {level} risk, score {score:.2f}"
        )
        decision = _build_decision(
            domain="flood", source_app="air_flood",
            city_id=city_id, h3_cell=h3_cell,
            severity=severity, score=score,
            proposed_action=action, evidence=packet,
        )
        _transport(decision)
        emitted += 1
    return emitted
