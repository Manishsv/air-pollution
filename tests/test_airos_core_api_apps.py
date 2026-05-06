from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urban_platform.sdk.apps import list_app_ids


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


def test_get_apps_lists_program_reporting_and_flood(api_client: TestClient) -> None:
    r = api_client.get("/apps")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {x.get("app_id") for x in body if isinstance(x, dict)}
    assert "program_reporting_review" in ids
    assert "flood_risk_review" in ids

    # summary fields present
    pr = [x for x in body if x.get("app_id") == "program_reporting_review"][0]
    for k in ["app_id", "name", "input_contracts", "output_contracts", "safety"]:
        assert k in pr
    assert pr["input_contracts"]
    assert pr["output_contracts"]
    assert isinstance(pr["safety"], dict)
    _assert_no_abs_paths(pr)


def test_get_apps_list_matches_sdk_list_app_ids(api_client: TestClient) -> None:
    """
    GET /apps and urban_platform.sdk.apps both load descriptors via specs_helpers;
    they must expose the same app_id set (regression guard after shared-loader refactor).
    """
    r = api_client.get("/apps")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    api_ids = {
        str(x.get("app_id") or "").strip()
        for x in body
        if isinstance(x, dict) and str(x.get("app_id") or "").strip()
    }
    assert api_ids == set(list_app_ids())


def test_get_app_returns_full_descriptor(api_client: TestClient) -> None:
    r = api_client.get("/apps/program_reporting_review")
    assert r.status_code == 200
    d = r.json()
    assert d["app_id"] == "program_reporting_review"
    assert "decision_logic" in d and "builder_ids" in d["decision_logic"]
    assert "deployment_examples" in d
    assert "provenance" in d
    _assert_no_abs_paths(d)

    # Descriptor is metadata only; it should not imply plugin loading or final decision automation.
    txt = str(d).lower()
    assert "dynamic plugin" not in txt
    assert "import " not in txt
    assert "exec(" not in txt
    assert "authorize fund release" in txt


def test_get_flood_app_returns_full_descriptor(api_client: TestClient) -> None:
    r = api_client.get("/apps/flood_risk_review")
    assert r.status_code == 200
    d = r.json()
    assert d["app_id"] == "flood_risk_review"
    _assert_no_abs_paths(d)
    txt = str(d).lower()
    assert "no emergency orders" in txt


def test_unknown_app_id_returns_404(api_client: TestClient) -> None:
    r = api_client.get("/apps/not_a_real_app_id_xx")
    assert r.status_code == 404
    detail = r.json()["detail"]
    _assert_no_abs_paths(detail)

