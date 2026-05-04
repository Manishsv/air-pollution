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


def build_program_reporting_state_summary(
    review_packets: list[dict[str, Any]],
    *,
    city_submissions: list[dict[str, Any]] | None = None,
    state_node_id: str = "state_urban_department_demo",
    program_id: str = "stormwater_resilience_grant_2026",
    reporting_period: str = "2026_Q1",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """
    Build a minimal state monitoring summary payload from multiple review packets.

    This is a demo-only internal payload (no schema yet). It never recommends automatic fund release.
    """
    ts = generated_at
    if not ts:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    review_status_counts: dict[str, int] = {}
    fund_release_review_status_counts: dict[str, int] = {}
    flagged_cities: list[dict[str, Any]] = []
    ready: list[str] = []
    needs_clarification: list[str] = []
    action_items: list[dict[str, Any]] = []

    by_city_submission: dict[str, dict[str, Any]] = {}
    for sub in city_submissions or []:
        try:
            cid = str(sub.get("city_id") or "")
            if cid:
                by_city_submission[cid] = sub
        except Exception:
            continue

    for pkt in review_packets:
        rs = str(pkt.get("review_status") or "")
        frs = str(pkt.get("fund_release_review_status") or "")
        review_status_counts[rs] = review_status_counts.get(rs, 0) + 1
        fund_release_review_status_counts[frs] = fund_release_review_status_counts.get(frs, 0) + 1

        city_id = str(pkt.get("city_id") or "")
        flags = list(pkt.get("flags") or [])
        if flags:
            flagged_cities.append(
                {
                    "city_id": city_id,
                    "flags": flags,
                    "review_status": rs,
                    "fund_release_review_status": frs,
                }
            )

        if frs == "ready_for_authorized_review" and rs == "review_ready":
            ready.append(city_id)
            if city_id:
                action_items.append(
                    {
                        "action_id": f"action_authorized_review_{city_id}",
                        "action_label": "Queue for authorized review",
                        "responsible_role": "state_program_reviewer",
                        "city_id": city_id,
                        "status": "open",
                        "reason": "City submission is review-ready; proceed with authorized review workflow outside AirOS.",
                    }
                )
        elif city_id:
            needs_clarification.append(city_id)
            action_items.append(
                {
                    "action_id": f"action_request_clarification_{city_id}",
                    "action_label": "Request clarification from city",
                    "responsible_role": "state_program_reviewer",
                    "city_id": city_id,
                    "status": "open",
                    "reason": "Submission needs clarification based on demo rules and/or flags; request supporting clarification (no fund release automation).",
                }
            )

    warnings = [
        "fixture/demo data only",
        "review support only",
        "no automatic fund release",
        "authorized finance process required",
    ]

    city_financial_rows: list[dict[str, Any]] = []
    city_progress_rows: list[dict[str, Any]] = []
    amount_approved_total = 0.0
    amount_released_total = 0.0
    amount_spent_total = 0.0

    for pkt in review_packets:
        city_id = str(pkt.get("city_id") or "")
        frs = str(pkt.get("fund_release_review_status") or "")
        rs = str(pkt.get("review_status") or "")
        flags = list(pkt.get("flags") or [])

        sub = by_city_submission.get(city_id) or {}
        fin = sub.get("financial_progress") if isinstance(sub, dict) else {}
        prog = sub.get("program_progress") if isinstance(sub, dict) else {}

        def _fnum(x: Any) -> float:
            try:
                return float(x)
            except Exception:
                return 0.0

        amount_approved = _fnum((fin or {}).get("amount_approved"))
        amount_released = _fnum((fin or {}).get("amount_released"))
        amount_spent = _fnum((fin or {}).get("amount_spent"))
        utilization_pct = _fnum((fin or {}).get("utilization_pct"))

        amount_approved_total += max(0.0, amount_approved)
        amount_released_total += max(0.0, amount_released)
        amount_spent_total += max(0.0, amount_spent)

        city_financial_rows.append(
            {
                "city_id": city_id,
                "amount_approved": amount_approved,
                "amount_released": amount_released,
                "amount_spent": amount_spent,
                "utilization_pct": utilization_pct,
                "fund_release_review_status": frs,
            }
        )

        city_progress_rows.append(
            {
                "city_id": city_id,
                "projects_total": int((prog or {}).get("projects_total") or 0),
                "projects_completed": int((prog or {}).get("projects_completed") or 0),
                "projects_in_progress": int((prog or {}).get("projects_in_progress") or 0),
                "projects_delayed": int((prog or {}).get("projects_delayed") or 0),
                "overall_progress_pct": _fnum((prog or {}).get("overall_progress_pct")),
                "flags": flags,
                "review_status": rs,
            }
        )

    utilization_pct_total = 0.0
    if amount_released_total > 0:
        utilization_pct_total = (amount_spent_total / amount_released_total) * 100.0

    return {
        "state_node_id": _normalize_state_node_id(state_node_id),
        "program_id": program_id,
        "reporting_period": reporting_period,
        "generated_at": ts,
        "city_count": len(review_packets),
        "review_status_counts": review_status_counts,
        "fund_release_review_status_counts": fund_release_review_status_counts,
        "financial_totals": {
            "amount_approved_total": amount_approved_total,
            "amount_released_total": amount_released_total,
            "amount_spent_total": amount_spent_total,
            "utilization_pct": utilization_pct_total,
        },
        "city_financial_rows": city_financial_rows,
        "city_progress_rows": city_progress_rows,
        "flagged_cities": flagged_cities,
        "cities_ready_for_authorized_review": sorted(set(ready)),
        "cities_needing_clarification": sorted(set(needs_clarification)),
        "action_items": action_items,
        "warnings": warnings,
        "blocked_uses": list(_BLOCKED_USES),
        "provenance": {
            "generated_by": "urban_platform.applications.program_reporting.review_packets.build_program_reporting_state_summary",
            "fixture_demo": True,
        },
    }
