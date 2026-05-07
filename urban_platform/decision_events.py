"""
AIR Climate Suite — GCP Decision Object emitter.

Produces Decision Objects that conform to:
  Digital Statecraft GCP decision-object.schema.json

Required fields:
  decision_id, case_id, timestamp, jurisdiction, service_domain,
  decision_authority, rule_reference, evidence_snapshot, inference,
  decision_outcome, reasoning_trace, contestation, audit

AIR always emits outcome_type "flagged" — downstream systems (DIGIT3
Workflow, AIRNet) decide routing, assignment, and lifecycle.

Transport (in priority order):
  AIRNET_EVENTS_URL set → POST to AIRNet /airnet/v1/events
  fallback              → append to data/events/decisions.jsonl
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

# ── Constants ────────────────────────────────────────────────────────────────

_SYSTEM_VERSION   = "air-climate-suite-v0.1"
_METHOD_AUTHORITY = "AIR Climate Suite — Anthropic / Urban Platform"

_SERVICE_CODES = {
    "air":   "air_quality_monitoring",
    "heat":  "urban_heat_risk",
    "flood": "flood_risk_monitoring",
}

_RULE_IDS = {
    "air":   "airos_air_decisions_v1",
    "heat":  "airos_heat_decisions_v1",
    "flood": "airos_flood_decisions_v1",
}

# Packets below these thresholds are not emitted
_AIR_ALERT_CATEGORIES = {"poor", "very_poor", "severe"}
_HEAT_RISK_THRESHOLD  = 0.65
_FLOOD_RISK_THRESHOLD = 0.55


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_source(source_name: str, source_type: str, data: dict) -> dict:
    return {
        "source_ref":     source_name,
        "source_type":    source_type,
        "record_version": "1",
        "as_of":          _now(),
        "record_hash":    _sha256(data),
    }


# ── GCP Decision Object builder ───────────────────────────────────────────────

def _build_decision_object(
    domain: str,
    city_id: str,
    h3_cell: str,
    case_id: str,
    rule_id: str,
    key_facts: list,
    structured_reasoning: list[dict],
    outcome_code: str,
    outcome_value: str,
    evidence_sources: list[dict],
    evidence_data: dict,
) -> dict:
    now = _now()
    decision_id   = str(uuid.uuid4())
    service_code  = _SERVICE_CODES[domain]
    snapshot_id   = str(uuid.uuid4())
    evidence_hash = _sha256(evidence_data)

    decision = {
        "decision_id": decision_id,
        "case_id":     case_id,
        "timestamp":   now,

        "jurisdiction": {
            "boundary_type":         "h3_cell",      # upgraded to "ward" when Boundary service available
            "boundary_code":         h3_cell,
            "boundary_registry_ref": f"airos://boundary/{city_id}/h3/{h3_cell}",
            "as_of":                 now,
        },

        "service_domain": {
            "service_code":        service_code,
            "service_registry_ref": f"airos://services/{service_code}",
            "service_version":     "1",
            "as_of":               now,
        },

        "decision_authority": {
            "authority_id":       f"airos-{domain}-engine",
            "responsible_entity": "AIR Climate Suite",
            "decision_mode":      "ai_assisted_system",
            "authority_version":  "1",
            "as_of":              now,
        },

        "rule_reference": {
            "rule_id":             rule_id,
            "rule_version":        "1",
            "publication_reference": f"airos://governance/rulesets/{rule_id}",
            "effective_from":      "2026-01-01T00:00:00+00:00",
        },

        "evidence_snapshot": {
            "snapshot_id":      snapshot_id,
            "timestamp":        now,
            "evidence_sources": evidence_sources,
            "evidence_hash":    evidence_hash,
        },

        "inference": {
            "inference_method_id":      f"{rule_id}_threshold_engine",
            "inference_method_version": "1",
            "execution_mode":           "rule_based",
            "publication_reference":    f"airos://inference/{rule_id}",
            "method_authority":         _METHOD_AUTHORITY,
            "as_of":                    now,
        },

        "decision_outcome": {
            "outcome_type":  "flagged",   # AIR flags; downstream routes/assigns
            "outcome_code":  outcome_code,
            "outcome_value": outcome_value,
        },

        "reasoning_trace": {
            "rule_applied":       rule_id,
            "key_facts_used":     key_facts,
            "inference_applied":  "Threshold-based rule evaluation with IDW spatial interpolation",
            "structured_reasoning": structured_reasoning,
        },

        "contestation": {
            "appellate_authority":    "DIGIT3 Governance Service",
            "contestation_deadline":  None,
            "contestation_channel":   f"airos://governance/v1/appeals?case_id={case_id}",
        },

        "audit": {
            "system_version": _SYSTEM_VERSION,
            "decision_hash":  "",           # filled after object is complete
            "log_reference":  f"airos://events/decisions/{decision_id}",
        },
    }

    # Hash the complete decision (excluding audit.decision_hash itself)
    decision["audit"]["decision_hash"] = _sha256({
        k: v for k, v in decision.items() if k != "audit"
    })

    return decision


# ── Transport ─────────────────────────────────────────────────────────────────

def _emit(decision: dict, domain: str, city_id: str) -> None:
    event = {
        "event_id":        str(uuid.uuid4()),
        "event_type":      "decision_proposed",
        "domain":          domain,
        "city_id":         city_id,
        "emitted_at":      _now(),
        "decision_object": decision,
    }

    airnet_url = os.environ.get("AIRNET_EVENTS_URL", "").strip()
    if airnet_url:
        try:
            import requests
            requests.post(airnet_url, json=event, timeout=5).raise_for_status()
            logger.info("Decision emitted to AIRNet: %s", decision["decision_id"])
            return
        except Exception as exc:
            logger.warning("AIRNet emit failed (%s) — falling back to local log", exc)

    log_path = Path(os.environ.get("DECISION_LOG_PATH", "data/events/decisions.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    logger.info("Decision logged: %s [%s/%s]",
                decision["decision_id"], domain, decision["decision_outcome"]["outcome_code"])


# ── Per-domain emitters ───────────────────────────────────────────────────────

def emit_air_decisions(packets: list[dict], city_id: str) -> int:
    emitted = 0
    for packet in packets:
        aa  = packet.get("aqi_assessment") or {}
        cat = aa.get("aqi_category", "")
        if cat not in _AIR_ALERT_CATEGORIES:
            continue

        score   = aa.get("aqi_score") or 0.0
        h3_cell = packet.get("h3_id", "")
        case_id = f"{city_id}-air-{h3_cell[:12]}"

        sources = packet.get("data_sources") or []
        evidence_sources = [
            _evidence_source(
                s.get("source_name", "unknown"),
                s.get("source_type", "sensor_api"),
                s,
            )
            for s in sources
        ] or [_evidence_source("air_quality_connector", "sensor_api", aa)]

        key_facts = [
            {"aqi_category": cat},
            {"aqi_score": score},
            {"h3_cell": h3_cell},
            {"city": city_id},
        ]
        reasoning = [
            {
                "criterion":   f"AQI category threshold (alert if: {', '.join(_AIR_ALERT_CATEGORIES)})",
                "observation": f"AQI category is '{cat}' with score {score:.3f}",
                "conclusion":  "Threshold exceeded — flagging for field investigation",
            }
        ]

        decision = _build_decision_object(
            domain="air", city_id=city_id, h3_cell=h3_cell,
            case_id=case_id, rule_id=_RULE_IDS["air"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"AQ_{cat.upper()}",
            outcome_value=f"AQI category {cat.replace('_', ' ')} — score {score:.3f}",
            evidence_sources=evidence_sources,
            evidence_data=aa,
        )
        _emit(decision, "air", city_id)
        emitted += 1
    return emitted


def emit_heat_decisions(candidates: list[dict], city_id: str) -> int:
    emitted = 0
    for candidate in candidates:
        score = candidate.get("risk_score") or 0.0
        if score < _HEAT_RISK_THRESHOLD:
            continue

        h3_cell = candidate.get("h3_id", "")
        case_id = f"{city_id}-heat-{h3_cell[:12]}"
        uhi     = candidate.get("uhi_intensity")
        interventions = ", ".join(candidate.get("suggested_interventions", []))

        key_facts = [
            {"heat_risk_score": score},
            {"uhi_intensity_c": uhi},
            {"green_deficit": candidate.get("green_deficit")},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Heat risk score threshold (≥ {_HEAT_RISK_THRESHOLD})",
                "observation": f"Heat risk score is {score:.3f}, UHI intensity {uhi}°C",
                "conclusion":  "High urban heat risk — flagging for intervention planning",
            }
        ]
        if interventions:
            reasoning.append({
                "criterion":   "Intervention recommendations",
                "observation": f"Green deficit identified, suggested: {interventions}",
                "conclusion":  "Refer to urban greening / heat mitigation team",
            })

        evidence_sources = [
            _evidence_source("gee_modis_lst", "satellite_observation", candidate)
        ]

        decision = _build_decision_object(
            domain="heat", city_id=city_id, h3_cell=h3_cell,
            case_id=case_id, rule_id=_RULE_IDS["heat"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"HEAT_RISK_{int(score * 100)}",
            outcome_value=f"Heat risk score {score:.3f} — UHI {uhi}°C",
            evidence_sources=evidence_sources,
            evidence_data=candidate,
        )
        _emit(decision, "heat", city_id)
        emitted += 1
    return emitted


def emit_flood_decisions(packets: list[dict], city_id: str) -> int:
    emitted = 0
    for packet in packets:
        fra   = packet.get("flood_risk_assessment") or {}
        score = fra.get("flood_risk_score") or 0.0
        if score < _FLOOD_RISK_THRESHOLD:
            continue

        h3_cell  = packet.get("h3_id", "")
        case_id  = f"{city_id}-flood-{h3_cell[:12]}"
        level    = fra.get("risk_level", "moderate")
        rain_3h  = fra.get("rainfall_accumulation_3h_mm", 0)

        key_facts = [
            {"flood_risk_score": score},
            {"risk_level": level},
            {"rainfall_accumulation_3h_mm": rain_3h},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Flood risk score threshold (≥ {_FLOOD_RISK_THRESHOLD})",
                "observation": f"Flood risk score {score:.3f}, level '{level}', rainfall {rain_3h} mm/3h",
                "conclusion":  f"Flood risk level '{level}' — flagging for drainage and response team",
            }
        ]

        sources = packet.get("data_sources") or []
        evidence_sources = [
            _evidence_source(
                s.get("source_name", "gee_gpm_srtm"),
                s.get("source_type", "satellite_observation"),
                s,
            )
            for s in sources
        ] or [_evidence_source("gee_gpm_srtm", "satellite_observation", fra)]

        decision = _build_decision_object(
            domain="flood", city_id=city_id, h3_cell=h3_cell,
            case_id=case_id, rule_id=_RULE_IDS["flood"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"FLOOD_{level.upper()}",
            outcome_value=f"Flood risk score {score:.3f} — {level} risk",
            evidence_sources=evidence_sources,
            evidence_data=fra,
        )
        _emit(decision, "flood", city_id)
        emitted += 1
    return emitted
