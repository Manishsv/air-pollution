from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def _make_package(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    assert res1.returncode == 0
    res2 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res2.returncode == 0
    return dist / "heat_risk_review-v1.zip"


def test_inspect_package_valid_succeeds(tmp_path: Path) -> None:
    manifest = (_REPO_ROOT / "specifications" / "manifest.json").read_bytes()
    builders = (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes()

    z = _make_package(tmp_path)
    res = _run_cli("apps", "inspect-package", str(z))
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "heat_risk_review" in out
    assert "validation_status" in out
    assert "input_contracts" in out
    assert "output_contracts" in out
    assert "blocked_uses" in out
    assert "Inspection does not execute builders" in out

    assert (_REPO_ROOT / "specifications" / "manifest.json").read_bytes() == manifest
    assert (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes() == builders


def test_inspect_package_missing_zip_fails(tmp_path: Path) -> None:
    res = _run_cli("apps", "inspect-package", str(tmp_path / "missing.zip"))
    assert res.returncode != 0


def test_inspect_package_non_zip_fails(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("x", encoding="utf-8")
    res = _run_cli("apps", "inspect-package", str(p))
    assert res.returncode != 0


def test_inspect_package_missing_manifest_fails(tmp_path: Path) -> None:
    z = _make_package(tmp_path)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "r") as zf_in, zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
        for n in zf_in.namelist():
            if n == "airos_package_manifest.json":
                continue
            zf_out.writestr(n, zf_in.read(n))
    res = _run_cli("apps", "inspect-package", str(bad))
    assert res.returncode != 0


def test_inspect_package_path_traversal_entry_fails(tmp_path: Path) -> None:
    z = _make_package(tmp_path)
    bad = tmp_path / "trav.zip"
    with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../evil.txt", "x")
        zf.writestr("airos_package_manifest.json", json.dumps({"app_id": "x", "version": "v1"}))
    res = _run_cli("apps", "inspect-package", str(bad))
    assert res.returncode != 0


def test_inspect_package_secret_like_file_fails(tmp_path: Path) -> None:
    bad = tmp_path / "secret.zip"
    with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("airos_package_manifest.json", json.dumps({"app_id": "x", "version": "v1"}))
        zf.writestr("app/.env", "SECRET=1")
    res = _run_cli("apps", "inspect-package", str(bad))
    assert res.returncode != 0

