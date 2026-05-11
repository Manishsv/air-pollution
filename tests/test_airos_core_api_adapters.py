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


def test_get_adapters_lists_current_descriptors(api_client: TestClient) -> None:
    r = api_client.get("/adapters")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {x.get("adapter_id") for x in body if isinstance(x, dict)}
    assert "openaq_air_quality_adapter" in ids
    assert "open_meteo_weather_adapter" in ids
    assert "osm_geospatial_adapter" in ids

    one = [x for x in body if x.get("adapter_id") == "openaq_air_quality_adapter"][0]
    for k in ["adapter_id", "adapter_type", "source_system_type", "output_contracts", "safety", "configuration"]:
        assert k in one
    _assert_no_abs_paths(one)


@pytest.mark.parametrize(
    "adapter_id",
    ["openaq_air_quality_adapter", "open_meteo_weather_adapter", "osm_geospatial_adapter"],
)
def test_get_adapter_returns_full_descriptor(api_client: TestClient, adapter_id: str) -> None:
    r = api_client.get(f"/adapters/{adapter_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["adapter_id"] == adapter_id
    _assert_no_abs_paths(d)

    txt = str(d).lower()
    assert "dynamic plugin" not in txt
    assert "exec(" not in txt
    assert "import " not in txt
    assert "produces_final_decisions" in txt

    # No secret values should be present in responses.
    assert "-----begin" not in txt
    assert "ghp_" not in txt
    assert "bearer " not in txt


def test_unknown_adapter_id_returns_404(api_client: TestClient) -> None:
    r = api_client.get("/adapters/not_a_real_adapter_xx")
    assert r.status_code == 404
    detail = r.json()["detail"]
    _assert_no_abs_paths(detail)

