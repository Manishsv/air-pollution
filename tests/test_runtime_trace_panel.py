from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest


def test_file_mode_shows_api_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIROS_DASHBOARD_DATA_MODE", raising=False)
    from airos.network.dashboard.components import runtime_trace_panel as rt

    res = rt.load_runtime_trace_data(fetch_endpoint=lambda _b, _p: ([], 200, None))
    assert res.mode == "file"

    text = (Path(__file__).resolve().parents[1] / "airos" / "network" / "dashboard" / "components" / "runtime_trace_panel.py").read_text(
        encoding="utf-8"
    )
    assert "Runtime Trace is available when the dashboard is connected to AirOS Core API." in text


def test_api_mode_renders_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://example.test")
    from airos.network.dashboard.components import runtime_trace_panel as rt

    runs = [
        {
            "run_id": "r1",
            "application_id": "program_reporting_review_packet",
            "deployment_id": "program_reporting_state_demo",
            "status": "completed",
            "started_at": "2026-05-06T00:00:00Z",
            "completed_at": "2026-05-06T00:01:00Z",
            "records_processed": 2,
            "outputs_generated": 3,
        }
    ]
    receipts = [
        {
            "receipt_id": "v1",
            "contract_key": "consumer_city_program_submission",
            "validation_target_type": "record",
            "validation_target_id": "rec_1",
            "status": "valid",
            "error_count": 0,
            "validated_at": "2026-05-06T00:00:10Z",
        }
    ]
    audits = [
        {
            "occurred_at": "2026-05-06T00:00:10Z",
            "action": "record_ingested",
            "actor": "core_api",
            "resource_type": "record",
            "resource_id": "rec_1",
            "deployment_id": "program_reporting_state_demo",
        }
    ]

    def fetch(_base: str, path: str) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
        if path == "/runs":
            return runs, 200, None
        if path == "/validation-receipts":
            return receipts, 200, None
        if path == "/audit-events":
            return audits, 200, None
        return [], 200, None

    res = rt.load_runtime_trace_data(fetch_endpoint=fetch)
    assert res.mode == "api"
    assert len(res.runs) == 1
    assert len(res.receipts) == 1
    assert len(res.audit_events) == 1


def test_api_mode_invalid_receipts_are_detectable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    from airos.network.dashboard.components import runtime_trace_panel as rt

    receipts = [
        {"receipt_id": "bad", "contract_key": "x", "validation_target_type": "record", "validation_target_id": "r1", "status": "invalid", "error_count": 2}
    ]

    def fetch(_base: str, path: str) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
        if path == "/validation-receipts":
            return receipts, 200, None
        return [], 200, None

    res = rt.load_runtime_trace_data(fetch_endpoint=fetch)
    assert res.mode == "api"
    assert rt._count_invalid_receipts(res.receipts) == 1


def test_api_connection_failure_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    from airos.network.dashboard.components import runtime_trace_panel as rt

    def fetch(_base: str, _path: str) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
        return None, None, "Connection refused"

    res = rt.load_runtime_trace_data(fetch_endpoint=fetch)
    assert res.mode == "api"
    assert res.api_warning is not None


def test_api_empty_returns_empty_guide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    from airos.network.dashboard.components import runtime_trace_panel as rt

    def fetch_ok_empty(_base: str, _path: str) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
        return [], 200, None

    res = rt.load_runtime_trace_data(fetch_endpoint=fetch_ok_empty)
    assert res.mode == "api"
    assert res.api_empty_guide is True
    assert res.api_warning is None


def test_panel_language_is_traceability_not_approval() -> None:
    text = (Path(__file__).resolve().parents[1] / "airos" / "network" / "dashboard" / "components" / "runtime_trace_panel.py").read_text(
        encoding="utf-8"
    )
    assert "traceability evidence, not approval evidence" in text.lower()

