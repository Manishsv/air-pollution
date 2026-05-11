from __future__ import annotations

import zipfile
from pathlib import Path

from airos.os.sdk.store_backup import backup_file_store, restore_file_store_dry_run


def _has_any_store_file(p: Path) -> bool:
    return any((p / n).exists() for n in ("records.jsonl", "outputs.jsonl", "runs.jsonl", "validation_receipts.jsonl", "audit_events.jsonl"))


def test_dry_run_valid_backup_does_not_create_target_dir(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    target = tmp_path / "restore_candidate"
    assert not target.exists()

    rep = restore_file_store_dry_run(backup_path=z, target_dir=target)
    assert rep["status"] == "ok"
    assert rep["target_exists"] is False
    assert rep["existing_store_members"] == []
    assert rep["paths_that_would_overwrite"] == []
    assert rep["would_overwrite"] is False
    assert "runs.jsonl" in (rep.get("files_to_restore") or [])
    assert not target.exists(), "dry-run must not create target_dir"


def test_dry_run_detects_collision(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    target = tmp_path / "restore_candidate"
    target.mkdir()
    (target / "runs.jsonl").write_text('{"run_id":"existing"}\n', encoding="utf-8")
    assert _has_any_store_file(target)

    rep = restore_file_store_dry_run(backup_path=z, target_dir=target)
    assert rep["status"] == "ok"
    assert rep["target_exists"] is True
    assert rep["target_has_existing_store_files"] is True
    assert rep["existing_store_members"] == ["runs.jsonl"]
    assert rep["paths_that_would_overwrite"] == ["runs.jsonl"]
    assert rep["would_overwrite"] is True


def test_dry_run_existing_members_without_overlap_reports_no_overwrite(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    target = tmp_path / "restore_candidate"
    target.mkdir()
    (target / "audit_events.jsonl").write_text('{"audit":"x"}\n', encoding="utf-8")

    rep = restore_file_store_dry_run(backup_path=z, target_dir=target)
    assert rep["status"] == "ok"
    assert rep["existing_store_members"] == ["audit_events.jsonl"]
    assert rep["paths_that_would_overwrite"] == []
    assert rep["would_overwrite"] is False
    warns = "\n".join(rep.get("warnings") or [])
    assert "hypothetical restore would not overwrite" in warns.lower()


def test_dry_run_invalid_backup_fails(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    # Tamper with runs.jsonl without updating manifest
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(z, "r") as zin, zipfile.ZipFile(tampered, "w") as zout:
        for name in zin.namelist():
            raw = zin.read(name)
            if name == "runs.jsonl":
                raw = b'{"run_id":"evil"}\n'
            zout.writestr(name, raw)

    rep = restore_file_store_dry_run(backup_path=tampered, target_dir=tmp_path / "x")
    assert rep["status"] == "invalid"
    assert rep["existing_store_members"] == []
    assert rep["paths_that_would_overwrite"] == []

