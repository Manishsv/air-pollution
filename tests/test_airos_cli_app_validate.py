from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_apps_validate_scaffolded_app_succeeds_with_warnings(tmp_path: Path) -> None:
    manifest = (_REPO_ROOT / "specifications" / "manifest.json").read_bytes()
    builders = (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes()

    out = tmp_path / "scaf"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res1.returncode == 0

    res2 = _run_cli("apps", "validate", str(out))
    assert res2.returncode == 0
    out_txt = (res2.stdout or "") + (res2.stderr or "")
    assert "status: valid_with_warnings" in out_txt or "status: valid" in out_txt
    assert "## App descriptor" in out_txt
    assert "## Structure" in out_txt

    # Must not modify repo specs/registry
    assert (_REPO_ROOT / "specifications" / "manifest.json").read_bytes() == manifest
    assert (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes() == builders


def test_apps_validate_missing_descriptor_fails(tmp_path: Path) -> None:
    out = tmp_path / "app"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("x", encoding="utf-8")
    for d in ["contracts", "examples", "builders", "dashboard", "deployments", "tests"]:
        (out / d).mkdir(parents=True, exist_ok=True)

    res = _run_cli("apps", "validate", str(out))
    assert res.returncode != 0


def test_apps_validate_invalid_yaml_fails(tmp_path: Path) -> None:
    out = tmp_path / "app"
    out.mkdir(parents=True, exist_ok=True)
    for d in ["contracts", "examples", "builders", "dashboard", "deployments", "tests"]:
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("x", encoding="utf-8")
    (out / "app_descriptor.yaml").write_text("not: [valid", encoding="utf-8")

    res = _run_cli("apps", "validate", str(out))
    assert res.returncode != 0


def test_apps_validate_descriptor_missing_safety_fields_fails(tmp_path: Path) -> None:
    out = tmp_path / "app"
    out.mkdir(parents=True, exist_ok=True)
    for d in ["contracts", "examples", "builders", "dashboard", "deployments", "tests"]:
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("x", encoding="utf-8")
    (out / "app_descriptor.yaml").write_text(
        "\n".join(
            [
                "app_id: heat_risk_review",
                "name: Heat Risk Review",
                "version: v1",
                "status: draft_demo",
                "domain_id: heat_risk",
                "app_type: review_support",
                "input_contracts: []",
                "output_contracts: []",
                "decision_logic: {builder_ids: []}",
                "safety: {review_support_only: true, human_review_required: true, blocked_uses: []}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    res = _run_cli("apps", "validate", str(out))
    assert res.returncode != 0


def test_apps_validate_invalid_app_id_domain_id_fails(tmp_path: Path) -> None:
    out = tmp_path / "HeatRiskReview"
    out.mkdir(parents=True, exist_ok=True)
    for d in ["contracts", "examples", "builders", "dashboard", "deployments", "tests"]:
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("x", encoding="utf-8")
    (out / "app_descriptor.yaml").write_text(
        "\n".join(
            [
                "app_id: HeatRiskReview",
                "name: x",
                "version: v1",
                "status: draft_demo",
                "domain_id: HeatRisk",
                "app_type: review_support",
                "input_contracts: []",
                "output_contracts: []",
                "decision_logic: {builder_ids: []}",
                "safety: {review_support_only: true, human_review_required: true, blocked_uses: [x]}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    res = _run_cli("apps", "validate", str(out))
    assert res.returncode != 0


def test_apps_validate_unknown_builder_id_is_warning_not_failure(tmp_path: Path) -> None:
    out = tmp_path / "heat_risk_review"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res1.returncode == 0

    # Add a builder_id that is not allowlisted.
    dpath = out / "app_descriptor.yaml"
    txt = dpath.read_text(encoding="utf-8")
    d = yaml_safe_load(txt)
    d["decision_logic"]["builder_ids"] = ["unknown_builder_id"]
    dpath.write_text(yaml_safe_dump(d), encoding="utf-8")

    res2 = _run_cli("apps", "validate", str(out))
    assert res2.returncode == 0


def test_apps_validate_known_builder_id_reported_allowlisted(tmp_path: Path) -> None:
    out = tmp_path / "heat_risk_review"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res1.returncode == 0

    dpath = out / "app_descriptor.yaml"
    d = yaml_safe_load(dpath.read_text(encoding="utf-8"))
    d["decision_logic"]["builder_ids"] = ["program_reporting_review_packet"]
    dpath.write_text(yaml_safe_dump(d), encoding="utf-8")

    res2 = _run_cli("apps", "validate", str(out))
    assert res2.returncode == 0
    out_txt = (res2.stdout or "") + (res2.stderr or "")
    assert "program_reporting_review_packet: allowlisted" in out_txt


def test_apps_validate_invalid_json_example_fails(tmp_path: Path) -> None:
    out = tmp_path / "heat_risk_review"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res1.returncode == 0
    (out / "examples" / "bad.json").write_text("{not json", encoding="utf-8")
    res2 = _run_cli("apps", "validate", str(out))
    assert res2.returncode != 0


# minimal YAML helpers (avoid importing heavy CLI modules)
import yaml  # noqa: E402


def yaml_safe_load(s: str) -> dict:
    obj = yaml.safe_load(s)
    assert isinstance(obj, dict)
    return obj


def yaml_safe_dump(d: dict) -> str:
    return yaml.safe_dump(d, sort_keys=False)

