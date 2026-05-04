from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

_BLOCKED_USES: list[str] = [
    "automatic_fund_release",
    "automatic_penalty_or_recovery",
    "blacklisting_without_authorized_review",
    "public_disclosure_without_authorization",
]

_REQUIRED_HUMAN_APPROVALS: list[str] = [
    "state_program_reviewer",
    "finance_department_authorizer",
]


def _normalize_state_node_id(state_node_id: str) -> str:
    if state_node_id.startswith("node:"):
        return state_node_id
    return f"node:{state_node_id}"


def _confidence_for_flags(flags: list[str]) -> float:
    if "financial_inconsistency" in flags:
        return 0.75
    n = len(flags)
    if n == 0:
        return 0.9
    if n == 1:
        return 0.85
    return 0.8


def build_fund_release_review_packet(
    city_submission: dict[str, Any],
    *,
    state_node_id: str = "state_urban_department_demo",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a Phase 1 fund_release_review_packet from a city_program_submission-shaped dict.

    Deterministic demo rules only; no finance integration or automatic fund release.
    """
    prog = city_submission["program_progress"]
    fin = city_submission["financial_progress"]
    overall = float(prog["overall_progress_pct"])
    utilization = float(fin["utilization_pct"])
    spent = float(fin["amount_spent"])
    released = float(fin["amount_released"])

    flags: list[str] = []
    if spent > released:
        flags.append("financial_inconsistency")
    if overall < 50.0:
        flags.append("progress_delay")
    if utilization < 50.0:
        flags.append("low_fund_utilization")

    if "financial_inconsistency" in flags:
        review_status = "clarification_required"
        fund_release_review_status = "not_ready"
    elif flags:
        if "progress_delay" in flags and "low_fund_utilization" in flags:
            review_status = "human_review_required"
            fund_release_review_status = "clarification_needed"
        elif "progress_delay" in flags:
            review_status = "human_review_required"
            fund_release_review_status = "clarification_needed"
        else:
            review_status = "clarification_required"
            fund_release_review_status = "clarification_needed"
    else:
        review_status = "review_ready"
        fund_release_review_status = "ready_for_authorized_review"

    rules_triggered_progress = [f for f in flags if f == "progress_delay"]
    rules_triggered_financial = [f for f in flags if f in ("low_fund_utilization", "financial_inconsistency")]

    ts = generated_at
    if not ts:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    submission_id = str(city_submission["submission_id"])
    packet_id = f"fr_{submission_id}"

    review_notes = (
        "Fixture-based review support only: this packet does not authorize fund release, penalties, "
        "or public disclosure. An authorized finance process outside AirOS remains required."
    )

    ref_versions = copy.deepcopy(city_submission["reference_data_versions"])

    return {
        "packet_id": packet_id,
        "state_node_id": _normalize_state_node_id(state_node_id),
        "city_id": city_submission["city_id"],
        "program_id": city_submission["program_id"],
        "program_spec_version": city_submission["program_spec_version"],
        "reporting_period": city_submission["reporting_period"],
        "submission_id": submission_id,
        "generated_at": ts,
        "review_status": review_status,
        "fund_release_review_status": fund_release_review_status,
        "progress_assessment": {
            "summary": "Demo rule evaluation on self-reported program_progress only.",
            "rules_triggered_demo": rules_triggered_progress,
        },
        "financial_assessment": {
            "summary": "Demo rule evaluation on self-reported financial_progress only.",
            "rules_triggered_demo": rules_triggered_financial,
        },
        "flags": flags,
        "required_human_approvals": list(_REQUIRED_HUMAN_APPROVALS),
        "confidence": _confidence_for_flags(flags),
        "blocked_uses": list(_BLOCKED_USES),
        "review_notes": review_notes,
        "provenance": {
            "generated_by": "urban_platform.applications.program_reporting.review_packets.build_fund_release_review_packet",
            "fixture_demo": True,
        },
        "reference_data_versions": ref_versions,
    }


def build_program_reporting_demo_outputs(
    city_submission: dict[str, Any],
    *,
    state_node_id: str = "state_urban_department_demo",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return a small envelope for demo runners (single review packet)."""
    return {
        "fund_release_review_packet": build_fund_release_review_packet(
            city_submission,
            state_node_id=state_node_id,
            generated_at=generated_at,
        )
    }
