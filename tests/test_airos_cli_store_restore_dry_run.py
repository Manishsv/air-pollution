from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from urban_platform.sdk.store_backup import backup_file_store


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_store_restore_dry_run_valid_does_not_create_target(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    target = tmp_path / "restore_candidate"
    assert not target.exists()

    res = _run_cli("store", "restore-dry-run", str(z), "--target-dir", str(target))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "") + (res.stderr or "")
    assert "dry-run" in out.lower()
    assert "does not write" in out.lower()
    assert "does not import" in out.lower()
    assert "existing_store_members: (none)" in out.lower()
    assert not target.exists()


def test_cli_store_restore_dry_run_collision_sections(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    target = tmp_path / "restore_candidate"
    target.mkdir()
    (target / "runs.jsonl").write_text("{}", encoding="utf-8")

    res = _run_cli("store", "restore-dry-run", str(z), "--target-dir", str(target))
    assert res.returncode == 0, res.stderr
    out = (res.stdout or "").lower()
    assert "existing_store_members:" in out
    assert "- runs.jsonl" in out
    assert "paths_that_would_overwrite" in out
    assert "would_overwrite: true" in out


def test_cli_store_restore_dry_run_invalid_backup_fails(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"notzip")
    res = _run_cli("store", "restore-dry-run", str(bad), "--target-dir", str(tmp_path / "x"))
    assert res.returncode != 0

