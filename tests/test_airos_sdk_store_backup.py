from __future__ import annotations

import json
import zipfile
from pathlib import Path

from airos.os.sdk.store_backup import backup_file_store


def test_backup_creates_zip_and_does_not_include_unknown_files(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()

    # Known store file (present)
    (store_dir / "runs.jsonl").write_text('{"run_id":"r1"}\n{"run_id":"r1","status":"completed"}\n', encoding="utf-8")
    # Unknown and secret-like files (must not be included)
    (store_dir / "notes.txt").write_text("ignore", encoding="utf-8")
    (store_dir / ".env").write_text("TOKEN=abc", encoding="utf-8")

    before = {p.name: p.read_bytes() for p in store_dir.iterdir()}

    out_dir = tmp_path / "backups"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)
    assert z.is_file()
    assert z.suffix == ".zip"

    after = {p.name: p.read_bytes() for p in store_dir.iterdir()}
    assert before == after, "Backup must not mutate source store files"

    with zipfile.ZipFile(z, "r") as zz:
        names = set(zz.namelist())
        assert "README.md" in names
        assert "store_manifest.json" in names
        assert "safety_notes.md" in names
        assert "runs.jsonl" in names
        assert "notes.txt" not in names
        assert ".env" not in names

        mf = json.loads(zz.read("store_manifest.json").decode("utf-8"))
        assert "not an approval" in str(mf.get("note") or "").lower()
        included = mf.get("included_files") or []
        assert any(x.get("path") == "runs.jsonl" and x.get("sha256") and x.get("line_count") == 2 for x in included)
        missing = mf.get("missing_expected_files") or []
        assert "records.jsonl" in missing


def test_backup_skips_symlinked_store_member(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"x":1}\n', encoding="utf-8")

    # Symlink named like a store member
    link = store_dir / "records.jsonl"
    link.symlink_to(outside)

    out_dir = tmp_path / "backups"
    z = backup_file_store(store_dir=store_dir, output_dir=out_dir)
    with zipfile.ZipFile(z, "r") as zz:
        assert "records.jsonl" not in set(zz.namelist())
        mf = json.loads(zz.read("store_manifest.json").decode("utf-8"))
        missing = mf.get("missing_expected_files") or []
        assert any("records.jsonl" in str(x) and "symlink" in str(x) for x in missing)

