from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_id(source_packet_id: str, assigned_role: str) -> str:
    raw = f"field_task|{source_packet_id}|{assigned_role}"
    return "task_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _priority_from_packet(pkt: dict[str, Any]) -> str:
    # Conservative default: without matching/mismatch severity, keep medium.
    issue = str(pkt.get("issue_type") or "").lower()
    if "high" in issue:
        return "high"
    if "low" in issue:
        return "low"
    return "medium"


def build_property_buildings_field_verification_tasks(
    review_packets: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    assigned_role: str = "field_inspector",
) -> list[dict[str, Any]]:
    """
    Build property/buildings field verification tasks from property/buildings review packets.

    Safety posture:
    - Verification tasks only (not enforcement/tax actions).
    - Tasks can be created even when packets block operational use (verification is how we unblock responsibly).
    """
    created_at = generated_at or _now()
    tasks: list[dict[str, Any]] = []

    for pkt in review_packets or []:
        if not isinstance(pkt, dict):
            continue
        packet_id = str(pkt.get("packet_id") or "")
        if not packet_id:
            continue

        domain_id = str(pkt.get("domain_id") or "property_buildings")
        priority = _priority_from_packet(pkt)

        issue_type = str(pkt.get("issue_type") or "unknown")
        confidence = pkt.get("confidence") or {}
        block_reason = str(confidence.get("recommendation_block_reason") or "").strip()

        verification_questions = [
            "Verify building existence and approximate built-up area (visual estimate is acceptable).",
            "Verify occupancy/use category if legally permissible and relevant (do not collect personal data).",
            "Verify whether permit documentation exists or permit status reference can be confirmed.",
            "Verify whether parcel/property identifiers used in records correspond to the physical site (non-identifying references only).",
        ]

        evidence_to_collect = [
            "photo",
            "site_visit_note",
            "approx_area_sq_m_estimate",
            "permit_reference_observed",
            "timestamp",
        ]

        notes_parts = [
            "Decision support only. Verification task, not an enforcement/tax action.",
            f"issue_type={issue_type}",
        ]
        if block_reason:
            notes_parts.append(f"packet_block_reason={block_reason}")
        if pkt.get("field_verification_required") is True:
            notes_parts.append("field_verification_required=true")

        task: dict[str, Any] = {
            "task_id": _task_id(packet_id, assigned_role),
            "source_packet_id": packet_id,
            "domain_id": domain_id,
            "location": {
                # Current property/buildings scaffolding is area-based; refine once geometry is safely supported.
                "centroid_lat": None,
                "centroid_lon": None,
                "geometry_geojson": None,
            },
            "assigned_role": assigned_role,
            "verification_questions": verification_questions,
            "evidence_to_collect": evidence_to_collect,
            "priority": priority,
            "status": "open",
            "created_at": created_at,
            "notes": " | ".join(notes_parts),
        }

        tasks.append(task)

    return tasks

