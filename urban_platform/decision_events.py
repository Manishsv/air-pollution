"""
AIR Climate Suite — Decision Object emitter (GCP-aligned).

The decision packets produced by the air/heat/flood pipelines already conform
to urban_decision_packet_core.v1.schema.json. This module:

  1. Extracts the GCP decision trace (rulesetId, facts, outcome) from each packet
  2. POSTs to DIGIT3 Governance service to obtain a decisionReceipt
     (stub: writes locally when DIGIT3_GOVERNANCE_URL is not set)
  3. Attaches the receipt to packet["audit_context"]["governance_receipt"]
  4. Emits the complete, receipt-stamped packet to the event transport

AIR only ever emits "proposed" status. Ward routing, workflow assignment,
notification, and lifecycle (proposed → assigned → resolved) are downstream.

GCP governance receipt schema (from AIROS_DIGIT3_INFRASTRUCTURE_SPEC §4.7.3):
  receiptId, entityId, rulesetId, rulesetVersion,
  factsHash, outcomeHash, chainHash, issuedAt, contestationUrl

Transport
─────────
  DIGIT3_GOVERNANCE_URL set → POST /governance/v1/decisions (real GCP receipt)
  AIRNET_EVENTS_URL set     → POST /airnet/v1/events (AIRNet event bus)
  fallback                  → append to data/events/decisions.jsonl
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Ruleset IDs — must match rulesets published during AIROS provisioning
_RULESET = {
    "air":   "airos_air_decisions_v1",
    "heat":  "airos_heat_decisions_v1",
    "flood": "airos_flood_decisions_v1",
}
_RULESET_VERSION = 1
_ENTITY_TYPE = "airos.decision"

# Thresholds — decisions are only emitted for packets above these
_AIR_ALERT_CATEGORIES = {"poor", "very_poor", "severe"}
_HEAT_RISK_THRESHOLD  = 0.65
_FLOOD_RISK_THRESHOLD = 0.55


# ── GCP governance receipt ────────────────────────────────────────────────────

def _sha256(obj: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _get_governance_receipt(
    domain: str,
    entity_id: str,
    facts: dict,
    outcome: dict,
    city_id: str,
) -> dict:
    """
    Obtain a GCP governance receipt.

    When DIGIT3_GOVERNANCE_URL is set, POSTs to the Governance service and
    returns its receipt. Otherwise builds a local stub receipt for audit trail.
    """
    ruleset_id = _RULESET[domain]
    payload = {
        "rulesetId":      ruleset_id,
        "rulesetVersion": _RULESET_VERSION,
        "entityType":     _ENTITY_TYPE,
        "entityId":       entity_id,
        "facts":          facts,
        "outcome":        outcome,
        "tenantId":       city_id,
    }

    gov_url = os.environ.get("DIGIT3_GOVERNANCE_URL", "").strip()
    if gov_url:
        try:
            import requests
            resp = requests.post(
                f"{gov_url}/governance/v1/decisions",
                json=payload,
                headers={"X-Tenant-ID": city_id},
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Governance service unavailable (%s) — using stub receipt", exc)

    # Stub receipt — same shape as DIGIT3 response
    now = datetime.now(timezone.utc).isoformat()
    facts_hash   = _sha256(facts)
    outcome_hash = _sha256(outcome)
    return {
        "receiptId":       f"stub-{uuid.uuid4().hex[:8]}",
        "entityId":        entity_id,
        "rulesetId":       ruleset_id,
        "rulesetVersion":  _RULESET_VERSION,
        "factsHash":       facts_hash,
        "outcomeHash":     outcome_hash,
        "chainHash":       _sha256({"factsHash": facts_hash, "outcomeHash": outcome_hash}),
        "issuedAt":        now,
        "contestationUrl": f"/governance/v1/appeals?entityId={entity_id}",
        "_stub":           True,
    }


# ── Transport ─────────────────────────────────────────────────────────────────

def _emit(domain: str, city_id: str, packet: dict) -> None:
    """Emit the receipt-stamped decision packet to the configured transport."""
    event = {
        "event_id":   str(uuid.uuid4()),
        "event_type": "decision_proposed",
        "domain":     domain,
        "city_id":    city_id,
        "ward_id":    None,        # populated by Boundary service downstream
        "status":     "proposed",  # AIR only ever emits "proposed"
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "decision_packet": packet,
    }

    airnet_url = os.environ.get("AIRNET_EVENTS_URL", "").strip()
    if airnet_url:
        try:
            import requests
            requests.post(airnet_url, json=event, timeout=5).raise_for_status()
            logger.info("Decision emitted to AIRNet: %s", packet.get("packet_id"))
            return
        except Exception as exc:
            logger.warning("AIRNet emit failed (%s) — falling back to local log", exc)

    log_path = Path(os.environ.get("DECISION_LOG_PATH", "data/events/decisions.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    logger.info("Decision logged: %s [%s]", packet.get("packet_id"), domain)


# ── Per-domain emitters ───────────────────────────────────────────────────────

def emit_air_decisions(packets: list[dict], city_id: str) -> int:
    """Emit GCP-receipted Decision Objects for air quality packets above threshold."""
    emitted = 0
    for packet in packets:
        aa  = packet.get("aqi_assessment") or {}
        cat = aa.get("aqi_category", "")
        if cat not in _AIR_ALERT_CATEGORIES:
            continue

        entity_id = f"AIROS-{city_id.upper()[:3]}-{packet.get('packet_id', uuid.uuid4().hex)[:12]}"
        facts = {
            "aqi_category":  cat,
            "aqi_score":     aa.get("aqi_score"),
            "h3_id":         packet.get("h3_id"),
            "timestamp":     packet.get("timestamp"),
            "cell_count":    1,
        }
        outcome = {
            "decision_id":   entity_id,
            "urgency":       "within_4h" if cat == "poor" else "immediate",
            "confidence":    (packet.get("confidence") or {}).get("driver_confidence", "medium"),
        }

        receipt = _get_governance_receipt("air", entity_id, facts, outcome, city_id)
        packet.setdefault("audit_context", {})["governance_receipt"] = receipt

        _emit("air", city_id, packet)
        emitted += 1
    return emitted


def emit_heat_decisions(candidates: list[dict], city_id: str) -> int:
    """Emit GCP-receipted Decision Objects for heat intervention candidates above threshold."""
    emitted = 0
    for candidate in candidates:
        score = candidate.get("risk_score") or 0.0
        if score < _HEAT_RISK_THRESHOLD:
            continue

        entity_id = f"AIROS-{city_id.upper()[:3]}-{candidate.get('h3_id', uuid.uuid4().hex)[:12]}"
        facts = {
            "risk_score":    score,
            "uhi_intensity": candidate.get("uhi_intensity"),
            "green_deficit": candidate.get("green_deficit"),
            "h3_id":         candidate.get("h3_id"),
        }
        outcome = {
            "decision_id":          entity_id,
            "urgency":              "within_24h",
            "suggested_interventions": candidate.get("suggested_interventions", []),
        }

        receipt = _get_governance_receipt("heat", entity_id, facts, outcome, city_id)
        candidate.setdefault("audit_context", {})["governance_receipt"] = receipt

        _emit("heat", city_id, candidate)
        emitted += 1
    return emitted


def emit_flood_decisions(packets: list[dict], city_id: str) -> int:
    """Emit GCP-receipted Decision Objects for flood packets above threshold."""
    emitted = 0
    for packet in packets:
        fra   = packet.get("flood_risk_assessment") or {}
        score = fra.get("flood_risk_score") or 0.0
        if score < _FLOOD_RISK_THRESHOLD:
            continue

        entity_id = f"AIROS-{city_id.upper()[:3]}-{packet.get('packet_id', uuid.uuid4().hex)[:12]}"
        facts = {
            "flood_risk_score": score,
            "risk_level":       fra.get("risk_level"),
            "rainfall_mm_3h":   fra.get("rainfall_accumulation_3h_mm"),
            "h3_id":            packet.get("h3_id"),
            "timestamp":        packet.get("timestamp"),
        }
        outcome = {
            "decision_id": entity_id,
            "urgency":     "immediate" if fra.get("risk_level") == "high" else "within_4h",
            "confidence":  (packet.get("confidence") or {}).get("driver_confidence", "medium"),
        }

        receipt = _get_governance_receipt("flood", entity_id, facts, outcome, city_id)
        packet.setdefault("audit_context", {})["governance_receipt"] = receipt

        _emit("flood", city_id, packet)
        emitted += 1
    return emitted
