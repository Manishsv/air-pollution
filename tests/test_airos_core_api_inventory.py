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


def test_get_inventory_static(api_client: TestClient) -> None:
    r = api_client.get("/inventory")
    assert r.status_code == 200
    body = r.json()
    assert "contracts" in body
    assert "apps" in body
    assert "adapters" in body
    assert "catalogs" in body
    assert "deployments" in body
    assert body.get("runtime", {}).get("included") is False
    assert body.get("safety", {}).get("review_support_only") is True
    _assert_no_abs_paths(body)


def test_get_inventory_include_runtime(api_client: TestClient) -> None:
    r = api_client.get("/inventory?include_runtime=true")
    assert r.status_code == 200
    body = r.json()
    rt = body.get("runtime") or {}
    assert rt.get("included") is True
    assert "record_count" in rt
    assert "run_count" in rt
    assert "output_count" in rt
    _assert_no_abs_paths(body)

