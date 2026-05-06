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


def _make_package(tmp_path: Path) -> Path:
    app_dir = tmp_path / "app"
    dist = tmp_path / "dist"
    res1 = _run_cli("apps", "scaffold", "heat_risk_review", "--domain-id", "heat_risk", "--output-dir", str(app_dir))
    assert res1.returncode == 0
    res2 = _run_cli("apps", "package", str(app_dir), "--output-dir", str(dist))
    assert res2.returncode == 0
    return dist / "heat_risk_review-v1.zip"


def test_catalog_list_empty_exits_0_with_help(tmp_path: Path) -> None:
    cat = tmp_path / "cat"
    res = _run_cli("catalog", "list", "--catalog-dir", str(cat))
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "Catalog is empty" in out


def test_catalog_add_list_show_roundtrip(tmp_path: Path) -> None:
    manifest = (_REPO_ROOT / "specifications" / "manifest.json").read_bytes()
    builders = (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes()

    z = _make_package(tmp_path)
    cat = tmp_path / "cat"
    res1 = _run_cli("catalog", "add-package", str(z), "--catalog-dir", str(cat))
    assert res1.returncode == 0
    idx = cat / "index.json"
    assert idx.exists()
    obj = json.loads(idx.read_text(encoding="utf-8"))
    assert "apps" in obj
    assert "heat_risk_review" in obj["apps"]
    assert "v1" in obj["apps"]["heat_risk_review"]
    entry = obj["apps"]["heat_risk_review"]["v1"]
    assert "catalog_note" in entry
    assert "metadata only" in entry["catalog_note"]

    res2 = _run_cli("catalog", "list", "--catalog-dir", str(cat))
    assert res2.returncode == 0
    out2 = (res2.stdout or "") + (res2.stderr or "")
    assert "heat_risk_review" in out2

    res3 = _run_cli("catalog", "show", "heat_risk_review", "--catalog-dir", str(cat))
    assert res3.returncode == 0
    out3 = (res3.stdout or "") + (res3.stderr or "")
    assert "versions:" in out3
    assert "blocked_uses" in out3

    # duplicate add without --force should fail
    res4 = _run_cli("catalog", "add-package", str(z), "--catalog-dir", str(cat))
    assert res4.returncode != 0

    # duplicate add with --force should succeed
    res5 = _run_cli("catalog", "add-package", str(z), "--catalog-dir", str(cat), "--force")
    assert res5.returncode == 0

    # must not modify repo specs/registry
    assert (_REPO_ROOT / "specifications" / "manifest.json").read_bytes() == manifest
    assert (_REPO_ROOT / "urban_platform" / "deployments" / "builder_registry.py").read_bytes() == builders


def test_catalog_show_unknown_exits_nonzero(tmp_path: Path) -> None:
    cat = tmp_path / "cat"
    res = _run_cli("catalog", "show", "does_not_exist", "--catalog-dir", str(cat))
    assert res.returncode != 0

