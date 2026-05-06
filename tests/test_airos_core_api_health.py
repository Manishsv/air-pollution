from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from urban_platform.api.app import create_app

    return TestClient(create_app())


def test_health_live_ok(api_client: TestClient) -> None:
    r = api_client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "airos-core", "check": "live"}


def test_health_ready_reports_checks_and_is_safe(api_client: TestClient, tmp_path: Path) -> None:
    r = api_client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body.get("service") == "airos-core"
    assert body.get("check") == "ready"
    assert body.get("status") in ("ready", "not_ready")
    checks = body.get("checks")
    assert isinstance(checks, list) and checks

    names = {c.get("name") for c in checks if isinstance(c, dict)}
    for required in ("manifest", "contracts", "apps", "adapters", "catalogs", "deployments", "store", "builder_registry"):
        assert required in names

    # No absolute local paths should leak (store dir is temporary).
    dump = json.dumps(body)
    assert str(tmp_path.resolve()) not in dump
    assert os.environ["AIROS_STORE_DIR"] not in dump


def test_health_ready_is_ready_for_fresh_empty_store_dir(api_client: TestClient, tmp_path: Path) -> None:
    store_dir = tmp_path / "api_store"
    assert not store_dir.exists()

    r = api_client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ready"

    # Readiness may create the store directory (via store init), but must not create JSONL members.
    assert store_dir.exists() and store_dir.is_dir()
    assert not (store_dir / "records.jsonl").exists()
    assert not (store_dir / "outputs.jsonl").exists()
    assert not (store_dir / "runs.jsonl").exists()
    assert not (store_dir / "validation_receipts.jsonl").exists()
    assert not (store_dir / "audit_events.jsonl").exists()


def test_health_ready_not_ready_if_store_path_is_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Use a *file* path for AIROS_STORE_DIR; readiness should report not_ready,
    # and must not error out due to dependency injection.
    p = tmp_path / "not_a_dir"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setenv("AIROS_STORE_DIR", str(p))

    from urban_platform.api.app import create_app

    client = TestClient(create_app())
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "not_ready"

    checks = body.get("checks") or []
    store_checks = [c for c in checks if isinstance(c, dict) and c.get("name") == "store"]
    assert store_checks and store_checks[0].get("status") == "fail"

    # No absolute path leakage.
    dump = json.dumps(body)
    assert str(tmp_path.resolve()) not in dump

