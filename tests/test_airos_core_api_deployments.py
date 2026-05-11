from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from airos.network.api.app import create_app

    return TestClient(create_app())


def _assert_no_abs_paths(obj) -> None:
    if isinstance(obj, dict):
        for _k, v in obj.items():
            assert not (isinstance(v, str) and (v.startswith("/Users/") or v.startswith("/private/")))
            _assert_no_abs_paths(v)
    elif isinstance(obj, list):
        for x in obj:
            _assert_no_abs_paths(x)


def test_get_deployments_lists_known_examples(api_client: TestClient) -> None:
    r = api_client.get("/deployments")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {x.get("deployment_id") for x in body if isinstance(x, dict)}
    assert "flood_local_demo" in ids
    assert "program_reporting_state_demo" in ids
    _assert_no_abs_paths(body)


def test_get_deployment_returns_detail(api_client: TestClient) -> None:
    r = api_client.get("/deployments/flood_local_demo")
    assert r.status_code == 200
    d = r.json()
    assert d.get("deployment_id") == "flood_local_demo"
    assert "deployment_profile" in d
    assert "suggested_cli_commands" in d
    _assert_no_abs_paths(d)


def test_unknown_deployment_returns_404(api_client: TestClient) -> None:
    r = api_client.get("/deployments/not_a_real_deployment_xx")
    assert r.status_code == 404
    _assert_no_abs_paths(r.json())

