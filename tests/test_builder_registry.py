from __future__ import annotations

import pytest

from urban_platform.deployments.builder_registry import get_builder, list_builders


def test_list_builders_includes_current_demo_application_ids() -> None:
    ids = {b.application_id for b in list_builders()}
    assert "flood_risk_dashboard_payload" in ids
    assert "flood_decision_packets" in ids
    assert "flood_field_verification_tasks" in ids
    assert "program_reporting_review_packet" in ids


def test_get_builder_returns_metadata() -> None:
    b = get_builder("flood_risk_dashboard_payload")
    assert b.domain_id == "flood_risk"
    assert b.output_contract_keys
    assert b.safety_notes
    assert "build_" in b.callable_name


def test_get_builder_unknown_fails_closed() -> None:
    with pytest.raises(KeyError) as e:
        get_builder("totally_unknown_app")
    assert "Unknown application_id" in str(e.value)


def test_registry_is_not_yaml_driven() -> None:
    # Guardrail: registry module must not use dynamic imports or yaml parsing.
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "urban_platform"
        / "deployments"
        / "builder_registry.py"
    ).read_text(encoding="utf-8")
    assert "yaml" not in src
    assert "importlib" not in src
    assert "__import__" not in src

