from __future__ import annotations

import re
from pathlib import Path

import yaml

import tools.airos_cli as cli


_SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._-]+\b|"
    r"\bAKIA[0-9A-Z]{12,}\b|"
    r"\bghp_[A-Za-z0-9]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\bAIza[0-9A-Za-z_-]{20,}\b"
    r")"
)


def _read_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_deployment_init_creates_expected_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "dep"
    rc = cli.main(
        [
            "deployment",
            "init",
            "--deployment-id",
            "demo_city_air_quality",
            "--deployment-name",
            "Demo City Air Quality",
            "--deployment-type",
            "single_agency",
            "--owner-organization",
            "Demo Agency",
            "--environment",
            "local",
            "--domains",
            "air_quality,flood_risk",
            "--output-dir",
            str(out_dir),
            "--providers",
            "openaq_v3,open_meteo",
            "--applications",
            "air_quality_reference_pipeline",
            "--network-adapters",
            "email_phase1_adapter",
        ]
    )
    assert rc == 0

    for name in [
        "deployment_profile.yaml",
        "provider_registry.yaml",
        "application_registry.yaml",
        "network_adapter_registry.yaml",
        "agency_node_profile.yaml",
        "network_participant_profile.yaml",
        "jurisdiction_profile.yaml",
        "data_sharing_policy.yaml",
        "README.md",
    ]:
        assert (out_dir / name).exists()

    dep = _read_yaml(out_dir / "deployment_profile.yaml")
    assert dep["deployment_id"] == "demo_city_air_quality"
    assert dep["enabled_domains"] == ["air_quality", "flood_risk"]

    prov = _read_yaml(out_dir / "provider_registry.yaml")
    pids = [p.get("provider_id") for p in prov.get("providers", []) if isinstance(p, dict)]
    assert pids == ["openaq_v3", "open_meteo"]


def test_deployment_init_fails_if_exists_without_force(tmp_path: Path) -> None:
    out_dir = tmp_path / "dep"
    out_dir.mkdir(parents=True, exist_ok=True)
    rc = cli.main(
        [
            "deployment",
            "init",
            "--deployment-id",
            "x",
            "--deployment-name",
            "x",
            "--deployment-type",
            "single_agency",
            "--owner-organization",
            "x",
            "--environment",
            "local",
            "--domains",
            "air_quality",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 1


def test_deployment_init_overwrites_with_force(tmp_path: Path) -> None:
    out_dir = tmp_path / "dep"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "README.md").write_text("old", encoding="utf-8")
    rc = cli.main(
        [
            "deployment",
            "init",
            "--deployment-id",
            "x",
            "--deployment-name",
            "x",
            "--deployment-type",
            "single_agency",
            "--owner-organization",
            "x",
            "--environment",
            "local",
            "--domains",
            "air_quality",
            "--output-dir",
            str(out_dir),
            "--force",
        ]
    )
    assert rc == 0
    assert (out_dir / "README.md").read_text(encoding="utf-8") != "old"


def test_generated_files_do_not_contain_secret_like_values(tmp_path: Path) -> None:
    out_dir = tmp_path / "dep"
    rc = cli.main(
        [
            "deployment",
            "init",
            "--deployment-id",
            "x",
            "--deployment-name",
            "x",
            "--deployment-type",
            "single_agency",
            "--owner-organization",
            "x",
            "--environment",
            "local",
            "--domains",
            "air_quality",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    for p in out_dir.rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".md"}:
            text = p.read_text(encoding="utf-8")
            assert _SECRET_VALUE_RE.search(text) is None

