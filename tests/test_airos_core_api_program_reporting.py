from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_dir = tmp_path / "api_store"
    monkeypatch.setenv("AIROS_STORE_DIR", str(store_dir))
    # Import after env is set so settings pick up the test directory.
    from urban_platform.api.app import create_app

    return TestClient(create_app())


def test_health_ok(api_client: TestClient) -> None:
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "airos-core", "mode": "pilot-runtime"}


def test_post_valid_submission_accepted_and_stored(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    r = api_client.post("/program-reporting/submissions", json=sample)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "accepted"
    assert out["contract_key"] == "consumer_city_program_submission"
    assert out["record_id"] == "rec_api_program_reporting_state_demo_sub_city_demo_a_2026q1"
    assert isinstance(out["payload_hash"], str) and len(out["payload_hash"]) == 64
    assert "warnings" in out

    store_dir = Path(os.environ["AIROS_STORE_DIR"])
    assert (store_dir / "records.jsonl").is_file()


def test_post_invalid_submission_returns_400(api_client: TestClient) -> None:
    r = api_client.post("/program-reporting/submissions", json={"submission_id": "x"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "errors" in detail


def test_run_after_two_submissions_completed_and_outputs(api_client: TestClient) -> None:
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
    assert api_client.post("/program-reporting/submissions", json=a).status_code == 200
    assert api_client.post("/program-reporting/submissions", json=b).status_code == 200

    r = api_client.post("/program-reporting/run", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["submissions_processed"] == 2
    assert body["review_packets_generated"] == 2
    assert len(body["outputs"]) >= 3

    from urban_platform.storage import FileAirOsStore

    store = FileAirOsStore(Path(os.environ["AIROS_STORE_DIR"]))
    pkts = store.list_outputs(deployment_id="program_reporting_state_demo", contract_key="consumer_fund_release_review_packet")
    assert len(pkts) >= 2
    summaries = store.list_outputs(
        deployment_id="program_reporting_state_demo", contract_key="internal_program_reporting_state_summary_demo"
    )
    assert len(summaries) >= 1
    audits = store.list_audit_events(deployment_id="program_reporting_state_demo")
    actions = {e.action for e in audits}
    assert "program_reporting_run_started" in actions
    assert "program_reporting_run_completed" in actions
    assert "program_reporting_output_generated" in actions


def test_get_review_packets_and_state_summary(api_client: TestClient) -> None:
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
    api_client.post("/program-reporting/submissions", json=a)
    api_client.post("/program-reporting/submissions", json=b)
    api_client.post("/program-reporting/run", json={})

    pr = api_client.get("/program-reporting/review-packets")
    assert pr.status_code == 200
    packets = pr.json()
    assert isinstance(packets, list)
    assert len(packets) == 2
    for pkt in packets:
        assert pkt.get("packet_id", "").startswith("fr_")

    sr = api_client.get("/program-reporting/state-summary")
    assert sr.status_code == 200
    summary = sr.json()
    assert summary.get("city_count") == 2


def test_get_audit_events(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    api_client.post("/program-reporting/submissions", json=sample)
    r = api_client.get("/audit-events", params={"deployment_id": "program_reporting_state_demo"})
    assert r.status_code == 200
    events = r.json()
    assert isinstance(events, list)
    assert any(e.get("action") == "program_reporting_submission_ingested" for e in events)


def test_run_without_submissions_returns_400(api_client: TestClient) -> None:
    r = api_client.post("/program-reporting/run", json={})
    assert r.status_code == 400
    assert "No stored city program submissions found" in r.json()["detail"]["message"]


def test_responses_do_not_imply_automatic_fund_release(api_client: TestClient) -> None:
    sample = json.loads(
        (REPO_ROOT / "specifications/examples/program_reporting/city_program_submission.sample.json").read_text(
            encoding="utf-8"
        )
    )
    r1 = api_client.post("/program-reporting/submissions", json=sample)
    r2 = api_client.post("/program-reporting/run", json={})
    for label, r in (("sub", r1), ("run", r2)):
        text = json.dumps(r.json()).lower()
        assert "will be automatically released" not in text
        assert "automatic fund release authorized" not in text
        assert "disbursement completed" not in text
        if r.status_code == 200:
            for w in r.json().get("warnings", []):
                assert isinstance(w, str)


def test_state_summary_404_when_missing(api_client: TestClient) -> None:
    r = api_client.get("/program-reporting/state-summary")
    assert r.status_code == 404
