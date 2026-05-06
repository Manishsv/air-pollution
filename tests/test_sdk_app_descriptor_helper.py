from __future__ import annotations

from urban_platform.sdk.specs_helpers import (
    get_app_descriptor_from_specs,
    load_all_app_descriptors_from_specs,
)


def test_load_all_app_descriptors_from_specs_includes_known_apps() -> None:
    descriptors = load_all_app_descriptors_from_specs(validate=True)
    ids = {str(d.get("app_id") or "").strip() for d in descriptors if isinstance(d, dict)}
    assert "program_reporting_review" in ids
    assert "flood_risk_review" in ids


def test_get_app_descriptor_from_specs_matches_known_yaml_ids() -> None:
    pr = get_app_descriptor_from_specs("program_reporting_review", validate=True)
    assert isinstance(pr, dict)
    assert pr.get("app_id") == "program_reporting_review"

    flood = get_app_descriptor_from_specs("flood_risk_review", validate=True)
    assert isinstance(flood, dict)
    assert flood.get("app_id") == "flood_risk_review"


def test_get_app_descriptor_from_specs_empty_id() -> None:
    assert get_app_descriptor_from_specs("", validate=True) is None
    assert get_app_descriptor_from_specs("   ", validate=True) is None

