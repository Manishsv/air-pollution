from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from airos.os.storage.file_store import FileAirOsStore
from airos.os.storage.models import StoredRun


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_evidence_export_by_run_id(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_cli_1",
            deployment_id="dep_cli",
            application_id="app_cli",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    out_dir = tmp_path / "out"
    res = _run_cli(
        "evidence",
        "export",
        "--run-id",
        "run_cli_1",
        "--store-dir",
        str(store_dir),
        "--output-dir",
        str(out_dir),
    )
    assert res.returncode == 0, res.stderr
    zips = list(out_dir.glob("*.zip"))
    assert zips
    with zipfile.ZipFile(zips[0], "r") as zz:
        assert "hash_manifest.json" in zz.namelist()
        m = json.loads(zz.read("manifest.json").decode("utf-8"))
        assert m.get("run_id") == "run_cli_1"


def test_cli_unknown_run_fails(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    FileAirOsStore(store_dir)
    out_dir = tmp_path / "out"
    res = _run_cli(
        "evidence",
        "export",
        "--run-id",
        "nope",
        "--store-dir",
        str(store_dir),
        "--output-dir",
        str(out_dir),
    )
    assert res.returncode != 0

