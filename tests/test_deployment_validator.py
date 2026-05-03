from __future__ import annotations

from pathlib import Path

import yaml

from tools.deployment_runner.validate_deployment import validate_deployment


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_yaml(path: Path, obj: object) -> None:
    path.write_text(yaml.safe_dump(obj, sort_keys=False), encoding="utf-8")


def test_flood_local_demo_validates() -> None:
    deployment_dir = REPO_ROOT / "deployments" / "examples" / "flood_local_demo"
    s = validate_deployment(deployment_dir=deployment_dir, repo_root=REPO_ROOT)
    assert s.errors == []
    assert s.deployment_id == "flood_local_demo"
    assert "flood_risk" in s.enabled_domains
    assert s.provider_count >= 1
    assert s.application_count >= 1


def test_missing_required_file_fails(tmp_path: Path) -> None:
    # Only create deployment_profile + provider_registry; omit application_registry.yaml.
    _write_yaml(
        tmp_path / "deployment_profile.yaml",
        {
            "deployment_id": "x",
            "deployment_name": "x",
            "deployment_type": "single_agency",
            "enabled_domains": ["flood_risk"],
            "environment": "local",
            "no_secrets_notice": "no secrets",
        },
    )
    _write_yaml(tmp_path / "provider_registry.yaml", {"providers": []})
    s = validate_deployment(deployment_dir=tmp_path, repo_root=REPO_ROOT)
    assert s.errors
    assert any("application_registry.yaml" in e for e in s.errors)


def test_missing_provider_contract_fails(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "deployment_profile.yaml",
        {
            "deployment_id": "x",
            "deployment_name": "x",
            "deployment_type": "single_agency",
            "enabled_domains": ["air_quality"],
            "environment": "local",
            "no_secrets_notice": "no secrets",
        },
    )
    _write_yaml(
        tmp_path / "provider_registry.yaml",
        {
            "providers": [
                {
                    "provider_id": "p1",
                    "domain_ids": ["air_quality"],
                    "provider_contract": "provider_contract_that_does_not_exist",
                    "input_method": "file",
                    "output_platform_object_types": ["Observation"],
                }
            ]
        },
    )
    _write_yaml(
        tmp_path / "application_registry.yaml",
        {
            "applications": [
                {
                    "application_id": "a1",
                    "domain_id": "air_quality",
                    "consumer_contracts": ["consumer_decision_packet_air_quality"],
                    "safety_gates_and_blocked_uses": ["specifications/domain_specs/air_quality.v1.yaml#blocked_uses"],
                }
            ]
        },
    )
    s = validate_deployment(deployment_dir=tmp_path, repo_root=REPO_ROOT)
    assert any("provider_contract not found" in e for e in s.errors)


def test_missing_fixture_path_fails(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "deployment_profile.yaml",
        {
            "deployment_id": "x",
            "deployment_name": "x",
            "deployment_type": "single_agency",
            "enabled_domains": ["flood_risk"],
            "environment": "local",
            "no_secrets_notice": "no secrets",
        },
    )
    _write_yaml(
        tmp_path / "provider_registry.yaml",
        {
            "providers": [
                {
                    "provider_id": "p1",
                    "domain_ids": ["flood_risk"],
                    "provider_contract": "provider_rainfall_observation_feed",
                    "input_method": "file",
                    "output_platform_object_types": ["Observation"],
                    "fixture_path": "specifications/examples/flood/does_not_exist.json",
                }
            ]
        },
    )
    _write_yaml(
        tmp_path / "application_registry.yaml",
        {
            "applications": [
                {
                    "application_id": "a1",
                    "domain_id": "flood_risk",
                    "consumer_contracts": ["consumer_flood_risk_dashboard"],
                    "safety_gates_and_blocked_uses": ["specifications/domain_specs/flood_risk.v1.yaml#blocked_uses"],
                }
            ]
        },
    )
    s = validate_deployment(deployment_dir=tmp_path, repo_root=REPO_ROOT)
    assert any("fixture_path not found" in e for e in s.errors)


def test_secret_like_value_detected(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "deployment_profile.yaml",
        {
            "deployment_id": "x",
            "deployment_name": "x",
            "deployment_type": "single_agency",
            "enabled_domains": ["air_quality"],
            "environment": "local",
            "no_secrets_notice": "no secrets",
        },
    )
    _write_yaml(
        tmp_path / "provider_registry.yaml",
        {
            "providers": [
                {
                    "provider_id": "p1",
                    "domain_ids": ["air_quality"],
                    "provider_contract": "provider_air_quality_observation_feed",
                    "input_method": "api",
                    "output_platform_object_types": ["Observation"],
                    "api_key": "Bearer not_a_real_token_but_should_be_caught",
                }
            ]
        },
    )
    _write_yaml(
        tmp_path / "application_registry.yaml",
        {
            "applications": [
                {
                    "application_id": "a1",
                    "domain_id": "air_quality",
                    "consumer_contracts": ["consumer_decision_packet_air_quality"],
                    "safety_gates_and_blocked_uses": ["specifications/domain_specs/air_quality.v1.yaml#blocked_uses"],
                }
            ]
        },
    )
    s = validate_deployment(deployment_dir=tmp_path, repo_root=REPO_ROOT)
    assert any("secret-like" in e for e in s.errors)

