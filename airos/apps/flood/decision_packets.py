from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _packet_id(area_id: str, generated_at: str) -> str:
    raw = f"flood_risk|packet|{area_id}|{generated_at}"
    return "pkt_flood_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _risk_level_placeholder(*, rainfall_mm_per_hour: float | None, incident_count: int, data_quality_score: float | None) -> str:
    # Mirror the dashboard placeholder logic; keep conservative.
    if data_quality_score is not None and float(data_quality_score) < 0.5:
        return "unknown"
    if incident_count >= 3:
        return "high"
    if incident_count >= 1:
        return "moderate"
    if rainfall_mm_per_hour is None:
        return "unknown"
    r = float(rainfall_mm_per_hour)
    if r >= 50:
        return "high"
    if r >= 20:
        return "moderate"
    return "low"


def build_flood_decision_packets(
    feature_rows: pd.DataFrame,
    *,
    generated_at: str | None = None,
    city_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build flood decision packets (consumer contract) from flood feature rows.

    Safety posture:
    - Decision support only (no automated operational recommendations).
    - Placeholder risk categories are triage labels, not validated predictions.
    - Field verification required when confidence is low, synthetic inputs are present, or low-lying proxy is unavailable.
    """
    gen = generated_at or _now()
    df = feature_rows.copy() if feature_rows is not None else pd.DataFrame()
    if df.empty:
        df = pd.DataFrame(
            [
                {
                    "area_id": city_id or "__unassigned__",
                    "rainfall_mm_per_hour": None,
                    "incident_count": 0,
                    "drainage_asset_count": 0,
                    "data_quality_score": 0.0,
                    "source_count": 0,
                    "provenance_summary": {"sources": [], "synthetic_used": False},
                    "warning_flags": ["NO_FEATURE_ROWS"],
                }
            ]
        )

    packets: list[dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        area_id = str(row.get("area_id") or city_id or "__unassigned__")
        rainfall = row.get("rainfall_mm_per_hour")
        incident_count = int(row.get("incident_count") or 0)
        drainage_asset_count = int(row.get("drainage_asset_count") or 0)
        dqs = row.get("data_quality_score")
        try:
            dqs_f = float(dqs) if dqs is not None else None
        except Exception:
            dqs_f = None

        provenance_summary = row.get("provenance_summary") if isinstance(row.get("provenance_summary"), dict) else {}
        sources = provenance_summary.get("sources") or []
        synthetic_used = bool(provenance_summary.get("synthetic_used"))

        flags: set[str] = set()
        wf = row.get("warning_flags")
        if isinstance(wf, list):
            flags.update(str(x) for x in wf if x)
        if synthetic_used:
            flags.add("SYNTHETIC_INPUT_PRESENT")

        risk_level = _risk_level_placeholder(
            rainfall_mm_per_hour=rainfall if isinstance(rainfall, (int, float)) else None,
            incident_count=incident_count,
            data_quality_score=dqs_f,
        )

        # Safety gates
        gates: list[dict[str, Any]] = []
        field_verification_required = True

        if "LOW_LYING_PROXY_UNAVAILABLE" in flags:
            gates.append(
                {
                    "gate_id": "low_lying_proxy_unavailable",
                    "status": "warning",
                    "message": "Low-lying/elevation proxy unavailable; risk labels are placeholders.",
                }
            )
        if synthetic_used:
            gates.append(
                {
                    "gate_id": "synthetic_inputs_present",
                    "status": "blocked",
                    "message": "Synthetic inputs present; restrict to review and verification tasks.",
                }
            )
        if dqs_f is not None and dqs_f < 0.5:
            gates.append(
                {
                    "gate_id": "low_data_quality",
                    "status": "blocked",
                    "message": "Low data quality; do not treat as operational truth.",
                }
            )

        # Always include an explicit decision-support gate.
        gates.append(
            {
                "gate_id": "decision_support_only",
                "status": "warning",
                "message": "This packet is decision support only; it is not an emergency order.",
            }
        )

        # Recommendation allowed? Never for operational action in this phase.
        recommendation_allowed = False
        block_reason = "Field verification and human review required. No automated operational recommendations."

        # Evidence inputs (lightweight; derived from features only)
        evidence_inputs: list[dict[str, Any]] = []
        if rainfall is not None:
            evidence_inputs.append(
                {
                    "type": "feature",
                    "name": "rainfall_mm_per_hour",
                    "value": rainfall,
                    "unit": "mm/hr",
                }
            )
        evidence_inputs.append({"type": "feature", "name": "incident_count", "value": incident_count, "unit": "count"})
        evidence_inputs.append({"type": "feature", "name": "drainage_asset_count", "value": drainage_asset_count, "unit": "count"})

        # Conservative recommended action (review/verify only)
        recommended_action = "Review evidence and dispatch field verification if warranted; do not treat placeholders as confirmed flood events."

        review_prompts = [
            "Is there authoritative confirmation (sensors/field teams) beyond proxies or unverified incidents?",
            "Are there known low-lying zones or drainage constraints near the highlighted area?",
            "Is the data quality sufficient to escalate, or should this remain a verification-only task?",
        ]
        when_not_to_act = [
            "Do not issue emergency orders based on placeholder risk labels.",
            "Do not treat synthetic or low-confidence inputs as operational truth.",
        ]

        uncertainty_notes: list[str] = []
        if "LOW_LYING_PROXY_UNAVAILABLE" in flags:
            uncertainty_notes.append("Low-lying/elevation proxy unavailable.")
        if synthetic_used:
            uncertainty_notes.append("Synthetic inputs present.")
        if risk_level == "unknown":
            uncertainty_notes.append("Insufficient confidence for risk categorization.")

        packet: dict[str, Any] = {
            "packet_id": _packet_id(area_id, gen),
            "domain_id": "flood_risk",
            "timestamp": gen,
            "area_id": area_id,
            "risk_assessment": {
                "risk_level": risk_level,
                "time_window": "now_to_next_3_hours",
                "primary_driver": "placeholder_rules",
            },
            "evidence": {
                "inputs": evidence_inputs,
                "notes": "Placeholder triage only; not a validated flood prediction.",
            },
            "provenance": {
                "sources": sources,
                "synthetic_used": bool(synthetic_used),
            },
            "confidence": {
                "confidence_score": dqs_f,
                "recommendation_allowed": recommendation_allowed,
                "recommendation_block_reason": block_reason,
            },
            "uncertainty": {"notes": " ".join(uncertainty_notes).strip()},
            "recommended_action": recommended_action,
            "review_guidance": {"review_prompts": review_prompts, "when_not_to_act": when_not_to_act},
            "safety_gates": gates,
            "blocked_uses": [
                "automatic_emergency_dispatch_without_human_review",
                "treat_placeholder_or_synthetic_inputs_as_confirmed_incident",
            ],
            "field_verification_required": field_verification_required,
        }

        packets.append(packet)

    return packets

