from __future__ import annotations

import textwrap
from pathlib import Path

from urban_platform.deployments.config_loader import (
    DeploymentConfig,
    load_deployment_config,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_flood_local_demo_loads() -> None:
    cfg = load_deployment_config(_repo_root() / "deployments/examples/flood_local_demo")
    assert isinstance(cfg, DeploymentConfig)
    assert cfg.deployment_id == "flood_local_demo"
    assert "flood_risk" in cfg.enabled_domains
    assert cfg.provider_count == 3
    assert cfg.application_count == 3
    assert cfg.network_adapter_count == 0
    assert len(cfg.providers) == 3
    assert len(cfg.applications) == 3
    assert not cfg.errors


def test_program_reporting_state_demo_loads() -> None:
    cfg = load_deployment_config(_repo_root() / "deployments/examples/program_reporting_state_demo")
    assert cfg.deployment_id == "program_reporting_state_demo"
    assert "program_reporting" in cfg.enabled_domains
    assert cfg.provider_count == 0
    assert cfg.application_count == 1
    assert len(cfg.applications) == 1
    assert cfg.applications[0].application_id == "program_reporting_review_packet"
    assert not cfg.errors


def test_missing_optional_registries_do_not_crash(tmp_path: Path) -> None:
    (tmp_path / "deployment_profile.yaml").write_text(
        textwrap.dedent(
            """
            deployment_id: tmp_only
            deployment_name: Tmp
            deployment_type: single_agency
            owner_organization: X
            environment: local
            enabled_domains:
              - air_quality
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg = load_deployment_config(tmp_path)
    assert cfg.deployment_id == "tmp_only"
    assert cfg.provider_registry_document is None
    assert cfg.application_registry_document is None
    assert cfg.network_adapter_registry_document is None
    assert cfg.provider_count == 0
    assert cfg.application_count == 0


def test_config_loader_source_has_no_connector_or_plugin_hooks() -> None:
    src = (_repo_root() / "urban_platform" / "deployments" / "config_loader.py").read_text(encoding="utf-8")
    assert "urban_platform.connectors" not in src
    assert "__import__" not in src
    assert "importlib" not in src


def test_network_adapter_file_parsed_when_present(tmp_path: Path) -> None:
    (tmp_path / "deployment_profile.yaml").write_text(
        textwrap.dedent(
            """
            deployment_id: net_test
            deployment_name: Net
            deployment_type: single_agency
            owner_organization: X
            environment: local
            enabled_domains:
              - test_domain
            """
        ).strip(),
        encoding="utf-8",
    )
    (tmp_path / "provider_registry.yaml").write_text("providers: []\n", encoding="utf-8")
    (tmp_path / "application_registry.yaml").write_text("applications: []\n", encoding="utf-8")
    (tmp_path / "network_adapter_registry.yaml").write_text(
        textwrap.dedent(
            """
            adapters:
              - adapter_id: email_stub
                supported_transport: email
                supported_network_contracts:
                  - network_message_envelope_v1
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg = load_deployment_config(tmp_path)
    assert cfg.network_adapter_count == 1
    assert cfg.network_adapters[0].adapter_id == "email_stub"
