from __future__ import annotations

from urban_platform.sdk import get_reference_catalog, list_reference_catalog_ids


def test_sdk_catalog_list_includes_reference_examples() -> None:
    ids = list_reference_catalog_ids()
    assert "administrative_units_demo_in" in ids
    assert "program_catalog_demo_in" in ids
    assert "reporting_periods_demo_in" in ids


def test_sdk_get_catalog_returns_catalog() -> None:
    c = get_reference_catalog("administrative_units_demo_in")
    assert isinstance(c, dict)
    assert c.get("catalog_type") == "administrative_units"


def test_sdk_unknown_catalog_returns_none() -> None:
    assert get_reference_catalog("does_not_exist") is None

