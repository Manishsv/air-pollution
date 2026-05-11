from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


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


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from airos.network.api.app import create_app

    return TestClient(create_app())


def test_health_ok(api_client: TestClient) -> None:
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "airos-core", "mode": "pilot-runtime"}


def test_manifest_lists_contract_keys(api_client: TestClient) -> None:
    r = api_client.get("/manifest")
    assert r.status_code == 200
    body = r.json()
    assert "artifact_count" in body
    assert body["artifact_count"] > 10
    assert "consumer_city_program_submission" in body["contract_keys"]


def test_post_valid_consumer_city_program_submission(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    r = api_client.post("/records/consumer_city_program_submission", json=sample)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "accepted"
    assert out["contract_key"] == "consumer_city_program_submission"
    assert isinstance(out["payload_hash"], str) and len(out["payload_hash"]) == 64
    assert isinstance(out.get("validation_receipt_id"), str) and out["validation_receipt_id"]

    store_dir = Path(os.environ["AIROS_STORE_DIR"])
    assert (store_dir / "records.jsonl").is_file()
    assert (store_dir / "validation_receipts.jsonl").is_file()


def test_post_invalid_submission_returns_400(api_client: TestClient) -> None:
    r = api_client.post("/records/consumer_city_program_submission", json={"submission_id": "x"})
    assert r.status_code == 400
    detail = r.json().get("detail", {})
    assert detail.get("message") == "Record validation failed."
    assert detail.get("contract_key") == "consumer_city_program_submission"
    assert isinstance(detail.get("validation_receipt_id"), str) and detail["validation_receipt_id"]
    assert "errors" in detail


def test_program_reporting_application_run_completed(api_client: TestClient) -> None:
    _ingest_both_sample_cities(api_client)
    body = _run_program_reporting_app(api_client)
    assert body["status"] == "completed"
    assert body["records_processed"] == 2
    assert body["outputs_generated"] == 3
    assert body["application_id"] == "program_reporting_review_packet"

    # Runs are first-class metadata.
    run_id = body["run_id"]
    r0 = api_client.get("/runs")
    assert r0.status_code == 200
    assert any(x.get("run_id") == run_id and x.get("status") == "completed" for x in r0.json())

    r1 = api_client.get(f"/runs/{run_id}")
    assert r1.status_code == 200
    run = r1.json()
    assert run["run_id"] == run_id
    assert run["deployment_id"] == "program_reporting_state_demo"
    assert run["application_id"] == "program_reporting_review_packet"
    assert run["status"] == "completed"
    assert run["records_processed"] == 2
    assert run["outputs_generated"] == 3
    assert len(run.get("input_refs") or []) == 2
    assert len(run.get("output_refs") or []) >= 1

    # Filters.
    rf_dep = api_client.get("/runs", params={"deployment_id": "program_reporting_state_demo"})
    assert rf_dep.status_code == 200
    assert any(x.get("run_id") == run_id for x in rf_dep.json())
    rf_app = api_client.get("/runs", params={"application_id": "program_reporting_review_packet"})
    assert rf_app.status_code == 200
    assert any(x.get("run_id") == run_id for x in rf_app.json())
    rf_status = api_client.get("/runs", params={"status": "completed"})
    assert rf_status.status_code == 200
    assert any(x.get("run_id") == run_id for x in rf_status.json())

    from airos.os.storage import FileAirOsStore

    store = FileAirOsStore(Path(os.environ["AIROS_STORE_DIR"]))
    pkts = store.list_outputs(deployment_id="program_reporting_state_demo", contract_key="consumer_fund_release_review_packet")
    assert len(pkts) >= 2
    sums = store.list_outputs(
        deployment_id="program_reporting_state_demo", contract_key="consumer_program_reporting_state_summary"
    )
    assert len(sums) >= 1

    audits = store.list_audit_events(deployment_id="program_reporting_state_demo")
    actions = {e.action for e in audits}
    assert "application_run_started" in actions
    assert "application_run_completed" in actions
    assert "output_generated" in actions


def test_get_outputs_review_packets(api_client: TestClient) -> None:
    _ingest_both_sample_cities(api_client)
    _run_program_reporting_app(api_client)
    r = api_client.get("/outputs", params={"contract_key": "consumer_fund_release_review_packet"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2
    assert all(x.get("contract_key") == "consumer_fund_release_review_packet" for x in rows)


def test_get_outputs_state_summary(api_client: TestClient) -> None:
    _ingest_both_sample_cities(api_client)
    _run_program_reporting_app(api_client)
    r = api_client.get("/outputs", params={"contract_key": "consumer_program_reporting_state_summary"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert rows[-1]["payload"].get("city_count") == 2


def test_get_output_by_id(api_client: TestClient) -> None:
    _ingest_both_sample_cities(api_client)
    _run_program_reporting_app(api_client)
    lst = api_client.get("/outputs", params={"contract_key": "consumer_fund_release_review_packet"}).json()
    oid = lst[0]["output_id"]
    one = api_client.get(f"/outputs/{oid}")
    assert one.status_code == 200
    assert one.json()["output_id"] == oid


def test_get_audit_events(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    api_client.post("/records/consumer_city_program_submission", json=sample)
    r = api_client.get("/audit-events", params={"deployment_id": "program_reporting_state_demo"})
    assert r.status_code == 200
    events = r.json()
    assert any(e.get("action") == "record_ingested" for e in events)


def test_unknown_application_fails_closed(api_client: TestClient) -> None:
    r = api_client.post("/applications/not_an_application/runs", json={})
    assert r.status_code == 404


def test_run_without_records_returns_400(api_client: TestClient) -> None:
    r = api_client.post("/applications/program_reporting_review_packet/runs", json={})
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "No stored records found for this application run."


def test_known_builder_without_required_records_returns_400(api_client: TestClient) -> None:
    r = api_client.post("/applications/flood_risk_dashboard_payload/runs", json={})
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "No stored records found for this application run."

    # Missing-input failures should not create misleading run entries.
    lst = api_client.get("/runs")
    assert lst.status_code == 200
    assert lst.json() == []


def test_no_response_implies_automatic_fund_release(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    r1 = api_client.post("/records/consumer_city_program_submission", json=sample)
    r2 = api_client.post(
        "/applications/program_reporting_review_packet/runs",
        json={
            "deployment_id": "program_reporting_state_demo",
            "program_id": "stormwater_resilience_grant_2026",
            "reporting_period": "2026_Q1",
        },
    )
    for r in (r1, r2):
        text = json.dumps(r.json()).lower()
        assert "will be automatically released" not in text
        assert "automatic fund release authorized" not in text
