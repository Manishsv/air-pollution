from __future__ import annotations

import json
from pathlib import Path

import yaml

import airos.network.cli.airos_cli as cli
from airos.network.cli.deployment_runner.run_deployment import run_deployment


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_deployment_init_from_example_copies_and_validates(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo_city_flood"

    rc = cli.main(
        [
            "deployment",
            "init",
            "--from-example",
            "flood_local_demo",
            "--deployment-id",
            "demo_city_flood",
            "--deployment-name",
            "Demo City Flood",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    # Copied files should exist (example has these).
    assert (out_dir / "deployment_profile.yaml").is_file()
    assert (out_dir / "provider_registry.yaml").is_file()
    assert (out_dir / "application_registry.yaml").is_file()

    prof = _read_yaml(out_dir / "deployment_profile.yaml")
    assert prof["deployment_id"] == "demo_city_flood"
    assert prof["deployment_name"] == "Demo City Flood"
    # Ensure local registry paths are self-contained.
    assert prof["enabled_provider_registries"] == ["provider_registry.yaml"]
    assert prof["enabled_application_registries"] == ["application_registry.yaml"]

    # Validate should pass (no placeholder contract keys introduced).
    rc_val = cli.main(["deployment", "validate", str(out_dir)])
    assert rc_val == 0


def test_deployment_init_from_example_run_produces_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo_city_flood"
    rc = cli.main(
        [
            "deployment",
            "init",
            "--from-example",
            "flood_local_demo",
            "--deployment-id",
            "demo_city_flood",
            "--deployment-name",
            "Demo City Flood",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    # Run the deployment using the copied workspace, but write outputs under tmp_path.
    summary = run_deployment(deployment_dir=out_dir, repo_root=REPO_ROOT, output_root=tmp_path)
    out = Path(summary.output_dir)

    assert summary.deployment_id == "demo_city_flood"
    assert (out / "flood_risk_dashboard_payload.json").is_file()
    assert (out / "flood_decision_packets.json").is_file()
    assert (out / "flood_field_verification_tasks.json").is_file()
    assert (out / "deployment_run_summary.json").is_file()

    # Quick sanity: JSON is parseable.
    json.loads((out / "deployment_run_summary.json").read_text(encoding="utf-8"))

