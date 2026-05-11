from __future__ import annotations

from airos.os.sdk import apps as sdk_apps
from airos.os.sdk.specs_helpers import (
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


def test_sdk_apps_list_app_descriptors_matches_specs_helper_ids() -> None:
    """SDK apps module delegates to specs_helpers; listing should match direct load."""
    from_specs = load_all_app_descriptors_from_specs(validate=True)
    from_sdk = sdk_apps.list_app_descriptors()
    ids_specs = {str(d.get("app_id") or "").strip() for d in from_specs if isinstance(d, dict)}
    ids_sdk = {str(d.get("app_id") or "").strip() for d in from_sdk if isinstance(d, dict)}
    assert ids_specs == ids_sdk
    assert "program_reporting_review" in ids_sdk
    assert "flood_risk_review" in ids_sdk

