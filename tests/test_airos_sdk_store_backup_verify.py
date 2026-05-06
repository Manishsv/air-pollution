from __future__ import annotations

import json
import zipfile
from pathlib import Path

from urban_platform.sdk.store_backup import backup_file_store, verify_store_backup


def _rewrite_zip(src: Path, dst: Path, *, mutate: dict[str, bytes] | None = None, drop: set[str] | None = None) -> None:
    mutate = mutate or {}
    drop = drop or set()
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            if name in drop:
                continue
            raw = mutate.get(name, zin.read(name))
            zout.writestr(name, raw)


def test_verify_valid_backup_is_verified(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    rep = verify_store_backup(backup_path=z)
    assert rep["status"] in ("verified", "verified_with_warnings")
    assert "internal consistency" in str(rep.get("note") or "").lower()


def test_verify_tampered_file_is_invalid(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    tampered = tmp_path / "tampered.zip"
    _rewrite_zip(z, tampered, mutate={"runs.jsonl": b'{"run_id":"evil"}\n'})

    rep = verify_store_backup(backup_path=tampered)
    assert rep["status"] == "invalid"


def test_verify_unknown_extra_file_is_warning(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    extra = tmp_path / "extra.zip"
    _rewrite_zip(z, extra)
    with zipfile.ZipFile(extra, "a") as zz:
        zz.writestr("notes.txt", "x")

    rep = verify_store_backup(backup_path=extra)
    assert rep["status"] in ("verified_with_warnings", "invalid")
    assert any("unknown_files" in w for w in rep.get("warnings") or [])


def test_verify_known_store_file_present_but_unlisted_warns(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    extra = tmp_path / "extra_known.zip"
    _rewrite_zip(z, extra)
    with zipfile.ZipFile(extra, "a") as zz:
        zz.writestr("records.jsonl", '{"record_id":"r"}\n')

    rep = verify_store_backup(backup_path=extra)
    assert rep["status"] in ("verified_with_warnings", "invalid")
    assert any("known_files_unlisted" in w for w in rep.get("warnings") or [])


def test_verify_missing_included_file_is_invalid(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)

    broken = tmp_path / "broken.zip"
    _rewrite_zip(z, broken, drop={"runs.jsonl"})

    rep = verify_store_backup(backup_path=broken)
    assert rep["status"] == "invalid"

