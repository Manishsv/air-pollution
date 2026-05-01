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
    ra = pkt.get("risk_assessment") or {}
    rl = str(ra.get("risk_level") or "unknown").lower()
    if rl == "high":
        return "high"
    if rl == "moderate":
        return "medium"
    if rl == "low":
        return "low"
    return "medium"


def build_flood_field_verification_tasks(
    decision_packets: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    assigned_role: str = "ward_engineer",
) -> list[dict[str, Any]]:
    """
    Build flood field verification tasks from flood decision packets.

    Safety posture:
    - Tasks are verification tasks (not emergency orders).
    - Tasks remain allowed even when packets block operational use; that is precisely when verification is needed.
    """
    created_at = generated_at or _now()
    tasks: list[dict[str, Any]] = []

    for pkt in decision_packets or []:
        if not isinstance(pkt, dict):
            continue
        packet_id = str(pkt.get("packet_id") or "")
        if not packet_id:
            continue

        domain_id = str(pkt.get("domain_id") or "flood_risk")
        priority = _priority_from_packet(pkt)

        ra = pkt.get("risk_assessment") or {}
        risk_level = str(ra.get("risk_level") or "unknown")
        confidence = pkt.get("confidence") or {}
        block_reason = str(confidence.get("recommendation_block_reason") or "").strip()

        verification_questions = [
            "Is there waterlogging at the site? If yes, estimate depth and affected extent.",
            "Are drains/culverts/inlets blocked, damaged, or overflowing nearby?",
            "Are vulnerable assets or critical facilities affected (underpasses, hospitals, substations)?",
            "Are roads passable? Note any closures or access constraints.",
            "Is escalation or a public advisory warranted under current human emergency protocol?",
        ]

        evidence_to_collect = [
            "photos",
            "water_depth_estimate",
            "drain_condition",
            "affected_roads_or_assets",
            "timestamp",
            "field_notes",
        ]

        notes_parts = [
            "Decision support only. Verification task, not an emergency order.",
            f"risk_level={risk_level}",
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
                # Current flood packets are area-based; location can be refined when geometry is available.
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

