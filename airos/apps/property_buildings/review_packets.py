from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _packet_id(scope_id: str, generated_at: str) -> str:
    raw = f"property_buildings|review_packet|{scope_id}|{generated_at}"
    return "pkt_pb_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_property_building_review_packets(
    feature_rows: pd.DataFrame,
    *,
    generated_at: str | None = None,
    area_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build property/buildings review packets (consumer contract) from feature scaffolding rows.

    Safety posture:
    - Verification candidates only.
    - No identity resolution / matching between registry, footprints, permits, land use.
    - No tax/enforcement/demolition/penalty recommendations.
    """
    gen = generated_at or _now()
    df = feature_rows.copy() if feature_rows is not None else pd.DataFrame()
    if df.empty:
        df = pd.DataFrame(
            [
                {
                    "area_id": area_id or "__unassigned__",
                    "provenance_summary": {"sources": [], "synthetic_used": False},
                    "warning_flags": ["NO_FEATURE_ROWS", "MATCHING_NOT_IMPLEMENTED"],
                    "property_registry_record_count": 0,
                    "building_footprint_record_count": 0,
                    "building_permit_record_count": 0,
                    "land_use_record_count": 0,
                }
            ]
        )

    packets: list[dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        rid = str(row.get("area_id") or area_id or "__unassigned__")
        prov = row.get("provenance_summary") if isinstance(row.get("provenance_summary"), dict) else {}
        sources = prov.get("sources") or []
        synthetic_used = bool(prov.get("synthetic_used"))

        flags: set[str] = set()
        wf = row.get("warning_flags")
        if isinstance(wf, list):
            flags.update(str(x) for x in wf if x)
        if synthetic_used:
            flags.add("SYNTHETIC_INPUT_PRESENT")

        # We cannot compute real issue types without matching. Emit a conservative "data_readiness" packet.
        issue_type = "data_readiness_review"

        evidence_inputs: list[dict[str, Any]] = [
            {"type": "feature", "name": "property_registry_record_count", "value": int(row.get("property_registry_record_count") or 0), "unit": "count"},
            {"type": "feature", "name": "building_footprint_record_count", "value": int(row.get("building_footprint_record_count") or 0), "unit": "count"},
            {"type": "feature", "name": "building_permit_record_count", "value": int(row.get("building_permit_record_count") or 0), "unit": "count"},
            {"type": "feature", "name": "land_use_record_count", "value": int(row.get("land_use_record_count") or 0), "unit": "count"},
        ]

        # Always require field verification until matching and reliability gates exist.
        field_verification_required = True
        gates: list[dict[str, Any]] = [
            {
                "gate_id": "require_field_verification_before_enforcement_or_tax_action",
                "status": "blocked",
                "message": "No enforcement/tax action may be taken solely from these outputs; field verification + authorized human review required.",
            },
            {
                "gate_id": "matching_not_implemented",
                "status": "blocked",
                "message": "Matching between registry/footprints/permits/land-use not implemented; cannot assert mismatches.",
            },
        ]
        if synthetic_used:
            gates.append(
                {
                    "gate_id": "synthetic_inputs_present",
                    "status": "blocked",
                    "message": "Synthetic/demo inputs present; restrict to contract validation and review-only workflows.",
                }
            )

        recommended_review_action = (
            "Review data coverage and provenance; if policy allows, create a field verification task to validate a small sample before any operational use."
        )

        review_prompts = [
            "Do we have authoritative sources for registry, footprints, permits, and land-use for this area?",
            "Are there privacy constraints that require masking or aggregation before sharing broadly?",
            "Is the data quality sufficient to proceed to matching logic, or should we improve inputs first?",
        ]
        when_not_to_act = [
            "Do not treat this packet as proof of non-compliance.",
            "Do not initiate enforcement, penalties, demolition, or tax reassessment from these outputs.",
        ]

        confidence_score = None
        recommendation_allowed = False
        block_reason = "Verification-first: matching not implemented; field verification required; enforcement/tax uses blocked."

        packet: dict[str, Any] = {
            "packet_id": _packet_id(rid, gen),
            "domain_id": "property_buildings",
            "timestamp": gen,
            "area_id": rid,
            "issue_type": issue_type,
            "evidence": {"inputs": evidence_inputs, "notes": "Scaffolding packet: coverage/provenance review only; no matching performed."},
            "provenance": {"sources": sources, "synthetic_used": bool(synthetic_used)},
            "confidence": {
                "confidence_score": confidence_score,
                "recommendation_allowed": recommendation_allowed,
                "recommendation_block_reason": block_reason,
            },
            "recommended_review_action": recommended_review_action,
            "review_guidance": {"review_prompts": review_prompts, "when_not_to_act": when_not_to_act},
            "safety_gates": gates,
            "blocked_uses": [
                "automated_enforcement_or_tax_reassessment_without_human_review",
                "publish_sensitive_property_details_to_public_dashboards",
                "treat_mismatch_score_as_proof_of_non_compliance",
            ],
            "field_verification_required": field_verification_required,
        }

        packets.append(packet)

    return packets

