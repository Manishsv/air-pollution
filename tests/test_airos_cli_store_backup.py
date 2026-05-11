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


def test_cli_store_backup_creates_zip_and_prints_safety_note(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "audit_events.jsonl").write_text('{"event_id":"e1"}\n', encoding="utf-8")

    out_dir = tmp_path / "out"
    res = _run_cli("store", "backup", "--store-dir", str(store_dir), "--output-dir", str(out_dir))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "read-only" in out.lower()
    assert "not restore/import" in out.lower()
    assert "not a digital signature" in out.lower()

    zips = list(out_dir.glob("*.zip"))
    assert zips
    with zipfile.ZipFile(zips[0], "r") as zz:
        names = set(zz.namelist())
        assert "README.md" in names
        assert "store_manifest.json" in names
        assert "safety_notes.md" in names
        assert "audit_events.jsonl" in names
        mf = json.loads(zz.read("store_manifest.json").decode("utf-8"))
        assert "not an approval" in str(mf.get("note") or "").lower()


def test_cli_store_backup_missing_store_dir_exits_nonzero(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    res = _run_cli("store", "backup", "--store-dir", str(tmp_path / "nope"), "--output-dir", str(out_dir))
    assert res.returncode != 0

