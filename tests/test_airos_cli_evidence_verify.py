from __future__ import annotations

import subprocess
import sys
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


def test_cli_evidence_verify_valid_bundle_exits_0(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_v1",
            deployment_id="dep_v",
            application_id="app_v",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
            output_refs=[],
        )
    )
    out_dir = tmp_path / "out"
    res_exp = _run_cli(
        "evidence",
        "export",
        "--run-id",
        "run_v1",
        "--store-dir",
        str(store_dir),
        "--output-dir",
        str(out_dir),
    )
    assert res_exp.returncode == 0, res_exp.stderr
    bundle = next(iter(out_dir.glob("*.zip")))

    res = _run_cli("evidence", "verify", str(bundle))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "internal consistency only" in out.lower()
    assert "not a digital signature" in out.lower()


def test_cli_evidence_verify_missing_bundle_fails(tmp_path: Path) -> None:
    res = _run_cli("evidence", "verify", str(tmp_path / "nope.zip"))
    assert res.returncode != 0

