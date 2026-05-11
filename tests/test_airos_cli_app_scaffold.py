from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def _read_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_apps_scaffold_creates_expected_structure_and_descriptor(tmp_path: Path) -> None:
    manifest = (_REPO_ROOT / "specifications" / "manifest.json").read_bytes()
    builders = (_REPO_ROOT / "airos" / "os" / "deployments" / "builder_registry.py").read_bytes()

    out = tmp_path / "scaf"
    res = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")

    # Structure
    for rel in [
        "README.md",
        "app_descriptor.yaml",
        "contracts/input_contract.template.schema.json",
        "contracts/output_contract.template.schema.json",
        "examples/input.sample.json",
        "examples/output.sample.json",
        "builders/builder.py",
        "dashboard/panel.py",
        "deployments/deployment_profile.yaml",
        "deployments/application_registry.yaml",
        "deployments/provider_registry.yaml",
        "tests/test_heat_risk_review.py",
    ]:
        assert (out / rel).exists()

    d = _read_yaml(out / "app_descriptor.yaml")
    assert d["app_id"] == "heat_risk_review"
    assert d["domain_id"] == "heat_risk"
    safety = d.get("safety") or {}
    assert isinstance(safety, dict)
    assert safety.get("review_support_only") is True
    assert safety.get("human_review_required") is True
    assert "final_government_decision_without_authorized_review" in (safety.get("blocked_uses") or [])

    # Placeholders / non-executable wording
    readme = (out / "README.md").read_text(encoding="utf-8").lower()
    assert "scaffold" in readme
    assert "not registered" in readme
    assert "not executable" in readme

    # Must not modify repo specs/registry
    assert (_REPO_ROOT / "specifications" / "manifest.json").read_bytes() == manifest
    assert (_REPO_ROOT / "airos" / "os" / "deployments" / "builder_registry.py").read_bytes() == builders


def test_apps_scaffold_fails_if_target_exists_without_force(tmp_path: Path) -> None:
    out = tmp_path / "scaf"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("old", encoding="utf-8")

    res = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out))
    assert res.returncode != 0
    assert (out / "README.md").read_text(encoding="utf-8") == "old"


def test_apps_scaffold_overwrites_with_force(tmp_path: Path) -> None:
    out = tmp_path / "scaf"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("old", encoding="utf-8")

    res = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(out), "--force")
    assert res.returncode == 0
    assert (out / "README.md").read_text(encoding="utf-8") != "old"


def test_apps_scaffold_invalid_app_id_fails(tmp_path: Path) -> None:
    res = _run_cli("apps", "scaffold", "HeatRiskReview", "--domain-id", "heat_risk", "--output-dir", str(tmp_path / "x"))
    assert res.returncode != 0


def test_apps_scaffold_invalid_domain_id_fails(tmp_path: Path) -> None:
    res = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "HeatRisk", "--output-dir", str(tmp_path / "x"))
    assert res.returncode != 0

