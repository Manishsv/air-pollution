from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from urban_platform.specifications.conformance import SPEC_ROOT


EXPECTED_STORE_FILES: tuple[str, ...] = (
    "records.jsonl",
    "outputs.jsonl",
    "runs.jsonl",
    "validation_receipts.jsonl",
    "audit_events.jsonl",
)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_store_ref(store_dir: Path) -> str:
    repo_root = SPEC_ROOT.parent.resolve()
    try:
        rel = store_dir.resolve().relative_to(repo_root)
        return str(rel).replace("\\", "/")
    except Exception:
        return "redacted"


def _count_lines(raw: bytes) -> int:
    # JSONL is line-delimited; count lines in a platform-neutral way.
    return len(raw.decode("utf-8", errors="replace").splitlines())


def backup_file_store(*, store_dir: Path, output_dir: Path) -> Path:
    """
    Create a safe, read-only zip backup of the pilot FileAirOsStore directory.

    Notes:
    - This is a pilot utility, not a production-grade backup system.
    - It includes only known JSONL files and a manifest + safety notes.
    - It does not restore/import/compact or mutate the source store.
    """
    sdir = store_dir.resolve()
    if not sdir.exists() or not sdir.is_dir():
        raise FileNotFoundError(f"Store directory not found: {store_dir}")

    out_dir = output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    created_at = _now_utc_iso()
    backup_id = f"airos_store_backup_{created_at.replace(':', '').replace('-', '')}"
    zip_path = out_dir / f"{backup_id}.zip"

    included_files: List[Dict[str, Any]] = []
    missing_expected_files: List[str] = []

    file_bytes: dict[str, bytes] = {}
    for name in EXPECTED_STORE_FILES:
        p0 = sdir / name
        if not p0.exists():
            missing_expected_files.append(name)
            continue
        if p0.is_symlink():
            # Never follow symlinks (avoid escaping store_dir).
            missing_expected_files.append(f"{name} (symlink skipped)")
            continue
        p = p0.resolve()
        if not p.is_file():
            missing_expected_files.append(name)
            continue
        try:
            p.relative_to(sdir)
        except Exception:
            missing_expected_files.append(f"{name} (outside store_dir)")
            continue
        try:
            raw = p.read_bytes()
        except Exception:
            missing_expected_files.append(f"{name} (unreadable)")
            continue

        file_bytes[name] = raw
        included_files.append(
            {
                "path": name,
                "size_bytes": len(raw),
                "sha256": _sha256_hex(raw),
                "line_count": _count_lines(raw),
            }
        )

    readme = f"""# AirOS pilot store backup (zip)

Backup: `{backup_id}`
Created at: `{created_at}`

## What this contains

- Pilot store JSONL files (only known store members when present)
- `store_manifest.json` with file hashes and line counts (integrity metadata only)
- `safety_notes.md`

## What this is not

- Not a restore/import tool (no import is implemented here).
- Not a compaction tool.
- Not an evidence bundle (evidence bundles are run/deployment-scoped review artifacts).
- Not a digital signature, approval, or legal attestation.

## How to inspect

Unzip and review the JSONL files with a text editor or `jq`.
"""

    safety_notes = """# Safety notes (read before use)

This store backup is **operational support only**.

It does **not** authorize or automate:

- fund release
- penalties / recovery
- emergency orders / evacuations
- blacklisting
- public disclosure without authorization
- any final government decision

Hashes in `store_manifest.json` support **file integrity checks only**. They are **not** digital signatures and do not prove signer identity.
"""

    store_manifest = {
        "backup_id": backup_id,
        "created_at": created_at,
        "source_store_dir": _safe_store_ref(sdir),
        "included_files": included_files,
        "missing_expected_files": missing_expected_files,
        "note": "This is a pilot store backup. It is not an approval, legal attestation, or production-grade backup.",
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", readme.encode("utf-8"))
        z.writestr("store_manifest.json", _stable_json(store_manifest).encode("utf-8"))
        z.writestr("safety_notes.md", safety_notes.encode("utf-8"))
        for name, raw in file_bytes.items():
            z.writestr(name, raw)

    return zip_path


def _is_unsafe_zip_member(name: str) -> bool:
    if not isinstance(name, str) or not name:
        return True
    if name.startswith("/") or name.startswith("\\"):
        return True
    if ":" in name.split("/")[0]:
        return True
    if "\\" in name:
        return True
    parts = [p for p in name.split("/") if p]
    if any(p == ".." for p in parts):
        return True
    return False


def inspect_store_backup(*, backup_path: Path) -> dict[str, Any]:
    p = backup_path
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    if p.suffix.lower() != ".zip":
        raise ValueError("Store backup must be a .zip file.")

    required = {"store_manifest.json", "README.md", "safety_notes.md"}
    warnings: list[str] = []

    with zipfile.ZipFile(p, "r") as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        for info in infos:
            n = info.filename
            if _is_unsafe_zip_member(n):
                raise ValueError(f"Unsafe zip member path: {n!r}")
            # Reject symlinks if detectable (Unix external attributes).
            is_symlink = (getattr(info, "external_attr", 0) >> 16) & 0o170000 == 0o120000
            if is_symlink:
                raise ValueError(f"Symlink zip member not allowed: {n!r}")

        present = set(names)
        missing = sorted(required - present)
        if missing:
            raise ValueError(f"Backup missing required files: {', '.join(missing)}")

        try:
            manifest = json.loads(z.read("store_manifest.json").decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"store_manifest.json: invalid JSON ({exc})") from exc
        if not isinstance(manifest, dict):
            raise ValueError("store_manifest.json: expected JSON object")

        included = manifest.get("included_files") or []
        missing_expected = manifest.get("missing_expected_files") or []
        if not isinstance(included, list):
            warnings.append("store_manifest.json included_files is not a list.")
            included = []
        if not isinstance(missing_expected, list):
            warnings.append("store_manifest.json missing_expected_files is not a list.")
            missing_expected = []

        total_size = 0
        total_lines = 0
        for f in included:
            if not isinstance(f, dict):
                continue
            try:
                total_size += int(f.get("size_bytes") or 0)
            except Exception:
                pass
            try:
                total_lines += int(f.get("line_count") or 0)
            except Exception:
                pass

        safety_notes_present = bool(z.read("safety_notes.md").decode("utf-8").strip())
        if not safety_notes_present:
            warnings.append("safety_notes.md was empty.")

    status = "inspectable"
    if warnings:
        status = "inspectable_with_warnings"

    return {
        "status": status,
        "backup_id": manifest.get("backup_id"),
        "created_at": manifest.get("created_at"),
        "included_files": included,
        "missing_expected_files": missing_expected,
        "file_count": len(included),
        "total_size_bytes": total_size,
        "total_line_count": total_lines,
        "safety_notes_present": safety_notes_present,
        "warnings": warnings,
    }


def verify_store_backup(*, backup_path: Path) -> dict[str, Any]:
    """
    Verify internal consistency + file hashes for a pilot store backup zip.

    This is not a digital signature, approval, certification, or a production backup guarantee.
    """
    # Reuse inspection safety checks and parsing.
    rep = inspect_store_backup(backup_path=backup_path)

    warnings: list[str] = list(rep.get("warnings") or [])
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    def _ok(name: str, detail: str) -> None:
        checks.append({"name": name, "status": "ok", "detail": detail})

    def _warn(name: str, detail: str) -> None:
        warnings.append(f"{name}: {detail}")
        checks.append({"name": name, "status": "warn", "detail": detail})

    def _err(name: str, detail: str) -> None:
        errors.append(f"{name}: {detail}")
        checks.append({"name": name, "status": "fail", "detail": detail})

    included_files = rep.get("included_files") or []
    missing_expected_files = rep.get("missing_expected_files") or []
    included_by_path: dict[str, dict[str, Any]] = {}
    if isinstance(included_files, list):
        for f in included_files:
            if isinstance(f, dict) and isinstance(f.get("path"), str):
                included_by_path[str(f["path"])] = f

    # Ensure missing_expected_files are not present as included files
    if isinstance(missing_expected_files, list):
        bad = [m for m in missing_expected_files if isinstance(m, str) and m in included_by_path]
        if bad:
            _err("missing_expected_files", f"Files marked missing are also included: {', '.join(bad)}")
        else:
            _ok("missing_expected_files", "missing_expected_files does not conflict with included_files.")

    allowed_non_store = {"README.md", "store_manifest.json", "safety_notes.md"}

    with zipfile.ZipFile(backup_path, "r") as z:
        present = set(z.namelist())

        # Warn if expected store files present but not listed in manifest.
        extra_known = sorted((present & set(EXPECTED_STORE_FILES)) - set(included_by_path.keys()))
        if extra_known:
            _warn("known_files_unlisted", "Known store files present but not listed in manifest: " + ", ".join(extra_known))
        else:
            _ok("known_files_unlisted", "No known store files are present without being listed.")

        # Warn on unknown files (anything not expected store file or required).
        unknown = sorted(present - set(EXPECTED_STORE_FILES) - allowed_non_store)
        if unknown:
            _warn("unknown_files", "Unknown files present in backup zip: " + ", ".join(unknown[:25]))
        else:
            _ok("unknown_files", "No unknown files present.")

        # Verify each included file exists and matches sha/size/lines.
        for path, meta in sorted(included_by_path.items(), key=lambda x: x[0]):
            if path not in present:
                _err("included_file_missing", f"Included file not found in zip: {path}")
                continue
            raw = z.read(path)

            sha = str(meta.get("sha256") or "").strip()
            if not sha:
                _warn("included_file_hash", f"{path}: missing sha256 in manifest")
            else:
                actual = _sha256_hex(raw)
                if actual != sha:
                    _err("included_file_hash", f"{path}: sha256 mismatch")
                else:
                    _ok("included_file_hash", f"{path}: sha256 matches")

            if meta.get("size_bytes") is not None:
                try:
                    expected_size = int(meta.get("size_bytes") or 0)
                    if expected_size != len(raw):
                        _err("included_file_size", f"{path}: size_bytes mismatch")
                    else:
                        _ok("included_file_size", f"{path}: size_bytes matches")
                except Exception:
                    _warn("included_file_size", f"{path}: invalid size_bytes in manifest")

            if path.endswith(".jsonl") and meta.get("line_count") is not None:
                try:
                    expected_lines = int(meta.get("line_count") or 0)
                    actual_lines = _count_lines(raw)
                    if expected_lines != actual_lines:
                        _err("included_file_line_count", f"{path}: line_count mismatch")
                    else:
                        _ok("included_file_line_count", f"{path}: line_count matches")
                except Exception:
                    _warn("included_file_line_count", f"{path}: invalid line_count in manifest")

        # Safety notes content check (basic)
        try:
            safety_txt = z.read("safety_notes.md").decode("utf-8", errors="replace").lower()
            if ("final government decision" in safety_txt) or ("not an approval" in safety_txt) or ("does not authorize" in safety_txt):
                _ok("safety_notes_content", "Safety posture wording present.")
            else:
                _warn("safety_notes_content", "Safety posture wording not detected (check safety_notes.md).")
        except Exception:
            _warn("safety_notes_content", "Could not read safety_notes.md for safety wording check.")

    status = "verified"
    if errors:
        status = "invalid"
    elif warnings:
        status = "verified_with_warnings"

    return {
        "status": status,
        "backup": {
            "backup_id": rep.get("backup_id"),
            "created_at": rep.get("created_at"),
        },
        "counts": {
            "included_files": int(rep.get("file_count") or 0),
            "missing_expected_files": len(missing_expected_files) if isinstance(missing_expected_files, list) else 0,
            "total_size_bytes": int(rep.get("total_size_bytes") or 0),
            "total_line_count": int(rep.get("total_line_count") or 0),
        },
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "note": "Backup verification checks internal consistency and file hashes only. It is not a signature, approval, certification, or production backup guarantee.",
    }


def restore_file_store_dry_run(*, backup_path: Path, target_dir: Path) -> dict[str, Any]:
    """
    Dry-run restore check: verify backup + report what would be restored to target_dir.

    Dry-run only: no files are written, target_dir is not created, and no store is modified.
    """
    v = verify_store_backup(backup_path=backup_path)
    verification_status = str(v.get("status") or "")
    warnings: list[str] = list(v.get("warnings") or [])
    errors: list[str] = list(v.get("errors") or [])

    if verification_status == "invalid":
        t0 = target_dir
        tgt_exists = t0.exists()
        return {
            "status": "invalid",
            "verification_status": verification_status,
            "files_to_restore": [],
            "missing_expected_files": [],
            "target_exists": tgt_exists,
            "target_has_existing_store_files": False,
            "existing_store_members": [],
            "paths_that_would_overwrite": [],
            "would_overwrite": False,
            "total_size_bytes": 0,
            "total_line_count": 0,
            "warnings": warnings,
            "errors": errors,
            "note": "Dry-run only. No files were written, target_dir was not created or modified.",
        }

    t = target_dir
    target_exists = t.exists()
    target_has_existing_store_files = False
    collision_files: list[str] = []

    if target_exists:
        if not t.is_dir():
            errors.append("target_dir is not a directory")
        else:
            for name in EXPECTED_STORE_FILES:
                p = t / name
                if p.exists():
                    target_has_existing_store_files = True
                    # Symlinks count as present paths for collision reporting; dry-run does not follow them.
                    collision_files.append(name)
    else:
        # Do not create the directory; dry-run reports existence only.
        pass

    included = v.get("counts") or {}
    total_size_bytes = int(included.get("total_size_bytes") or 0)
    total_line_count = int(included.get("total_line_count") or 0)

    files_to_restore: list[str] = []
    # Prefer deriving from verification checks: manifest-listed files are those that would be restored.
    # (Restore would only consider expected JSONL members anyway.)
    try:
        rep_inspect = inspect_store_backup(backup_path=backup_path)
        inc = rep_inspect.get("included_files") or []
        if isinstance(inc, list):
            for f in inc:
                if isinstance(f, dict) and isinstance(f.get("path"), str):
                    path = str(f["path"])
                    if path in EXPECTED_STORE_FILES:
                        files_to_restore.append(path)
    except Exception:
        # verification already passed; keep conservative empty list
        warnings.append("could not derive files_to_restore from manifest (unexpected).")

    files_to_restore = sorted(set(files_to_restore))
    existing_store_members = sorted(set(collision_files))
    paths_that_would_overwrite = sorted(set(files_to_restore) & set(existing_store_members))
    would_overwrite = bool(paths_that_would_overwrite)

    if existing_store_members:
        warnings.append("target_dir already has store member file(s): " + ", ".join(existing_store_members))
        if would_overwrite:
            warnings.append(
                "Hypothetical restore would overwrite existing file(s): "
                + ", ".join(paths_that_would_overwrite)
                + " (dry-run only; no writes performed)."
            )
        else:
            warnings.append(
                "Existing store member file(s) do not overlap files in this backup; hypothetical restore would not overwrite them."
            )

    missing_expected_files: list[str] = []
    try:
        rep_inspect2 = inspect_store_backup(backup_path=backup_path)
        miss = rep_inspect2.get("missing_expected_files") or []
        if isinstance(miss, list):
            missing_expected_files = [str(x) for x in miss if isinstance(x, str)]
    except Exception:
        pass

    status = "ok" if not errors else "invalid"

    return {
        "status": status,
        "verification_status": verification_status,
        "files_to_restore": files_to_restore,
        "missing_expected_files": missing_expected_files,
        "target_exists": bool(target_exists),
        "target_has_existing_store_files": bool(target_has_existing_store_files),
        "existing_store_members": existing_store_members,
        "paths_that_would_overwrite": paths_that_would_overwrite,
        "would_overwrite": bool(would_overwrite),
        "total_size_bytes": total_size_bytes,
        "total_line_count": total_line_count,
        "warnings": warnings,
        "errors": errors,
        "note": "Dry-run only. No files were written, target_dir was not created or modified.",
    }

