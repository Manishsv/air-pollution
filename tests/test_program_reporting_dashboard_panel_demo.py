from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


def _sample_state_summary() -> Dict[str, Any]:
    return {
        "state_node_id": "node:state_urban_department_demo",
        "program_id": "stormwater_resilience_grant_2026",
        "reporting_period": "2026_Q1",
        "generated_at": "2026-05-04T12:00:00Z",
        "city_count": 2,
        "review_status_counts": {"review_ready": 1, "clarification_required": 1},
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
        ],
        "action_items": [
            {
                "action_label": "Queue for authorized review",
                "responsible_role": "state_program_reviewer",
                "city_id": "city_demo_a",
                "status": "open",
                "reason": "Review support outside AirOS; no fund release automation here.",
            },
        ],
        "flagged_cities": [],
        "cities_ready_for_authorized_review": ["city_demo_a"],
        "cities_needing_clarification": ["city_demo_b"],
        "warnings": [],
        "blocked_uses": [
            "automatic_fund_release",
            "automatic_penalty_or_recovery",
            "blacklisting_without_authorized_review",
            "public_disclosure_without_authorization",
        ],
        "fund_release_review_status_counts": {"ready_for_authorized_review": 1, "clarification_needed": 1},
        "provenance": {"generated_by": "demo_test", "fixture_demo": True},
    }


def _sample_packets_direct() -> List[Dict[str, Any]]:
    return [
        {
            "packet_id": "fr_city_a",
            "city_id": "city_demo_a",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
            "review_status": "review_ready",
            "fund_release_review_status": "ready_for_authorized_review",
            "flags": [],
            "confidence": 0.9,
            "submission_id": "sub_a",
        },
        {
            "packet_id": "fr_city_b",
            "city_id": "city_demo_b",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
            "review_status": "clarification_required",
            "fund_release_review_status": "clarification_needed",
            "flags": ["progress_delay"],
            "confidence": 0.8,
            "submission_id": "sub_b",
        },
    ]


def test_default_data_mode_is_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIROS_DASHBOARD_DATA_MODE", raising=False)
    from review_dashboard.components import program_reporting_panel as pr

    assert pr._dashboard_data_mode() == "file"


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

    state_summary = _sample_state_summary()
    packets_raw = [
        {"city_id": "city_demo_a", "submission_id": "s1"},
        {"city_id": "city_demo_b", "submission_id": "s2"},
    ]
    (out_dir / "state_program_summary.json").write_text(json.dumps(state_summary), encoding="utf-8")
    (out_dir / "fund_release_review_packets.json").write_text(json.dumps(packets_raw), encoding="utf-8")

    loaded = load_program_reporting_demo_outputs(base_output_dir=out_dir)
    assert loaded is not None
    assert loaded.output_dir == out_dir.resolve()
    assert loaded.data_source == "file"
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
        "submission_id": "s1",
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


def test_api_mode_stored_output_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://127.0.0.1:8000")
    summaries = [{"output_id": "o1", "contract_key": "x", "generated_at": "2026-05-05T01:00:00Z", "payload": _sample_state_summary()}]
    pkts = [
        {
            "output_id": "p1",
            "contract_key": "consumer_fund_release_review_packet",
            "generated_at": "2026-05-05T01:01:00Z",
            "payload": _sample_packets_direct()[0],
        },
        {"output_id": "p2", "payload": _sample_packets_direct()[1]},
    ]

    def _fetch(base: str, ck: str) -> Tuple[Optional[list], Optional[int], Optional[str]]:
        if ck == "consumer_program_reporting_state_summary":
            return summaries, 200, None
        if ck == "internal_program_reporting_state_summary_demo":
            return [], 200, None
        return pkts, 200, None

    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_dashboard_data,
    )

    r = load_program_reporting_dashboard_data(fetch_outputs=_fetch)
    assert r.mode == "api"
    assert r.outputs is not None
    assert len(r.outputs.review_packets) == 2
    assert r.outputs.state_summary is not None
    assert r.outputs.state_summary.get("city_count") == 2


def test_api_mode_direct_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")

    summary_a = dict(_sample_state_summary())
    summary_a["generated_at"] = "2026-05-05T02:00:00Z"
    summary_b = dict(_sample_state_summary())
    summary_b["generated_at"] = "2026-05-05T03:00:00Z"
    summaries = [summary_b, summary_a]

    pkts = _sample_packets_direct()

    def _fetch(base: str, ck: str) -> Tuple[Optional[list], Optional[int], Optional[str]]:
        if ck == "consumer_program_reporting_state_summary":
            return summaries, 200, None
        if ck == "internal_program_reporting_state_summary_demo":
            return [], 200, None
        return pkts, 200, None

    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_dashboard_data,
        pick_latest_state_summary,
    )

    assert pick_latest_state_summary(summaries)["generated_at"] == "2026-05-05T03:00:00Z"

    r = load_program_reporting_dashboard_data(fetch_outputs=_fetch)
    assert r.outputs is not None
    assert len(r.outputs.review_packets) == 2


def test_api_mode_empty_returns_empty_guide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")

    def _fetch_ok_empty(_base: str, _ck: str) -> Tuple[Optional[list], Optional[int], Optional[str]]:
        return [], 200, None

    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_dashboard_data,
    )

    r = load_program_reporting_dashboard_data(fetch_outputs=_fetch_ok_empty)
    assert r.outputs is None
    assert r.api_empty_guide is True
    assert r.api_warning is None


def test_api_mode_http_error_shows_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")

    def _fetch(_base: str, _ck: str) -> Tuple[Optional[list], Optional[int], Optional[str]]:
        return None, 404, "not found"

    from review_dashboard.components.program_reporting_panel import (
        API_LOAD_FAILURE_PREFACE,
        load_program_reporting_dashboard_data,
    )

    r = load_program_reporting_dashboard_data(fetch_outputs=_fetch)
    assert r.outputs is None
    assert r.api_warning and API_LOAD_FAILURE_PREFACE in r.api_warning
    assert "404" in r.api_warning
    assert r.api_empty_guide is True


def test_api_mode_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")

    def _fetch(_base: str, _ck: str) -> Tuple[Optional[list], Optional[int], Optional[str]]:
        return None, None, "Connection refused"

    from review_dashboard.components.program_reporting_panel import (
        load_program_reporting_dashboard_data,
    )

    r = load_program_reporting_dashboard_data(fetch_outputs=_fetch)
    assert r.outputs is None
    assert r.api_warning and "Connection refused" in r.api_warning


def test_panel_safe_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIROS_DASHBOARD_DATA_MODE", raising=False)
    panel_path = Path(__file__).resolve().parents[1] / "review_dashboard" / "components" / "program_reporting_panel.py"
    text = panel_path.read_text(encoding="utf-8").lower()
    assert "will be automatically released" not in text
    assert "automatic fund release authorized" not in text
