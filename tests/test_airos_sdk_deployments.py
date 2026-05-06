from __future__ import annotations

from urban_platform.sdk import get_deployment_profile, list_deployment_ids, list_deployment_profiles


def test_sdk_deployments_list_includes_known_examples() -> None:
    ids = list_deployment_ids()
    assert "flood_local_demo" in ids
    assert "program_reporting_state_demo" in ids

    profs = list_deployment_profiles()
    by_id = {p.get("deployment_id"): p for p in profs if isinstance(p, dict)}
    assert by_id["flood_local_demo"]["provider_count"] >= 0
    assert by_id["program_reporting_state_demo"]["application_count"] >= 0


def test_sdk_get_deployment_profile_returns_detail() -> None:
    d = get_deployment_profile("flood_local_demo")
    assert isinstance(d, dict)
    assert d.get("deployment_id") == "flood_local_demo"
    assert "deployment_profile" in d
    assert "provider_registrations" in d


def test_sdk_unknown_deployment_returns_none() -> None:
    assert get_deployment_profile("does_not_exist") is None

