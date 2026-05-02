from __future__ import annotations

import json
from pathlib import Path

from tools.ai_dev_supervisor.deployment_probe import probe_deployment_examples


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_deployment_probe_detects_flood_local_demo() -> None:
    r = probe_deployment_examples(REPO_ROOT)
    assert r.examples_dir_exists is True
    keys = [d.get("deployment_key") for d in (r.deployments or [])]
    assert "flood_local_demo" in keys


def test_deployment_probe_missing_files_and_manifest_refs(tmp_path: Path) -> None:
    # Minimal fake repo root
    (tmp_path / "specifications").mkdir(parents=True)
    (tmp_path / "specifications" / "manifest.json").write_text(
        json.dumps({"artifacts": {"provider_ok": {"schema_path": "x", "contract_type": "provider"}}}) + "\n",
        encoding="utf-8",
    )
    ex_dir = tmp_path / "deployments" / "examples" / "demo1"
    ex_dir.mkdir(parents=True)

    # Only provider registry exists; missing deployment_profile.yaml, application_registry.yaml, README.md.
    (ex_dir / "provider_registry.yaml").write_text(
        (
            "registry_id: x\n"
            "version: v1\n"
            "updated_at: \"2026-05-02T00:00:00Z\"\n"
            "scope: deployment\n"
            "deployment_id: demo1\n"
            "providers:\n"
            "  - provider_id: p1\n"
            "    provider_contract: provider_missing\n"
            "    enabled_by_default: true\n"
            "    fixture_path: specifications/examples/flood/does_not_exist.json\n"
        ),
        encoding="utf-8",
    )

    r = probe_deployment_examples(tmp_path)
    assert r.examples_dir_exists is True
    assert r.example_count == 1
    d = r.deployments[0]
    assert d["deployment_key"] == "demo1"
    assert d["deployment_profile_exists"] is False
    assert d["application_registry_exists"] is False
    assert d["readme_exists"] is False
    assert d["missing_manifest_references"]
    assert d["missing_fixture_paths"]
    assert d["risks"]


def test_deployment_probe_no_examples_dir_non_crashing(tmp_path: Path) -> None:
    (tmp_path / "specifications").mkdir(parents=True)
    (tmp_path / "specifications" / "manifest.json").write_text("{}\n", encoding="utf-8")
    r = probe_deployment_examples(tmp_path)
    assert r.examples_dir_exists is False
    assert r.example_count == 0

