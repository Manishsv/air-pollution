from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from airos.os.sdk.store_backup import backup_file_store, inspect_store_backup


def test_inspect_valid_backup_succeeds(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    rep = inspect_store_backup(backup_path=z)
    assert rep["status"] in ("inspectable", "inspectable_with_warnings")
    assert rep["backup_id"]
    assert rep["created_at"]
    assert rep["file_count"] >= 1
    assert rep["total_size_bytes"] >= 1
    assert rep["safety_notes_present"] is True


def test_missing_backup_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inspect_store_backup(backup_path=tmp_path / "nope.zip")


def test_non_zip_fails(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_store_backup(backup_path=p)


def test_missing_required_files_fails(tmp_path: Path) -> None:
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("README.md", "x")
        zz.writestr("store_manifest.json", "{}")
    with pytest.raises(ValueError):
        inspect_store_backup(backup_path=z)


def test_unsafe_zip_path_fails(tmp_path: Path) -> None:
    z = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../store_manifest.json", "{}")
        zz.writestr("README.md", "x")
        zz.writestr("safety_notes.md", "x")
    with pytest.raises(ValueError):
        inspect_store_backup(backup_path=z)


def test_malformed_store_manifest_fails(tmp_path: Path) -> None:
    z = tmp_path / "malformed.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("README.md", "x")
        zz.writestr("safety_notes.md", "x")
        zz.writestr("store_manifest.json", "{")
    with pytest.raises(ValueError):
        inspect_store_backup(backup_path=z)

