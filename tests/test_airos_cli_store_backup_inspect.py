from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from airos.os.sdk.store_backup import backup_file_store


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_store_inspect_backup_valid(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "audit_events.jsonl").write_text('{"event_id":"e1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    res = _run_cli("store", "inspect-backup", str(z))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "read-only" in out.lower()
    assert "does not restore" in out.lower()
    assert "does not import" in out.lower()
    assert "does not approve" in out.lower()


def test_cli_store_inspect_backup_missing_fails(tmp_path: Path) -> None:
    res = _run_cli("store", "inspect-backup", str(tmp_path / "nope.zip"))
    assert res.returncode != 0

