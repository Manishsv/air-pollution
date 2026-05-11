from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_apps_package_scaffolded_app_creates_zip_with_manifest(tmp_path: Path) -> None:
    manifest = (_REPO_ROOT / "specifications" / "manifest.json").read_bytes()
    builders = (_REPO_ROOT / "airos" / "os" / "deployments" / "builder_registry.py").read_bytes()

    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    assert res1.returncode == 0
    res2 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res2.returncode == 0, (res2.stdout or "") + (res2.stderr or "")

    z = dist / "heat_risk_review-v1.zip"
    assert z.exists()
    with zipfile.ZipFile(z, "r") as zf:
        assert "airos_package_manifest.json" in zf.namelist()
        pm = json.loads(zf.read("airos_package_manifest.json").decode("utf-8"))
        assert pm["app_id"] == "heat_risk_review"
        assert pm["version"] == "v1"
        assert "included_files" in pm
        assert "not installed, registered, allowlisted" in pm.get("note", "")
        # Generated junk should not be present
        assert not any("__pycache__" in n for n in zf.namelist())
        assert not any(".DS_Store" in n for n in zf.namelist())

    assert (_REPO_ROOT / "specifications" / "manifest.json").read_bytes() == manifest
    assert (_REPO_ROOT / "airos" / "os" / "deployments" / "builder_registry.py").read_bytes() == builders


def test_apps_package_fails_if_exists_without_force(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    res1 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res1.returncode == 0
    res2 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res2.returncode != 0


def test_apps_package_overwrites_with_force(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    res1 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res1.returncode == 0
    z = dist / "heat_risk_review-v1.zip"
    before = z.stat().st_mtime
    res2 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist), "--force")
    assert res2.returncode == 0
    assert z.stat().st_mtime >= before


def test_apps_package_invalid_app_does_not_package(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    # Remove descriptor to make invalid
    (app_dir / "app_descriptor.yaml").unlink()
    res = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res.returncode != 0


def test_apps_package_secret_like_file_causes_failure(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    (app_dir / ".env").write_text("SECRET=1", encoding="utf-8")
    res = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res.returncode != 0

