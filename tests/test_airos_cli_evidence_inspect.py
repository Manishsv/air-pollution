from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

from urban_platform.storage.file_store import FileAirOsStore
from urban_platform.storage.models import StoredRun


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_evidence_inspect_valid_bundle(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_cli_2",
            deployment_id="dep_cli",
            application_id="app_cli",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    out_dir = tmp_path / "out"
    res_exp = _run_cli(
        "evidence",
        "export",
        "--run-id",
        "run_cli_2",
        "--store-dir",
        str(store_dir),
        "--output-dir",
        str(out_dir),
    )
    assert res_exp.returncode == 0, res_exp.stderr
    bundle = next(iter(out_dir.glob("*.zip")))

    res = _run_cli("evidence", "inspect", str(bundle))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "read-only" in out.lower()
    assert "does not approve" in out.lower()
    assert "hash manifest" in out.lower()


def test_cli_evidence_inspect_missing_bundle_fails(tmp_path: Path) -> None:
    res = _run_cli("evidence", "inspect", str(tmp_path / "nope.zip"))
    assert res.returncode != 0


def test_cli_evidence_inspect_unsafe_zip_fails(tmp_path: Path) -> None:
    z = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../manifest.json", "{}")
    res = _run_cli("evidence", "inspect", str(z))
    assert res.returncode != 0

