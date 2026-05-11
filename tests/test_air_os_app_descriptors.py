from __future__ import annotations

from pathlib import Path

import yaml

from airos.os.deployments import builder_registry
from airos.os.specifications.conformance import SPEC_ROOT, Draft202012Validator, load_manifest, validator_for_schema_file


def _spec_path(rel: str) -> Path:
    return (SPEC_ROOT / rel).resolve()


def _load_descriptor(rel: str) -> dict:
    p = _spec_path(rel)
    with open(p, encoding="utf-8") as f:
        obj = yaml.safe_load(f)
    assert isinstance(obj, dict)
    return obj


def test_app_descriptor_schema_is_valid_draft_2020_12() -> None:
    schema_path = _spec_path("platform_objects/air_os_app_descriptor.v1.schema.json")
    assert schema_path.exists()
    import json

    doc = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(doc)


def test_program_reporting_descriptor_validates_and_references_known_keys() -> None:
    m = load_manifest()
    arts = m.get("artifacts") or {}

    desc = _load_descriptor("app_descriptors/program_reporting_review.v1.yaml")
    v = validator_for_schema_file(str(_spec_path(arts["platform_air_os_app_descriptor"]["schema_path"])))
    v.validate(desc)

    for k in desc["input_contracts"]:
        assert k in arts
    for k in desc["output_contracts"]:
        assert k in arts

    for bid in desc["decision_logic"]["builder_ids"]:
        assert builder_registry.has_builder(bid)

    for ex in desc["deployment_examples"]:
        assert Path(ex["path"]).exists()

    assert desc["safety"]["blocked_uses"]
    assert desc["safety"]["review_support_only"] is True
    assert desc["safety"]["human_review_required"] is True
    # No descriptor should claim automation of final decisions.
    txt = yaml.safe_dump(desc).lower()
    assert "automatic_fund_release" in txt
    assert "authorize fund release" in txt or "does not authorize fund release" in txt


def test_flood_descriptor_validates_and_references_known_keys() -> None:
    m = load_manifest()
    arts = m.get("artifacts") or {}

    desc = _load_descriptor("app_descriptors/flood_risk_review.v1.yaml")
    v = validator_for_schema_file(str(_spec_path(arts["platform_air_os_app_descriptor"]["schema_path"])))
    v.validate(desc)

    for k in desc["input_contracts"]:
        assert k in arts
    for k in desc["output_contracts"]:
        assert k in arts

    for bid in desc["decision_logic"]["builder_ids"]:
        assert builder_registry.has_builder(bid)

    for ex in desc["deployment_examples"]:
        assert Path(ex["path"]).exists()

    assert desc["safety"]["blocked_uses"]
    assert desc["safety"]["review_support_only"] is True
    assert desc["safety"]["human_review_required"] is True
    txt = yaml.safe_dump(desc).lower()
    assert "emergency_orders" in txt
    assert "no emergency orders" in txt

