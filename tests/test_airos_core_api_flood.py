from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from urban_platform.api.app import create_app

    return TestClient(create_app())


def _post_fixture(client: TestClient, contract_key: str, rel_path: str) -> None:
    payload = json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    r = client.post(f"/records/{contract_key}?deployment_id=flood_local_demo", json=payload)
    assert r.status_code == 200


def test_flood_end_to_end_generic_api(api_client: TestClient) -> None:
    _post_fixture(api_client, "provider_rainfall_observation_feed", "specifications/examples/flood/rainfall_observation.sample.json")
    _post_fixture(api_client, "provider_flood_incident_feed", "specifications/examples/flood/flood_incident.sample.json")
    _post_fixture(api_client, "provider_drainage_asset_feed", "specifications/examples/flood/drainage_asset.sample.json")

    run = api_client.post("/applications/flood_risk_dashboard_payload/runs", json={"deployment_id": "flood_local_demo"})
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["application_id"] == "flood_risk_dashboard_payload"
    assert body["records_processed"] >= 3
    assert body["outputs_generated"] >= 3

    run_id = body["run_id"]
    runs = api_client.get("/runs", params={"deployment_id": "flood_local_demo", "application_id": "flood_risk_dashboard_payload"})
    assert runs.status_code == 200
    assert any(x.get("run_id") == run_id and x.get("status") == "completed" for x in runs.json())

    one = api_client.get(f"/runs/{run_id}")
    assert one.status_code == 200
    got = one.json()
    assert got["deployment_id"] == "flood_local_demo"
    assert got["application_id"] == "flood_risk_dashboard_payload"
    assert got["status"] == "completed"
    assert len(got.get("input_refs") or []) >= 3
    assert len(got.get("output_refs") or []) >= 1

    dash = api_client.get("/outputs", params={"contract_key": "consumer_flood_risk_dashboard"})
    assert dash.status_code == 200
    assert len(dash.json()) >= 1

    packets = api_client.get("/outputs", params={"contract_key": "consumer_flood_decision_packet"})
    assert packets.status_code == 200
    assert len(packets.json()) >= 1

    tasks = api_client.get("/outputs", params={"contract_key": "consumer_field_verification_task"})
    assert tasks.status_code == 200
    assert len(tasks.json()) >= 1

    audits = api_client.get("/audit-events", params={"deployment_id": "flood_local_demo"})
    assert audits.status_code == 200
    actions = {e.get("action") for e in audits.json()}
    assert "application_run_started" in actions
    assert "application_run_completed" in actions
    assert "output_generated" in actions

    # Safety: do not imply emergency orders / evacuation / dispatch.
    # Explicit disclaimers like "no emergency orders" are allowed.
    blob = json.dumps(body).lower()
    for forbidden in ("evacuation", "dispatch", "evacuate", "issue emergency orders", "evacuation order"):
        assert forbidden not in blob


def test_flood_missing_required_records_returns_400(api_client: TestClient) -> None:
    _post_fixture(api_client, "provider_rainfall_observation_feed", "specifications/examples/flood/rainfall_observation.sample.json")
    r = api_client.post("/applications/flood_risk_dashboard_payload/runs", json={"deployment_id": "flood_local_demo"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "missing_contract_keys" in detail
    assert "provider_flood_incident_feed" in detail["missing_contract_keys"]
    assert "provider_drainage_asset_feed" in detail["missing_contract_keys"]

    lst = api_client.get("/runs")
    assert lst.status_code == 200
    assert lst.json() == []

