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
        for k, v in obj.items():
            assert not (isinstance(v, str) and v.startswith("/Users/"))
            assert not (isinstance(v, str) and v.startswith("/private/"))
            _assert_no_abs_paths(v)
    elif isinstance(obj, list):
        for x in obj:
            _assert_no_abs_paths(x)


@pytest.mark.parametrize(
    "contract_key",
    [
        "consumer_city_program_submission",
        "consumer_fund_release_review_packet",
        "provider_rainfall_observation_feed",
    ],
)
def test_contract_endpoint_returns_schema(contract_key: str, api_client: TestClient) -> None:
    r = api_client.get(f"/contracts/{contract_key}")
    assert r.status_code == 200
    body = r.json()
    assert body["contract_key"] == contract_key
    assert "schema_path" in body and body["schema_path"].startswith("specifications/")
    assert isinstance(body["schema"], dict)
    _assert_no_abs_paths(body)


def test_unknown_contract_returns_404(api_client: TestClient) -> None:
    r = api_client.get("/contracts/not_a_real_contract_key_xx")
    assert r.status_code == 404


def test_openapi_artifact_returns_helpful_400(api_client: TestClient) -> None:
    r = api_client.get("/contracts/openapi_platform_api")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "openapi" in str(detail).lower()
    _assert_no_abs_paths(detail)


def test_contracts_index_groups_by_type(api_client: TestClient) -> None:
    r = api_client.get("/contracts")
    assert r.status_code == 200
    body = r.json()
    assert "contracts" in body
    assert "consumer" in body["contracts"]
    assert "provider" in body["contracts"]
    assert "registry_contract" in body["contracts"]
    assert "network_contract" in body["contracts"]

