from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIROS_STORE_DIR", str(tmp_path / "api_store"))
    from urban_platform.api.app import create_app

    return TestClient(create_app())


def _assert_no_abs_paths(obj) -> None:
    if isinstance(obj, dict):
        for _k, v in obj.items():
            assert not (isinstance(v, str) and (v.startswith("/Users/") or v.startswith("/private/")))
            _assert_no_abs_paths(v)
    elif isinstance(obj, list):
        for x in obj:
            _assert_no_abs_paths(x)


def test_get_catalogs_lists_known_catalogs(api_client: TestClient) -> None:
    r = api_client.get("/catalogs")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {x.get("catalog_id") for x in body if isinstance(x, dict)}
    assert "administrative_units_demo_in" in ids
    assert "program_catalog_demo_in" in ids
    assert "reporting_periods_demo_in" in ids
    _assert_no_abs_paths(body)


def test_get_catalog_returns_full_catalog(api_client: TestClient) -> None:
    r = api_client.get("/catalogs/administrative_units_demo_in")
    assert r.status_code == 200
    c = r.json()
    assert c["catalog_id"] == "administrative_units_demo_in"
    assert "entries" in c
    _assert_no_abs_paths(c)


def test_unknown_catalog_returns_404(api_client: TestClient) -> None:
    r = api_client.get("/catalogs/not_a_real_catalog_xx")
    assert r.status_code == 404
    _assert_no_abs_paths(r.json())

