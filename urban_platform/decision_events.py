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
    "fire":  "fire_airshed_monitoring",
    "waste": "waste_site_monitoring",
    "water":        "water_quality_monitoring",
    "construction": "construction_dust_monitoring",
    "green":        "green_cover_monitoring",
    "noise":        "noise_risk_monitoring",
}

_RULE_IDS = {
    "air":   "airos_air_decisions_v1",
    "heat":  "airos_heat_decisions_v1",
    "flood": "airos_flood_decisions_v1",
    "fire":  "airos_fire_decisions_v1",
    "waste": "airos_waste_decisions_v1",
    "water":        "airos_water_decisions_v1",
    "construction": "airos_construction_decisions_v1",
    "green":        "airos_green_decisions_v1",
    "noise":        "airos_noise_decisions_v1",
}

_FIRE_FRP_THRESHOLD  = 5.0   # MW — minimum fire radiative power
_WATER_WQI_THRESHOLD = 0.25  # minimum WQI to emit a water decision

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


def emit_fire_decisions(
    fire_df,   # pd.DataFrame from FIRMS connector
    city_id: str,
    bbox: dict,
) -> int:
    """Emit Decision Objects for VIIRS fire detections in city + airshed."""
    try:
        import pandas as pd
        import h3 as _h3
    except ImportError:
        return 0

    if fire_df is None or (hasattr(fire_df, "empty") and fire_df.empty):
        return 0

    required = {"latitude", "longitude", "frp"}
    if not required.issubset(fire_df.columns):
        return 0

    emitted = 0
    for _, row in fire_df.iterrows():
        frp = float(row.get("frp") or 0)
        if frp < _FIRE_FRP_THRESHOLD:
            continue

        lat = float(row["latitude"])
        lon = float(row["longitude"])

        try:
            h3_cell = _h3.latlng_to_cell(lat, lon, 9)
        except Exception:
            h3_cell = f"{lat:.4f}_{lon:.4f}"

        confidence = int(row.get("detection_confidence") or 50)
        acq_date   = str(row.get("acq_date", ""))
        satellite  = str(row.get("satellite", "VIIRS"))
        in_city    = bool(row.get("within_bbox", False))
        location   = "city" if in_city else "airshed"

        case_id = f"{city_id}-fire-{h3_cell[:12]}"

        key_facts = [
            {"fire_radiative_power_mw": frp},
            {"detection_confidence_pct": confidence},
            {"satellite": satellite},
            {"acq_date": acq_date},
            {"location_type": location},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Fire radiative power threshold (≥ {_FIRE_FRP_THRESHOLD} MW)",
                "observation": f"VIIRS detected fire at ({lat:.4f}, {lon:.4f}), FRP {frp:.1f} MW, confidence {confidence}%",
                "conclusion":  f"Active fire in {location} — flagging for airshed air quality impact assessment",
            }
        ]

        evidence_data = {
            "latitude": lat, "longitude": lon,
            "frp": frp, "detection_confidence": confidence,
            "satellite": satellite, "acq_date": acq_date,
        }
        evidence_sources = [
            _evidence_source("nasa_firms_viirs", "satellite_observation", evidence_data)
        ]

        decision = _build_decision_object(
            domain="fire",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["fire"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"FIRE_FRP_{int(frp)}MW",
            outcome_value=f"Fire detected {frp:.1f} MW FRP — {location} impact",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "fire", city_id)
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


def emit_waste_decisions(packets: list[dict], city_id: str) -> int:
    """Emit Decision Objects for waste monitoring packets."""
    emitted = 0
    for packet in packets:
        wa    = packet.get("waste_assessment") or {}
        score = (packet.get("confidence") or {}).get("confidence_score", 0.0)
        if score < 0.25:
            continue

        h3_cell  = packet.get("h3_id", "")
        dom_type = wa.get("dominant_type", "waste_burn")
        level    = wa.get("risk_level", "low")
        signals  = wa.get("signals_active", [])
        case_id  = f"{city_id}-waste-{h3_cell[:12]}"

        key_facts = [
            {"dominant_waste_type": dom_type},
            {"risk_level": level},
            {"signals_active": signals},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Waste risk score threshold (≥ 0.25)",
                "observation": f"Dominant signal: {dom_type}, risk level: {level}, active signals: {signals}",
                "conclusion":  f"Waste site activity detected — flagging for municipal solid waste team review",
            }
        ]

        ev = packet.get("evidence") or {}
        evidence_data = {inp["name"]: inp["value"] for inp in (ev.get("inputs") or [])}
        evidence_sources = [
            _evidence_source(
                s.get("source", "satellite"),
                "satellite_observation",
                {"label": s.get("label", ""), "detail": s.get("detail", "")},
            )
            for s in (packet.get("data_source_status") or [])
        ] or [_evidence_source("firms_sentinel", "satellite_observation", evidence_data)]

        decision = _build_decision_object(
            domain="waste",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["waste"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"WASTE_{dom_type.upper()}_{level.upper()}",
            outcome_value=f"{dom_type.replace('_', ' ').title()} — {level} risk",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "waste", city_id)
        emitted += 1
    return emitted


def emit_water_decisions(packets: list[dict], city_id: str) -> int:
    """Emit Decision Objects for water quality monitoring packets."""
    emitted = 0
    for packet in packets:
        wa    = packet.get("water_assessment") or {}
        score = (packet.get("confidence") or {}).get("confidence_score", 0.0)
        if score < _WATER_WQI_THRESHOLD:
            continue

        h3_cell  = packet.get("h3_id", "")
        level    = wa.get("quality_level", "moderate")
        dominant = wa.get("dominant_issue", "turbidity")
        wqi      = wa.get("water_quality_index", 0.0)
        case_id  = f"{city_id}-water-{h3_cell[:12]}"

        key_facts = [
            {"quality_level": level},
            {"dominant_issue": dominant},
            {"water_quality_index": wqi},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Water quality index threshold (≥ {_WATER_WQI_THRESHOLD})",
                "observation": f"WQI = {wqi:.3f}, dominant issue: {dominant}, level: {level}",
                "conclusion":  f"Water body degradation detected — flagging for water authority review",
            }
        ]

        ev = packet.get("evidence") or {}
        evidence_data = {inp["name"]: inp["value"] for inp in (ev.get("inputs") or [])}
        evidence_sources = [
            _evidence_source(
                s.get("source", "sentinel2_wq"),
                "satellite_observation",
                {"label": s.get("label", ""), "detail": s.get("detail", "")},
            )
            for s in (packet.get("data_source_status") or [])
        ] or [_evidence_source("sentinel2_wq", "satellite_observation", evidence_data)]

        decision = _build_decision_object(
            domain="water",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["water"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"WATER_{dominant.upper()}_{level.upper()}",
            outcome_value=f"{dominant.replace('_', ' ').title()} — {level} quality",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "water", city_id)
        emitted += 1
    return emitted


_CONSTRUCTION_CRI_THRESHOLD = 0.40  # moderate and above


def emit_construction_decisions(packets: list[dict], city_id: str) -> int:
    """Emit Decision Objects for construction activity monitoring packets."""
    emitted = 0
    for packet in packets:
        ca    = packet.get("construction_assessment") or {}
        score = (packet.get("confidence") or {}).get("confidence_score", 0.0)
        if score < _CONSTRUCTION_CRI_THRESHOLD:
            continue

        h3_cell  = packet.get("h3_id", "")
        level    = ca.get("risk_level", "moderate")
        dominant = ca.get("dominant_activity", "soil_disturbance")
        cri      = ca.get("construction_risk_index", 0.0)
        case_id  = f"{city_id}-construction-{h3_cell[:12]}"

        key_facts = [
            {"risk_level": level},
            {"dominant_activity": dominant},
            {"construction_risk_index": cri},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Construction risk index threshold (≥ {_CONSTRUCTION_CRI_THRESHOLD})",
                "observation": f"CRI = {cri:.3f}, dominant: {dominant}, level: {level}",
                "conclusion":  f"Active construction detected — flagging for dust compliance review",
            }
        ]

        ev = packet.get("evidence") or {}
        evidence_data = {inp["name"]: inp["value"] for inp in (ev.get("inputs") or [])}
        evidence_sources = [
            _evidence_source(
                s.get("source", "sentinel2_bsi"),
                "satellite_observation",
                {"label": s.get("label", ""), "detail": s.get("detail", "")},
            )
            for s in (packet.get("data_source_status") or [])
        ] or [_evidence_source("sentinel2_bsi", "satellite_observation", evidence_data)]

        decision = _build_decision_object(
            domain="construction",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["construction"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"CONSTRUCTION_{dominant.upper()}_{level.upper()}",
            outcome_value=f"{dominant.replace('_', ' ').title()} — {level} risk",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "construction", city_id)
        emitted += 1
    return emitted


_GREEN_GCCI_THRESHOLD = 0.2  # |GCCI| threshold for loss packets


def emit_green_decisions(packets: list[dict], city_id: str) -> int:
    """Emit Decision Objects for green cover loss monitoring packets."""
    emitted = 0
    for packet in packets:
        ga    = packet.get("green_assessment") or {}
        score = (packet.get("confidence") or {}).get("confidence_score", 0.0)
        if score < _GREEN_GCCI_THRESHOLD:
            continue

        h3_cell  = packet.get("h3_id", "")
        level    = ga.get("change_level", "moderate_loss")
        gcci     = ga.get("green_cover_change_index", 0.0)
        ndvi_chg = ga.get("ndvi_change", 0.0)
        coverage = ga.get("coverage_class", "moderate")
        case_id  = f"{city_id}-green-{h3_cell[:12]}"

        key_facts = [
            {"change_level": level},
            {"green_cover_change_index": gcci},
            {"ndvi_change": ndvi_chg},
            {"coverage_class": coverage},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"|GCCI| threshold (≥ {_GREEN_GCCI_THRESHOLD})",
                "observation": f"GCCI = {gcci:.3f}, ΔNDVI = {ndvi_chg:+.3f}, level: {level}",
                "conclusion":  "Significant green cover loss — flagging for urban forestry review",
            }
        ]

        ev = packet.get("evidence") or {}
        evidence_data = {inp["name"]: inp["value"] for inp in (ev.get("inputs") or [])}
        evidence_sources = [
            _evidence_source(
                s.get("source", "sentinel2_ndvi"),
                "satellite_observation",
                {"label": s.get("label", ""), "detail": s.get("detail", "")},
            )
            for s in (packet.get("data_source_status") or [])
        ] or [_evidence_source("sentinel2_ndvi", "satellite_observation", evidence_data)]

        decision = _build_decision_object(
            domain="green",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["green"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"GREEN_{level.upper()}",
            outcome_value=f"{level.replace('_', ' ').title()} — ΔNDVI {ndvi_chg:+.3f}",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "green", city_id)
        emitted += 1
    return emitted


_NOISE_NRI_THRESHOLD = 0.5  # high and above


def emit_noise_decisions(packets: list[dict], city_id: str) -> int:
    """Emit Decision Objects for noise risk monitoring packets."""
    emitted = 0
    for packet in packets:
        na    = packet.get("noise_assessment") or {}
        score = (packet.get("confidence") or {}).get("confidence_score", 0.0)
        if score < _NOISE_NRI_THRESHOLD:
            continue

        h3_cell  = packet.get("h3_id", "")
        level    = na.get("risk_level", "high")
        dominant = na.get("dominant_source", "traffic_corridor")
        nri      = na.get("noise_risk_index", 0.0)
        db_proxy = na.get("db_proxy", "—")
        case_id  = f"{city_id}-noise-{h3_cell[:12]}"

        key_facts = [
            {"risk_level": level},
            {"dominant_source": dominant},
            {"noise_risk_index": nri},
            {"db_proxy": db_proxy},
            {"h3_cell": h3_cell},
        ]
        reasoning = [
            {
                "criterion":   f"Noise risk index threshold (≥ {_NOISE_NRI_THRESHOLD})",
                "observation": f"NRI = {nri:.3f}, dominant: {dominant}, proxy: {db_proxy}",
                "conclusion":  "Elevated noise risk — flagging for acoustic verification and source identification",
            }
        ]

        ev = packet.get("evidence") or {}
        evidence_data = {inp["name"]: inp["value"] for inp in (ev.get("inputs") or [])}
        evidence_sources = [
            _evidence_source(
                s.get("source", "noise_proximity_model"),
                "proxy_model",
                {"label": s.get("label", ""), "detail": s.get("detail", "")},
            )
            for s in (packet.get("data_source_status") or [])
        ] or [_evidence_source("noise_proximity_model", "proxy_model", evidence_data)]

        decision = _build_decision_object(
            domain="noise",
            city_id=city_id,
            h3_cell=h3_cell,
            case_id=case_id,
            rule_id=_RULE_IDS["noise"],
            key_facts=key_facts,
            structured_reasoning=reasoning,
            outcome_code=f"NOISE_{dominant.upper()}_{level.upper()}",
            outcome_value=f"{dominant.replace('_', ' ').title()} — {level} ({db_proxy})",
            evidence_sources=evidence_sources,
            evidence_data=evidence_data,
        )
        _emit(decision, "noise", city_id)
        emitted += 1
    return emitted
