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

