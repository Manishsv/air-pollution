from __future__ import annotations

import json
import re
from pathlib import Path

from airos.apps.program_reporting.review_packets import (
    build_fund_release_review_packet,
    build_program_reporting_demo_outputs,
    build_program_reporting_state_summary,
)
from airos.os.specifications.conformance import assert_conforms

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE_SUBMISSION = _REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json"
_SAMPLE_SUBMISSION_CITY_B = (
    _REPO_ROOT / "specifications/examples/program_reporting/city_program_submission_city_b.sample.json"
)


def _load_sample_submission() -> dict:
    return json.loads(_SAMPLE_SUBMISSION.read_text(encoding="utf-8"))


def _load_city_b_submission() -> dict:
    return json.loads(_SAMPLE_SUBMISSION_CITY_B.read_text(encoding="utf-8"))


def _base_submission(**overrides) -> dict:
    doc = _load_sample_submission()
    doc.update(overrides)
    return doc


def test_sample_submission_builds_valid_review_packet() -> None:
    sub = _load_sample_submission()
    assert_conforms(sub, schema_name="consumer_city_program_submission")
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert_conforms(packet, schema_name="consumer_fund_release_review_packet")
    # City A fixture is healthy (progress >= 50%, utilization >= 50%, spend <= released): no demo flags.
    assert packet["flags"] == []
    assert packet["review_status"] == "review_ready"
    assert packet["fund_release_review_status"] == "ready_for_authorized_review"


def test_preserves_reference_data_versions() -> None:
    sub = _load_sample_submission()
    expected = dict(sub["reference_data_versions"])
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert packet["reference_data_versions"] == expected


def test_blocked_uses_and_human_approvals_always_present() -> None:
    sub = _load_sample_submission()
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert len(packet["blocked_uses"]) >= 4
    assert "automatic_fund_release" in packet["blocked_uses"]
    assert "state_program_reviewer" in packet["required_human_approvals"]
    assert "finance_department_authorizer" in packet["required_human_approvals"]


def test_review_notes_disclaim_automatic_fund_release() -> None:
    sub = _load_sample_submission()
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    notes = packet["review_notes"].lower()
    assert "fund release" in notes or "release" in notes
    assert "automatic" in notes or "authorize" in notes


def test_progress_delay_flag() -> None:
    sub = _base_submission()
    sub["program_progress"] = {**sub["program_progress"], "overall_progress_pct": 40.0}
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert "progress_delay" in packet["flags"]
    assert packet["review_status"] in ("human_review_required", "clarification_required")
    assert_conforms(packet, schema_name="consumer_fund_release_review_packet")


def test_low_fund_utilization_flag() -> None:
    sub = _base_submission()
    sub["financial_progress"] = {
        **sub["financial_progress"],
        "utilization_pct": 40.0,
        "amount_spent": 100.0,
        "amount_released": 200.0,
    }
    sub["program_progress"] = {**sub["program_progress"], "overall_progress_pct": 60.0}
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert "low_fund_utilization" in packet["flags"]
    assert packet["review_status"] in ("clarification_required", "human_review_required")
    assert_conforms(packet, schema_name="consumer_fund_release_review_packet")


def test_financial_inconsistency_flag_and_not_ready() -> None:
    sub = _base_submission()
    sub["financial_progress"] = {
        **sub["financial_progress"],
        "amount_spent": 5000000.0,
        "amount_released": 4000000.0,
        "utilization_pct": 90.0,
    }
    sub["program_progress"] = {**sub["program_progress"], "overall_progress_pct": 60.0}
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert "financial_inconsistency" in packet["flags"]
    assert packet["review_status"] == "clarification_required"
    assert packet["fund_release_review_status"] == "not_ready"
    assert_conforms(packet, schema_name="consumer_fund_release_review_packet")


def test_review_ready_clean_input() -> None:
    sub = _base_submission()
    sub["program_progress"] = {**sub["program_progress"], "overall_progress_pct": 60.0}
    sub["financial_progress"] = {
        **sub["financial_progress"],
        "utilization_pct": 60.0,
        "amount_spent": 100.0,
        "amount_released": 200.0,
    }
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert packet["flags"] == []
    assert packet["review_status"] == "review_ready"
    assert packet["fund_release_review_status"] == "ready_for_authorized_review"
    assert_conforms(packet, schema_name="consumer_fund_release_review_packet")


def test_demo_outputs_envelope() -> None:
    sub = _load_sample_submission()
    out = build_program_reporting_demo_outputs(sub, generated_at="2026-05-04T12:00:00Z")
    assert set(out.keys()) == {"fund_release_review_packet"}
    assert_conforms(out["fund_release_review_packet"], schema_name="consumer_fund_release_review_packet")


def test_city_b_sample_triggers_progress_delay_and_low_utilization() -> None:
    sub = _load_city_b_submission()
    assert_conforms(sub, schema_name="consumer_city_program_submission")
    pkt = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    assert_conforms(pkt, schema_name="consumer_fund_release_review_packet")
    assert "progress_delay" in pkt["flags"]
    assert "low_fund_utilization" in pkt["flags"]


def test_state_summary_aggregates_counts_and_includes_safety_fields() -> None:
    sub_a = _load_sample_submission()
    sub_b = _load_city_b_submission()
    a = build_fund_release_review_packet(sub_a, generated_at="2026-05-04T12:00:00Z")
    b = build_fund_release_review_packet(sub_b, generated_at="2026-05-04T12:00:00Z")
    summary = build_program_reporting_state_summary(
        [a, b],
        city_submissions=[sub_a, sub_b],
        generated_at="2026-05-04T12:05:00Z",
    )

    assert summary["city_count"] == 2
    assert "review_status_counts" in summary
    assert "fund_release_review_status_counts" in summary
    assert "financial_totals" in summary
    assert "city_financial_rows" in summary
    assert "city_progress_rows" in summary
    assert "action_items" in summary
    assert len(summary["blocked_uses"]) >= 4
    assert "automatic_fund_release" in summary["blocked_uses"]
    for w in (
        "fixture/demo data only",
        "review support only",
        "no automatic fund release",
        "authorized finance process required",
    ):
        assert w in summary["warnings"]

    # Guardrail: action items must not imply approval, penalties, blacklisting, or enforcement.
    forbidden = [
        "release funds",
        "approve funds",
        "reject funds",
        "penal",
        "enforce",
        "blacklist",
    ]
    for a in summary["action_items"]:
        blob = json.dumps(a).lower()
        for s in forbidden:
            assert s not in blob


def test_no_personal_names_or_emails_in_output() -> None:
    sub = _load_sample_submission()
    packet = build_fund_release_review_packet(sub, generated_at="2026-05-04T12:00:00Z")
    blob = json.dumps(packet)
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob)
    for role in packet["required_human_approvals"]:
        assert "_" in role or role.islower()
        assert " " not in role
