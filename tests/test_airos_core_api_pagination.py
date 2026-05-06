from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_platform.storage.models import StoredRun


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from urban_platform.api.app import create_app

    return TestClient(create_app())


def test_runs_paginated_envelope_and_legacy_array(api_client: TestClient) -> None:
    # create a couple runs directly via store
    from urban_platform.storage.file_store import FileAirOsStore

    store = FileAirOsStore(Path(os.environ["AIROS_STORE_DIR"]))
    store.put_run(
        StoredRun(
            run_id="run_p1",
            deployment_id="dep_p",
            application_id="app_p",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    store.put_run(
        StoredRun(
            run_id="run_p2",
            deployment_id="dep_p",
            application_id="app_p",
            status="failed",
            started_at="2026-05-06T00:01:00Z",
        )
    )

    r0 = api_client.get("/runs")
    assert r0.status_code == 200
    assert isinstance(r0.json(), list)

    r1 = api_client.get("/runs?paginated=true&limit=1&offset=0")
    assert r1.status_code == 200
    body = r1.json()
    assert set(body.keys()) >= {"items", "count", "total", "limit", "offset", "next_offset", "has_more"}
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["count"] == 1
    assert body["total"] >= 2
    assert body["next_offset"] == 1
    assert body["has_more"] is True


def test_limit_max_enforced(api_client: TestClient) -> None:
    r = api_client.get("/runs?paginated=true&limit=999&offset=0")
    assert r.status_code == 422


def test_outputs_filter_by_run_id_with_pagination(api_client: TestClient) -> None:
    # create outputs with metadata.run_id
    from urban_platform.storage.file_store import FileAirOsStore
    from urban_platform.storage.models import StoredOutput

    store = FileAirOsStore(Path(os.environ["AIROS_STORE_DIR"]))
    store.put_output(
        StoredOutput(
            output_id="out_r1",
            deployment_id="dep_o",
            contract_key="consumer_x",
            payload={"x": 1},
            generated_at="2026-05-06T00:00:00Z",
            generated_by="app",
            metadata={"run_id": "run_filter"},
        )
    )
    store.put_output(
        StoredOutput(
            output_id="out_r2",
            deployment_id="dep_o",
            contract_key="consumer_x",
            payload={"x": 2},
            generated_at="2026-05-06T00:01:00Z",
            generated_by="app",
            metadata={"run_id": "other"},
        )
    )

    r = api_client.get("/outputs?run_id=run_filter&paginated=true&limit=10&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["output_id"] == "out_r1"


def test_audit_events_filter_by_action_and_resource_type(api_client: TestClient) -> None:
    from urban_platform.storage.file_store import FileAirOsStore
    from urban_platform.storage.models import AuditEvent

    store = FileAirOsStore(Path(os.environ["AIROS_STORE_DIR"]))
    store.append_audit_event(
        AuditEvent(
            event_id="ae_1",
            deployment_id="dep_a",
            actor="core_api",
            action="output_generated",
            resource_type="output",
            resource_id="out_1",
            occurred_at="2026-05-06T00:00:00Z",
        )
    )
    store.append_audit_event(
        AuditEvent(
            event_id="ae_2",
            deployment_id="dep_a",
            actor="core_api",
            action="record_ingested",
            resource_type="record",
            resource_id="rec_1",
            occurred_at="2026-05-06T00:00:01Z",
        )
    )

    r = api_client.get("/audit-events?action=output_generated&resource_type=output&paginated=true&limit=10&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["event_id"] == "ae_1"

