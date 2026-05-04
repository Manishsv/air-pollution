from __future__ import annotations

import json
from pathlib import Path


def test_panel_missing_outputs_returns_none(tmp_path: Path) -> None:
    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_demo_outputs,
    )

    assert load_program_reporting_demo_outputs(base_output_dir=tmp_path / "nope") is None


def test_panel_loader_reads_state_summary_and_packets(tmp_path: Path) -> None:
    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_demo_outputs,
    )

    out_dir = tmp_path / "program_reporting_state_demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    state_summary = {
        "state_node_id": "node:state_urban_department_demo",
        "program_id": "stormwater_resilience_grant_2026",
        "reporting_period": "2026_Q1",
        "generated_at": "2026-05-04T12:00:00Z",
        "city_count": 2,
        "review_status_counts": {"review_ready": 1, "clarification_required": 1},
        "fund_release_review_status_counts": {"ready_for_authorized_review": 1, "clarification_needed": 1},
        "financial_totals": {
            "amount_approved_total": 2000000.0,
            "amount_released_total": 1200000.0,
            "amount_spent_total": 600000.0,
            "utilization_pct": 50.0,
        },
        "city_financial_rows": [
            {
                "city_id": "city_demo_a",
                "amount_approved": 1000000.0,
                "amount_released": 800000.0,
                "amount_spent": 500000.0,
                "utilization_pct": 62.5,
                "fund_release_review_status": "ready_for_authorized_review",
            },
            {
                "city_id": "city_demo_b",
                "amount_approved": 1000000.0,
                "amount_released": 400000.0,
                "amount_spent": 100000.0,
                "utilization_pct": 25.0,
                "fund_release_review_status": "clarification_needed",
            },
        ],
        "city_progress_rows": [
            {
                "city_id": "city_demo_a",
                "projects_total": 10,
                "projects_completed": 6,
                "projects_in_progress": 3,
                "projects_delayed": 1,
                "overall_progress_pct": 60.0,
                "flags": [],
                "review_status": "review_ready",
            },
            {
                "city_id": "city_demo_b",
                "projects_total": 10,
                "projects_completed": 2,
                "projects_in_progress": 4,
                "projects_delayed": 4,
                "overall_progress_pct": 30.0,
                "flags": ["progress_delay"],
                "review_status": "clarification_required",
            },
        ],
        "action_items": [
            {
                "action_id": "action_authorized_review_city_demo_a",
                "action_label": "Queue for authorized review",
                "responsible_role": "state_program_reviewer",
                "city_id": "city_demo_a",
                "status": "open",
                "reason": "City submission is review-ready; proceed with authorized review workflow outside AirOS.",
            },
            {
                "action_id": "action_request_clarification_city_demo_b",
                "action_label": "Request clarification from city",
                "responsible_role": "state_program_reviewer",
                "city_id": "city_demo_b",
                "status": "open",
                "reason": "Submission needs clarification based on demo rules and/or flags; request supporting clarification (no fund release automation).",
            },
        ],
        "flagged_cities": [],
        "cities_ready_for_authorized_review": ["city_demo_a"],
        "cities_needing_clarification": ["city_demo_b"],
        "warnings": [
            "fixture/demo data only",
            "review support only",
            "no automatic fund release",
            "authorized finance process required",
        ],
        "blocked_uses": [
            "automatic_fund_release",
            "automatic_penalty_or_recovery",
            "blacklisting_without_authorized_review",
            "public_disclosure_without_authorization",
        ],
        "provenance": {"fixture_demo": True},
    }
    packets = [
        {
            "city_id": "city_demo_a",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
            "review_status": "review_ready",
            "fund_release_review_status": "ready_for_authorized_review",
            "flags": [],
            "confidence": 0.9,
        },
        {
            "city_id": "city_demo_b",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
            "review_status": "clarification_required",
            "fund_release_review_status": "clarification_needed",
            "flags": ["progress_delay"],
            "confidence": 0.8,
        },
    ]

    (out_dir / "state_program_summary.json").write_text(json.dumps(state_summary), encoding="utf-8")
    (out_dir / "fund_release_review_packets.json").write_text(json.dumps(packets), encoding="utf-8")

    loaded = load_program_reporting_demo_outputs(base_output_dir=out_dir)
    assert loaded is not None
    assert loaded.state_summary is not None
    assert len(loaded.review_packets) == 2


def test_program_reporting_panel_contains_business_sections() -> None:
    panel = (
        Path(__file__).resolve().parents[1]
        / "review_dashboard"
        / "components"
        / "program_reporting_panel.py"
    )
    text = panel.read_text(encoding="utf-8")
    for s in (
        "Program Reporting & Fund Release Review",
        "Financial progress",
        "Program progress",
        "Needs attention",
        "Action items",
        "Do not use this dashboard for",
        "Technical details:",
    ):
        assert s in text


def test_panel_loader_falls_back_to_single_packet(tmp_path: Path) -> None:
    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_demo_outputs,
    )

    out_dir = tmp_path / "program_reporting_state_demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    pkt = {
        "city_id": "city_demo_a",
        "program_id": "stormwater_resilience_grant_2026",
        "reporting_period": "2026_Q1",
        "review_status": "human_review_required",
        "fund_release_review_status": "clarification_needed",
        "flags": ["progress_delay"],
        "confidence": 0.85,
        "review_notes": "review support only; no automatic fund release",
    }
    (out_dir / "fund_release_review_packet.json").write_text(json.dumps(pkt), encoding="utf-8")

    loaded = load_program_reporting_demo_outputs(base_output_dir=out_dir)
    assert loaded is not None
    assert loaded.state_summary is None
    assert len(loaded.review_packets) == 1

