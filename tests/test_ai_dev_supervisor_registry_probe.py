from __future__ import annotations

from pathlib import Path

from tools.ai_dev_supervisor.registry_probe import check_registry_hygiene, probe_registry_hygiene


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_registry_probe_happy_path_on_repo_samples() -> None:
    r = probe_registry_hygiene(REPO_ROOT)
    assert r.errors == []
    assert r.provider_count >= 1
    assert r.application_count >= 1
    assert r.missing_manifest_references == []
    # Example references may be incomplete while registries are still early and
    # runtime registry loading is not enabled yet; the probe must surface them as risks.
    if r.missing_example_references:
        assert r.risks


def test_registry_probe_detects_missing_manifest_and_examples() -> None:
    spec_root = REPO_ROOT / "specifications"
    manifest = {"artifacts": {"provider_ok": {"schema_path": "x", "contract_type": "provider"}}, "examples": {}}

    provider_registry = {
        "providers": [
            {
                "provider_id": "p1",
                "provider_contract": "provider_missing",
                "examples": ["examples/does_not_exist/sample.json"],
                "status": "reference",
                "input_method": "api",
            }
        ]
    }
    application_registry = {
        "applications": [
            {
                "application_id": "a1",
                "consumer_contracts": ["consumer_missing"],
                "examples": ["example_missing_key"],
                "payload_builders": [],
                "safety_gates_and_blocked_uses": [],
            }
        ]
    }

    r = check_registry_hygiene(
        spec_root=spec_root,
        manifest=manifest,
        provider_registry=provider_registry,
        application_registry=application_registry,
    )
    assert any("provider:p1 provider_contract:provider_missing" in x for x in r.missing_manifest_references)
    assert any("application:a1 consumer_contract:consumer_missing" in x for x in r.missing_manifest_references)
    assert r.missing_example_references  # at least one missing example path/key
    assert r.risks

