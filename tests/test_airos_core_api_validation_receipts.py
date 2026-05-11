from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from airos.network.api.app import create_app

    return TestClient(create_app())


def _ingest_both_sample_cities(client: TestClient) -> None:
    a = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    b = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission_city_b.sample.json").read_text(
            encoding="utf-8"
        )
    )
    assert client.post("/records/consumer_city_program_submission", json=a).status_code == 200
    assert client.post("/records/consumer_city_program_submission", json=b).status_code == 200


def _run_program_reporting_app(client: TestClient) -> Dict[str, Any]:
    r = client.post(
        "/applications/program_reporting_review_packet/runs",
        json={
            "deployment_id": "program_reporting_state_demo",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
        },
    )
    assert r.status_code == 200
    return r.json()


def _post_fixture(client: TestClient, contract_key: str, rel_path: str) -> None:
    payload = json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    r = client.post(f"/records/{contract_key}?deployment_id=flood_local_demo", json=payload)
    assert r.status_code == 200


def test_list_and_get_validation_receipts_and_filters(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    ok = api_client.post("/records/consumer_city_program_submission", json=sample).json()
    assert isinstance(ok.get("validation_receipt_id"), str)

    bad = api_client.post("/records/consumer_city_program_submission", json={"submission_id": "x"})
    assert bad.status_code == 400
    receipt_id = bad.json()["detail"]["validation_receipt_id"]

    lst = api_client.get("/validation-receipts")
    assert lst.status_code == 200
    rows = lst.json()
    assert len(rows) >= 2

    one = api_client.get(f"/validation-receipts/{receipt_id}")
    assert one.status_code == 200
    rec = one.json()
    assert rec["receipt_id"] == receipt_id
    assert rec["status"] == "invalid"
    assert rec["contract_key"] == "consumer_city_program_submission"
    assert rec["validation_target_type"] == "record"
    assert isinstance(rec.get("errors"), list)

    # Filters
    inv = api_client.get("/validation-receipts", params={"status": "invalid"})
    assert inv.status_code == 200
    assert all(x.get("status") == "invalid" for x in inv.json())

    by_ck = api_client.get("/validation-receipts", params={"contract_key": "consumer_city_program_submission"})
    assert by_ck.status_code == 200
    assert len(by_ck.json()) >= 2

    by_type = api_client.get("/validation-receipts", params={"validation_target_type": "record"})
    assert by_type.status_code == 200
    assert all(x.get("validation_target_type") == "record" for x in by_type.json())

    missing = api_client.get("/validation-receipts/not_a_receipt")
    assert missing.status_code == 404


def test_program_reporting_and_flood_runs_create_output_receipts(api_client: TestClient) -> None:
    _ingest_both_sample_cities(api_client)
    _run_program_reporting_app(api_client)

    # Flood ingest + run
    _post_fixture(api_client, "provider_rainfall_observation_feed", "specifications/examples/flood/rainfall_observation.sample.json")
    _post_fixture(api_client, "provider_flood_incident_feed", "specifications/examples/flood/flood_incident.sample.json")
    _post_fixture(api_client, "provider_drainage_asset_feed", "specifications/examples/flood/drainage_asset.sample.json")
    flood_run = api_client.post("/applications/flood_risk_dashboard_payload/runs", json={"deployment_id": "flood_local_demo"})
    assert flood_run.status_code == 200

    outs = api_client.get("/validation-receipts", params={"validation_target_type": "output"})
    assert outs.status_code == 200
    rows = outs.json()
    assert len(rows) >= 3
    assert any(x.get("contract_key") == "consumer_fund_release_review_packet" and x.get("status") == "valid" for x in rows)
    assert any(x.get("contract_key") == "consumer_flood_risk_dashboard" and x.get("status") == "valid" for x in rows)

    # Safety: never leak stack traces in receipts.
    blob = json.dumps(rows).lower()
    assert "traceback" not in blob

    # Safety: receipts do not imply approvals/decisions.
    for forbidden in ("approved", "approval", "funds will be released", "issue emergency orders", "enforcement"):
        assert forbidden not in blob

