from __future__ import annotations

import os


def test_default_mode_is_file(monkeypatch) -> None:
    monkeypatch.delenv("AIROS_DASHBOARD_DATA_MODE", raising=False)
    from review_dashboard.components import flood_panel

    res = flood_panel.load_flood_dashboard_data(fetch_outputs=lambda _b, _ck: ([], 200, None))
    assert res.mode == "file"
    assert res.dashboard_payload is not None


def test_api_mode_unwraps_payload_and_picks_latest(monkeypatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://example.test")
    from review_dashboard.components import flood_panel

    dash_rows = [
        {"output_id": "o1", "contract_key": "consumer_flood_risk_dashboard", "payload": {"generated_at": "2026-01-01T00:00:00Z", "risk_summary": {}, "risk_areas": []}},
        {"output_id": "o2", "contract_key": "consumer_flood_risk_dashboard", "payload": {"generated_at": "2026-02-01T00:00:00Z", "risk_summary": {"overall_risk_level": "low"}, "risk_areas": []}},
    ]
    pkt_rows = [{"payload": {"packet_id": "p1", "risk_assessment": {}, "area_id": "a1"}}]
    task_rows = [{"payload": {"task_id": "t1", "source_packet_id": "p1"}}]

    def fetch(_base: str, ck: str):
        if ck == "consumer_flood_risk_dashboard":
            return dash_rows, 200, None
        if ck == "consumer_flood_decision_packet":
            return pkt_rows, 200, None
        if ck == "consumer_field_verification_task":
            return task_rows, 200, None
        return [], 200, None

    res = flood_panel.load_flood_dashboard_data(fetch_outputs=fetch)
    assert res.mode == "api"
    assert res.dashboard_payload is not None
    assert res.dashboard_payload.get("generated_at") == "2026-02-01T00:00:00Z"
    assert len(res.decision_packets) == 1
    assert len(res.field_tasks) == 1


def test_api_mode_accepts_direct_payload_shapes(monkeypatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://example.test")
    from review_dashboard.components import flood_panel

    def fetch(_base: str, ck: str):
        if ck == "consumer_flood_risk_dashboard":
            return [{"generated_at": "2026-03-01T00:00:00Z", "risk_summary": {}, "risk_areas": []}], 200, None
        if ck == "consumer_flood_decision_packet":
            return [{"packet_id": "p2", "risk_assessment": {}, "area_id": "a2"}], 200, None
        if ck == "consumer_field_verification_task":
            return [{"task_id": "t2", "source_packet_id": "p2"}], 200, None
        return [], 200, None

    res = flood_panel.load_flood_dashboard_data(fetch_outputs=fetch)
    assert res.mode == "api"
    assert res.dashboard_payload is not None
    assert res.decision_packets and res.field_tasks


def test_api_mode_handles_404_or_empty_gracefully(monkeypatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://example.test")
    from review_dashboard.components import flood_panel

    def fetch(_base: str, _ck: str):
        return [], 404, "Not found"

    res = flood_panel.load_flood_dashboard_data(fetch_outputs=fetch)
    assert res.mode == "api"
    # Warning should be present, but it should not crash or require outputs.
    assert res.api_warning is not None
    assert res.dashboard_payload is None or isinstance(res.dashboard_payload, dict)


def test_api_mode_handles_connection_error_gracefully(monkeypatch) -> None:
    monkeypatch.setenv("AIROS_DASHBOARD_DATA_MODE", "api")
    monkeypatch.setenv("AIROS_API_BASE_URL", "http://example.test")
    from review_dashboard.components import flood_panel

    def fetch(_base: str, _ck: str):
        return None, None, "Connection refused"

    res = flood_panel.load_flood_dashboard_data(fetch_outputs=fetch)
    assert res.mode == "api"
    assert res.api_warning is not None

