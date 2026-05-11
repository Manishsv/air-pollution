from __future__ import annotations

from airos.os.sdk import get_platform_inventory


def test_sdk_inventory_static_contains_known_ids() -> None:
    inv = get_platform_inventory()
    assert inv["apps"]["app_count"] >= 1
    assert "program_reporting_review" in inv["apps"]["app_ids"]
    assert "flood_risk_review" in inv["apps"]["app_ids"]

    assert "openaq_air_quality_adapter" in inv["adapters"]["adapter_ids"]
    assert "administrative_units_demo_in" in inv["catalogs"]["catalog_ids"]
    assert "flood_local_demo" in inv["deployments"]["deployment_ids"]


def test_sdk_inventory_runtime_is_optional() -> None:
    inv = get_platform_inventory(include_runtime=False)
    assert inv["runtime"]["included"] is False

