from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from airos.os.specifications.conformance import SPEC_ROOT
from airos.os.storage.models import AuditEvent, StoredOutput, StoredRecord, StoredRun, StoredValidationReceipt


def _repo_root() -> Path:
    return SPEC_ROOT.parent.resolve()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_hash_manifest(*, file_bytes: dict[str, bytes], created_at: str) -> bytes:
    items = [{"path": p, "sha256": _sha256_hex(b)} for p, b in sorted(file_bytes.items(), key=lambda x: x[0])]
    manifest = {
        "algorithm": "sha256",
        "created_at": created_at,
        "files": items,
        "note": "Hash manifest supports internal integrity checks only. It is not a digital signature or approval.",
    }
    return _stable_json(manifest).encode("utf-8")


def _safe_store_ref(store_dir: Path) -> str:
    rr = _repo_root()
    try:
        rel = store_dir.resolve().relative_to(rr)
        return str(rel).replace("\\", "/")
    except Exception:
        return "AIROS_STORE_DIR"


def _iter_jsonl_dicts(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _load_latest_by_id(path: Path, *, id_key: str, cls) -> dict[str, Any]:
    by_id: dict[str, Any] = {}
    for obj in _iter_jsonl_dicts(path):
        rid = str(obj.get(id_key) or "").strip()
        if not rid:
            continue
        try:
            by_id[rid] = cls(**obj)  # type: ignore[misc]
        except TypeError:
            continue
    return by_id


def _store_paths(store_dir: Path) -> dict[str, Path]:
    d = store_dir.resolve()
    return {
        "records": d / "records.jsonl",
        "runs": d / "runs.jsonl",
        "outputs": d / "outputs.jsonl",
        "validation_receipts": d / "validation_receipts.jsonl",
        "audit_events": d / "audit_events.jsonl",
    }


def _collect_by_run_id(
    store_dir: Path,
    *,
    run_id: str,
) -> tuple[list[StoredRun], list[StoredRecord], list[StoredOutput], list[StoredValidationReceipt], list[AuditEvent]]:
    paths = _store_paths(store_dir)

    runs_by_id = _load_latest_by_id(paths["runs"], id_key="run_id", cls=StoredRun)
    run = runs_by_id.get(run_id)
    if run is None:
        return [], [], [], [], []

    # Outputs: linked by output_refs primarily; fall back to deployment_id if output_refs missing.
    outputs_by_id = _load_latest_by_id(paths["outputs"], id_key="output_id", cls=StoredOutput)
    outputs: list[StoredOutput] = []
    if run.output_refs:
        for oid in run.output_refs:
            o = outputs_by_id.get(str(oid))
            if isinstance(o, StoredOutput):
                outputs.append(o)
    if not outputs:
        outputs = [o for o in outputs_by_id.values() if isinstance(o, StoredOutput) and o.deployment_id == run.deployment_id]

    # Records: linked by run.input_refs if present; fall back to deployment_id records.
    records_by_id = _load_latest_by_id(paths["records"], id_key="record_id", cls=StoredRecord)
    records: list[StoredRecord] = []
    if run.input_refs:
        for rid in run.input_refs:
            r = records_by_id.get(str(rid))
            if isinstance(r, StoredRecord):
                records.append(r)
    if not records:
        records = [r for r in records_by_id.values() if isinstance(r, StoredRecord) and r.deployment_id == run.deployment_id]

    # Receipts: prefer targets among collected outputs/records, else deployment_id.
    receipts_by_id = _load_latest_by_id(paths["validation_receipts"], id_key="receipt_id", cls=StoredValidationReceipt)
    output_ids = {o.output_id for o in outputs}
    record_ids = {r.record_id for r in records}
    receipts: list[StoredValidationReceipt] = []
    for rec in receipts_by_id.values():
        if not isinstance(rec, StoredValidationReceipt):
            continue
        if rec.deployment_id != run.deployment_id:
            continue
        if rec.validation_target_id in output_ids or rec.validation_target_id in record_ids:
            receipts.append(rec)
    if not receipts:
        receipts = [r for r in receipts_by_id.values() if isinstance(r, StoredValidationReceipt) and r.deployment_id == run.deployment_id]

    # Audit events: filter by deployment_id and match run_id in resource_id when possible.
    audit_by_id = _load_latest_by_id(paths["audit_events"], id_key="event_id", cls=AuditEvent)
    events = [e for e in audit_by_id.values() if isinstance(e, AuditEvent) and e.deployment_id == run.deployment_id]
    events_run = [e for e in events if str(e.resource_id) == run.run_id or str(e.metadata.get("run_id") or "") == run.run_id]
    audit_events = events_run or events

    return [run], records, outputs, receipts, audit_events


def _collect_by_deployment_id(
    store_dir: Path,
    *,
    deployment_id: str,
) -> tuple[list[StoredRun], list[StoredRecord], list[StoredOutput], list[StoredValidationReceipt], list[AuditEvent]]:
    paths = _store_paths(store_dir)

    runs_by_id = _load_latest_by_id(paths["runs"], id_key="run_id", cls=StoredRun)
    runs = [r for r in runs_by_id.values() if isinstance(r, StoredRun) and r.deployment_id == deployment_id]

    records_by_id = _load_latest_by_id(paths["records"], id_key="record_id", cls=StoredRecord)
    records = [r for r in records_by_id.values() if isinstance(r, StoredRecord) and r.deployment_id == deployment_id]

    outputs_by_id = _load_latest_by_id(paths["outputs"], id_key="output_id", cls=StoredOutput)
    outputs = [o for o in outputs_by_id.values() if isinstance(o, StoredOutput) and o.deployment_id == deployment_id]

    receipts_by_id = _load_latest_by_id(paths["validation_receipts"], id_key="receipt_id", cls=StoredValidationReceipt)
    receipts = [r for r in receipts_by_id.values() if isinstance(r, StoredValidationReceipt) and r.deployment_id == deployment_id]

    audit_by_id = _load_latest_by_id(paths["audit_events"], id_key="event_id", cls=AuditEvent)
    audit_events = [e for e in audit_by_id.values() if isinstance(e, AuditEvent) and e.deployment_id == deployment_id]

    return runs, records, outputs, receipts, audit_events


def export_evidence_bundle(
    *,
    store_dir: Path,
    output_dir: Path,
    run_id: str | None = None,
    deployment_id: str | None = None,
) -> Path:
    """
    Export a portable, read-only evidence bundle for a pilot-runtime store.

    The bundle is intended for review/debug/audit support. It does not execute builders,
    rerun applications, or imply approval/authorization.
    """
    rid = str(run_id or "").strip() or None
    did = str(deployment_id or "").strip() or None
    if (rid is None and did is None) or (rid is not None and did is not None):
        raise ValueError("Exactly one of run_id or deployment_id must be provided.")

    sdir = store_dir.resolve()
    if not sdir.exists() or not sdir.is_dir():
        raise FileNotFoundError(f"Store directory not found: {store_dir}")

    out_dir = output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if rid is not None:
        runs, records, outputs, receipts, audits = _collect_by_run_id(sdir, run_id=rid)
        if not runs:
            raise ValueError(f"Unknown run_id: {rid}")
        selector = rid
    else:
        runs, records, outputs, receipts, audits = _collect_by_deployment_id(sdir, deployment_id=did or "")
        if not (runs or records or outputs or receipts or audits):
            raise ValueError(f"No store data found for deployment_id: {did}")
        selector = did or "deployment"

    created_at = _now_utc_iso()
    bundle_id = f"evidence_bundle_{selector}_{created_at.replace(':', '').replace('-', '')}"
    zip_name = f"{bundle_id}.zip"
    zip_path = out_dir / zip_name

    manifest = {
        "bundle_id": bundle_id,
        "created_at": created_at,
        "run_id": rid,
        "deployment_id": did or (runs[0].deployment_id if runs else None),
        "counts": {
            "runs": len(runs),
            "records": len(records),
            "outputs": len(outputs),
            "validation_receipts": len(receipts),
            "audit_events": len(audits),
        },
        "source_store_dir": _safe_store_ref(sdir),
        "note": "Evidence export only. This bundle is for traceability and review support; it is not approval evidence.",
    }

    readme = f"""# AirOS Evidence Bundle

Bundle: `{bundle_id}`

Created at: `{created_at}`

## What this includes

- Runs (`runs.json`)
- Ingested records (`records.json`)
- Generated outputs (`outputs.json`)
- Validation receipts (`validation_receipts.json`)
- Audit events (`audit_events.json`)
- Bundle manifest (`manifest.json`)
- Safety notes (`safety_notes.md`)

## What this does not include

- It does **not** rerun applications or execute builders.
- It does **not** validate or approve anything.
- It does **not** imply authorization, approval, or any final government decision.

## How to inspect

Unzip the file and review the JSON files in a text editor, or use `jq` to filter.
"""

    safety_notes = """# Safety notes (read before use)

This evidence bundle is **review and audit support only**.

It does **not** authorize or automate:

- fund release
- emergency orders / evacuations
- penalties / recovery
- blacklisting
- public disclosure without authorization
- any final government decision

Runs and validation receipts are **traceability evidence**, not approval evidence.
"""

    def _dump_jsonl_like(objs: Sequence[Any]) -> str:
        payload = [asdict(x) for x in objs]
        return _stable_json(payload)

    file_bytes: dict[str, bytes] = {}
    file_bytes["README.md"] = readme.encode("utf-8")
    file_bytes["manifest.json"] = _stable_json(manifest).encode("utf-8")
    file_bytes["runs.json"] = _dump_jsonl_like(runs).encode("utf-8")
    file_bytes["records.json"] = _dump_jsonl_like(records).encode("utf-8")
    file_bytes["outputs.json"] = _dump_jsonl_like(outputs).encode("utf-8")
    file_bytes["validation_receipts.json"] = _dump_jsonl_like(receipts).encode("utf-8")
    file_bytes["audit_events.json"] = _dump_jsonl_like(audits).encode("utf-8")
    file_bytes["safety_notes.md"] = safety_notes.encode("utf-8")

    # Hash every file except the hash manifest itself.
    hash_manifest_bytes = _build_hash_manifest(file_bytes=file_bytes, created_at=created_at)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, b in file_bytes.items():
            z.writestr(path, b)
        z.writestr("hash_manifest.json", hash_manifest_bytes)

    return zip_path


def _is_unsafe_zip_member(name: str) -> bool:
    """
    Reject:
    - absolute paths (/..., C:\...)
    - traversal (..)
    - backslash-based traversal
    """
    if not isinstance(name, str) or not name:
        return True
    if name.startswith("/") or name.startswith("\\"):
        return True
    if ":" in name.split("/")[0]:
        # windows drive or scheme-like prefix
        return True
    if "\\" in name:
        # treat backslashes as unsafe in bundle members
        return True
    parts = [p for p in name.split("/") if p]
    if any(p == ".." for p in parts):
        return True
    return False


def _read_zip_json(z: zipfile.ZipFile, member: str) -> list[dict[str, Any]]:
    raw = z.read(member).decode("utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, list):
        raise ValueError(f"{member}: expected JSON array")
    return [x for x in obj if isinstance(x, dict)]


def inspect_evidence_bundle(*, bundle_path: Path) -> dict[str, Any]:
    p = bundle_path
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    if p.suffix.lower() != ".zip":
        raise ValueError("Evidence bundle must be a .zip file.")

    required = {
        "manifest.json",
        "runs.json",
        "records.json",
        "outputs.json",
        "validation_receipts.json",
        "audit_events.json",
        "safety_notes.md",
    }

    with zipfile.ZipFile(p, "r") as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        for n in names:
            if _is_unsafe_zip_member(n):
                raise ValueError(f"Unsafe zip member path: {n!r}")
            # Reject symlinks if detectable (Unix external attributes).
            is_symlink = (getattr(i := next((x for x in infos if x.filename == n), None), "external_attr", 0) >> 16) & 0o170000 == 0o120000  # type: ignore[truthy-bool]
            if is_symlink:
                raise ValueError(f"Symlink zip member not allowed: {n!r}")

        present = set(names)
        missing = sorted(required - present)
        if missing:
            raise ValueError(f"Bundle missing required files: {', '.join(missing)}")

        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"manifest.json: invalid JSON ({exc})") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json: expected JSON object")

        runs = _read_zip_json(z, "runs.json")
        records = _read_zip_json(z, "records.json")
        outputs = _read_zip_json(z, "outputs.json")
        receipts = _read_zip_json(z, "validation_receipts.json")
        audits = _read_zip_json(z, "audit_events.json")
        safety_notes_present = bool(z.read("safety_notes.md").decode("utf-8").strip())
        redaction_report_present = "redaction_report.json" in present
        hash_manifest_present = "hash_manifest.json" in present
        hash_algorithm = None
        hashed_file_count = None
        if hash_manifest_present:
            try:
                hm = json.loads(z.read("hash_manifest.json").decode("utf-8"))
                if isinstance(hm, dict):
                    hash_algorithm = hm.get("algorithm")
                    files = hm.get("files") or []
                    hashed_file_count = len(files) if isinstance(files, list) else None
            except Exception:
                # keep as None; inspection should not fail due to hash manifest parse
                pass

    run_status_counts: dict[str, int] = {}
    for r in runs:
        s = str(r.get("status") or "unknown").lower()
        run_status_counts[s] = run_status_counts.get(s, 0) + 1

    output_contract_keys = sorted({str(o.get("contract_key") or "").strip() for o in outputs if str(o.get("contract_key") or "").strip()})

    receipt_status_counts: dict[str, int] = {}
    invalid_receipts: list[dict[str, Any]] = []
    for r in receipts:
        s = str(r.get("status") or "unknown").lower()
        receipt_status_counts[s] = receipt_status_counts.get(s, 0) + 1
        try:
            errc = int(r.get("error_count") or 0)
        except Exception:
            errc = 0
        if s == "invalid" or errc > 0:
            invalid_receipts.append(
                {
                    "receipt_id": r.get("receipt_id"),
                    "contract_key": r.get("contract_key"),
                    "validation_target_type": r.get("validation_target_type"),
                    "validation_target_id": r.get("validation_target_id"),
                    "error_count": r.get("error_count"),
                }
            )

    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    summary = {
        "bundle": {
            "bundle_id": manifest.get("bundle_id"),
            "created_at": manifest.get("created_at"),
            "run_id": manifest.get("run_id"),
            "deployment_id": manifest.get("deployment_id"),
            "counts": counts,
            "safety_note": manifest.get("note"),
        },
        "runs": {
            "count": len(runs),
            "status_counts": run_status_counts,
        },
        "records": {"count": len(records)},
        "outputs": {"count": len(outputs), "contract_keys": output_contract_keys},
        "validation_receipts": {
            "count": len(receipts),
            "status_counts": receipt_status_counts,
            "invalid_count": len(invalid_receipts),
            "invalid_receipts": invalid_receipts[:50],
        },
        "audit_events": {"count": len(audits)},
        "safety_notes_present": bool(safety_notes_present),
        "redaction_report_present": bool(redaction_report_present),
        "hash_manifest": {
            "present": bool(hash_manifest_present),
            "algorithm": hash_algorithm,
            "hashed_file_count": hashed_file_count,
        },
        "warnings": [],
    }
    if not safety_notes_present:
        summary["warnings"].append("safety_notes.md was empty.")
    if not hash_manifest_present:
        summary["warnings"].append("hash_manifest.json missing (legacy bundle; integrity checks limited).")
    return summary


def verify_evidence_bundle(*, bundle_path: Path) -> dict[str, Any]:
    """
    Verify internal consistency of an evidence bundle.

    Verification checks internal consistency only. It is not a signature check, approval, or certification.
    """
    # Start from the same safety + parsing posture as inspection.
    p = bundle_path
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    if p.suffix.lower() != ".zip":
        raise ValueError("Evidence bundle must be a .zip file.")

    required = {
        "manifest.json",
        "runs.json",
        "records.json",
        "outputs.json",
        "validation_receipts.json",
        "audit_events.json",
        "safety_notes.md",
    }

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def _ok(cid: str, msg: str) -> None:
        checks.append({"check_id": cid, "status": "pass", "message": msg})

    def _warn(cid: str, msg: str) -> None:
        checks.append({"check_id": cid, "status": "warn", "message": msg})
        warnings.append(msg)

    def _err(cid: str, msg: str) -> None:
        checks.append({"check_id": cid, "status": "fail", "message": msg})
        errors.append(msg)

    with zipfile.ZipFile(p, "r") as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        present = set(names)
        for info in infos:
            n = info.filename
            if _is_unsafe_zip_member(n):
                raise ValueError(f"Unsafe zip member path: {n!r}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"Symlink zip member not allowed: {n!r}")

        missing = sorted(required - present)
        if missing:
            _err("required_files", f"Missing required files: {', '.join(missing)}")
            # still attempt to parse what we can (for better error reporting)
        else:
            _ok("required_files", "All required bundle files are present.")

        # Hash manifest (optional for backward compatibility)
        hash_manifest = None
        if "hash_manifest.json" in present:
            try:
                hash_manifest = json.loads(z.read("hash_manifest.json").decode("utf-8"))
                if not isinstance(hash_manifest, dict):
                    raise ValueError("hash_manifest.json: expected JSON object")
                _ok("hash_manifest_parse", "hash_manifest.json parsed.")
            except Exception as exc:
                _err("hash_manifest_parse", f"hash_manifest.json parse failed: {exc}")
                hash_manifest = None
        else:
            _warn("hash_manifest_missing", "hash_manifest.json missing (legacy bundle; file integrity checks limited).")

        if isinstance(hash_manifest, dict):
            algo = str(hash_manifest.get("algorithm") or "").lower()
            if algo != "sha256":
                _err("hash_manifest_algorithm", f"hash_manifest.json algorithm must be sha256 (got {algo!r})")
            else:
                _ok("hash_manifest_algorithm", "hash_manifest.json algorithm is sha256.")

            listed = hash_manifest.get("files") or []
            if not isinstance(listed, list):
                _err("hash_manifest_files", "hash_manifest.json files must be an array")
                listed = []

            listed_paths: set[str] = set()
            mismatches: list[str] = []
            missing_files: list[str] = []
            for entry in listed:
                if not isinstance(entry, dict):
                    continue
                path = str(entry.get("path") or "").strip()
                sha = str(entry.get("sha256") or "").strip()
                if not path or not sha:
                    continue
                if path == "hash_manifest.json":
                    _err("hash_manifest_scope", "hash_manifest.json must not include itself.")
                    continue
                if _is_unsafe_zip_member(path):
                    _err("hash_manifest_paths", f"hash_manifest.json contains unsafe path: {path!r}")
                    continue
                listed_paths.add(path)
                if path not in present:
                    missing_files.append(path)
                    continue
                data = z.read(path)
                if _sha256_hex(data) != sha:
                    mismatches.append(path)

            if missing_files:
                _err("hash_manifest_missing_files", "hash_manifest references missing files: " + ", ".join(missing_files[:25]))
            if mismatches:
                _err("hash_manifest_mismatch", "Hash mismatch for files: " + ", ".join(mismatches[:25]))
            if not missing_files and not mismatches and not errors:
                _ok("hash_manifest_match", "All listed file hashes match.")
            elif not missing_files and not mismatches:
                _ok("hash_manifest_match", "All listed file hashes match (other checks may still fail).")

            # Warn on extra files not listed (except the hash manifest itself).
            extra = sorted((present - {"hash_manifest.json"}) - listed_paths)
            if extra:
                _warn("hash_manifest_extra_files", "Bundle contains files not listed in hash_manifest.json: " + ", ".join(extra[:25]))

        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest.json: expected JSON object")
            _ok("manifest_parse", "manifest.json parsed.")
        except Exception as exc:
            _err("manifest_parse", f"manifest.json parse failed: {exc}")
            manifest = {}

        is_redacted_bundle = ("redaction_report.json" in present) or bool(manifest.get("redacted") is True)

        def _try_read_array(member: str) -> list[dict[str, Any]]:
            try:
                arr = _read_zip_json(z, member)
                _ok(f"parse_{member}", f"{member} parsed.")
                return arr
            except Exception as exc:
                _err(f"parse_{member}", f"{member} parse failed: {exc}")
                return []

        runs = _try_read_array("runs.json")
        records = _try_read_array("records.json")
        outputs = _try_read_array("outputs.json")
        receipts = _try_read_array("validation_receipts.json")
        audits = _try_read_array("audit_events.json")

        safety_text = ""
        try:
            safety_text = z.read("safety_notes.md").decode("utf-8")
        except Exception as exc:
            _err("safety_notes", f"safety_notes.md read failed: {exc}")

    # Manifest counts check
    mcounts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    expected = {
        "runs": len(runs),
        "records": len(records),
        "outputs": len(outputs),
        "validation_receipts": len(receipts),
        "audit_events": len(audits),
    }
    mismatch: list[str] = []
    for k, actual in expected.items():
        try:
            exp = int(mcounts.get(k)) if mcounts.get(k) is not None else None
        except Exception:
            exp = None
        if exp is None:
            _warn("manifest_counts", f"manifest counts missing or non-integer for: {k}")
            continue
        if exp != actual:
            mismatch.append(f"{k}: manifest={exp} actual={actual}")
    if mismatch:
        _err("manifest_counts", "Manifest count mismatch: " + "; ".join(mismatch))
    else:
        _ok("manifest_counts", "Manifest counts match bundle contents (where provided).")

    # Payload hash checks (records + outputs)
    from airos.os.storage.file_store import compute_payload_hash  # noqa: WPS433

    def _verify_hash(items: Sequence[dict[str, Any]], *, item_label: str, id_key: str) -> None:
        bad: list[str] = []
        missing: int = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            payload = it.get("payload")
            if not isinstance(payload, dict):
                continue
            ph = it.get("payload_hash")
            if not isinstance(ph, str) or not ph.strip():
                missing += 1
                continue
            calc = compute_payload_hash(payload)
            if calc != ph:
                bad.append(str(it.get(id_key) or "?"))
        if bad:
            if is_redacted_bundle:
                _warn(
                    f"payload_hash_{item_label}",
                    f"{item_label}: payload_hash mismatch for ids (redacted bundle): {', '.join(bad[:25])}",
                )
            else:
                _err(f"payload_hash_{item_label}", f"{item_label}: payload_hash mismatch for ids: {', '.join(bad[:25])}")
        else:
            _ok(f"payload_hash_{item_label}", f"{item_label}: payload_hash values match payloads (where present).")
        if missing:
            _warn(f"payload_hash_{item_label}_missing", f"{item_label}: {missing} items missing payload_hash (treated as warnings).")

    _verify_hash(records, item_label="records", id_key="record_id")
    _verify_hash(outputs, item_label="outputs", id_key="output_id")

    # Run-output links
    output_ids = {str(o.get("output_id") or "").strip() for o in outputs if str(o.get("output_id") or "").strip()}
    run_ids = {str(r.get("run_id") or "").strip() for r in runs if str(r.get("run_id") or "").strip()}

    missing_out_refs: list[str] = []
    for r in runs:
        refs = r.get("output_refs") or []
        if not isinstance(refs, list):
            continue
        for oid in refs:
            soid = str(oid or "").strip()
            if soid and soid not in output_ids:
                missing_out_refs.append(f"{r.get('run_id')}→{soid}")
    if missing_out_refs:
        _err("run_output_refs", "Runs reference missing outputs: " + ", ".join(missing_out_refs[:25]))
    else:
        _ok("run_output_refs", "Run output_refs are resolvable (where present).")

    # Output-run links (metadata.run_id is optional; warn if absent)
    outputs_missing_run: int = 0
    outputs_unknown_run: list[str] = []
    for o in outputs:
        md = o.get("metadata") if isinstance(o.get("metadata"), dict) else {}
        rid = str(md.get("run_id") or "").strip()
        if not rid:
            outputs_missing_run += 1
            continue
        if rid not in run_ids:
            outputs_unknown_run.append(f"{o.get('output_id')}→{rid}")
    if outputs_unknown_run:
        _warn("output_run_id", "Some outputs reference unknown run_id: " + ", ".join(outputs_unknown_run[:25]))
    else:
        _ok("output_run_id", "Output metadata.run_id references are resolvable (where present).")
    if outputs_missing_run:
        _warn("output_run_id_missing", f"{outputs_missing_run} outputs missing metadata.run_id (treated as warnings).")

    # Validation receipt links + sanity rules
    record_ids = {str(r.get("record_id") or "").strip() for r in records if str(r.get("record_id") or "").strip()}

    bad_receipts: list[str] = []
    dangling_receipts: list[str] = []
    for rec in receipts:
        rstatus = str(rec.get("status") or "").lower()
        target_type = str(rec.get("validation_target_type") or "").lower()
        target_id = str(rec.get("validation_target_id") or "").strip()
        try:
            errc = int(rec.get("error_count") or 0)
        except Exception:
            errc = 0
        errs = rec.get("errors") or []
        errs_list = errs if isinstance(errs, list) else []

        if rstatus == "valid" and errc > 0:
            bad_receipts.append(str(rec.get("receipt_id") or "?"))
        if rstatus == "invalid" and errc == 0 and not errs_list:
            _warn("receipt_invalid_no_errors", f"Receipt marked invalid but has no errors: {rec.get('receipt_id')}")

        if target_type == "record" and target_id and target_id not in record_ids:
            dangling_receipts.append(f"{rec.get('receipt_id')}→record:{target_id}")
        if target_type == "output" and target_id and target_id not in output_ids:
            dangling_receipts.append(f"{rec.get('receipt_id')}→output:{target_id}")

    if bad_receipts:
        _err("receipt_valid_error_count", "Receipts marked valid but have error_count>0: " + ", ".join(bad_receipts[:25]))
    else:
        _ok("receipt_valid_error_count", "Valid receipts have error_count==0.")

    if dangling_receipts:
        _warn("receipt_targets", "Some receipts reference unknown targets: " + ", ".join(dangling_receipts[:25]))
    else:
        _ok("receipt_targets", "Receipt targets are resolvable (where applicable).")

    # Audit links (warn only)
    known = output_ids | record_ids | run_ids
    unknown_audit: int = 0
    for e in audits:
        rid = str(e.get("resource_id") or "").strip()
        if rid and rid not in known:
            unknown_audit += 1
    if unknown_audit:
        _warn("audit_links", f"{unknown_audit} audit events reference unknown resource_id (warning only).")
    else:
        _ok("audit_links", "Audit resource_id values are resolvable (where they reference stored ids).")

    # Safety notes content check
    if not safety_text.strip():
        _err("safety_notes_content", "safety_notes.md was empty.")
    else:
        low = safety_text.lower()
        if ("final government decision" in low) or ("not approval" in low) or ("traceability evidence" in low):
            _ok("safety_notes_content", "Safety notes include review / non-approval language.")
        else:
            _warn("safety_notes_content", "Safety notes missing explicit non-approval / no-final-decision wording.")

    status = "verified"
    if errors:
        status = "invalid"
    elif warnings:
        status = "verified_with_warnings"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "counts": expected,
        "note": "Verification checks internal consistency only. It is not a signature check, approval, or certification.",
        "bundle": {
            "bundle_id": manifest.get("bundle_id"),
            "created_at": manifest.get("created_at"),
            "run_id": manifest.get("run_id"),
            "deployment_id": manifest.get("deployment_id"),
        },
    }


def _redact_key_name_matches(key: str, needles: Sequence[str]) -> bool:
    k = str(key or "").lower()
    return any(n in k for n in needles)


def _redact_json_obj(obj: Any, *, profile: str, redaction_counter: list[int]) -> Any:
    """
    Recursive redaction of JSON-compatible structures.

    - Redacts values by key-name heuristics.
    - Does not attempt perfect PII detection; this is a lightweight pilot profile system.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            k_low = ks.lower()

            # Universal secret-like keys (both profiles)
            if _redact_key_name_matches(
                k_low,
                ("token", "secret", "api_key", "authorization", "credential", "password"),
            ):
                out[ks] = "redacted"
                redaction_counter[0] += 1
                continue

            # Public demo: redact additional potential identifiers and source metadata
            if profile == "public_demo" and _redact_key_name_matches(
                k_low,
                ("email", "phone", "mobile"),
            ):
                out[ks] = "redacted"
                redaction_counter[0] += 1
                continue

            if profile == "public_demo" and k_low in ("source_metadata", "source_ref"):
                out[ks] = {"redacted": True}
                redaction_counter[0] += 1
                continue

            out[ks] = _redact_json_obj(v, profile=profile, redaction_counter=redaction_counter)
        return out

    if isinstance(obj, list):
        return [_redact_json_obj(x, profile=profile, redaction_counter=redaction_counter) for x in obj]

    return obj


def redact_evidence_bundle(
    *,
    bundle_path: Path,
    output_dir: Path,
    profile: str,
) -> Path:
    """
    Create a redacted copy of an evidence bundle zip.

    Redaction is for sharing copies (demo/internal review). It does not approve, certify, sign, execute, import, or publish anything.
    """
    prof = str(profile or "").strip()
    if prof not in ("public_demo", "internal_review"):
        raise ValueError("profile must be one of: public_demo, internal_review")

    src = bundle_path
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    if src.suffix.lower() != ".zip":
        raise ValueError("Evidence bundle must be a .zip file.")

    out_dir = output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"{src.name}.{prof}.redacted.zip" if not src.name.endswith(".zip") else f"{src.name[:-4]}.{prof}.redacted.zip"
    out_path = out_dir / out_name

    redacted_count = [0]
    files_processed: list[str] = []

    from airos.os.storage.file_store import compute_payload_hash  # noqa: WPS433

    with zipfile.ZipFile(src, "r") as zin:
        infos = zin.infolist()
        for info in infos:
            if _is_unsafe_zip_member(info.filename):
                raise ValueError(f"Unsafe zip member path: {info.filename!r}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"Symlink zip member not allowed: {info.filename!r}")

        names = set(i.filename for i in infos)
        # Require the same core files as inspection.
        for req in (
            "manifest.json",
            "runs.json",
            "records.json",
            "outputs.json",
            "validation_receipts.json",
            "audit_events.json",
            "safety_notes.md",
        ):
            if req not in names:
                raise ValueError(f"Bundle missing required file: {req}")

        manifest = json.loads(zin.read("manifest.json").decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json: expected JSON object")

        runs = json.loads(zin.read("runs.json").decode("utf-8"))
        records = json.loads(zin.read("records.json").decode("utf-8"))
        outputs = json.loads(zin.read("outputs.json").decode("utf-8"))
        receipts = json.loads(zin.read("validation_receipts.json").decode("utf-8"))
        audits = json.loads(zin.read("audit_events.json").decode("utf-8"))

        if not all(isinstance(x, list) for x in (runs, records, outputs, receipts, audits)):
            raise ValueError("Bundle JSON files must be arrays.")

        # Apply redaction to records/outputs/receipts/audits (runs are metadata-only; redact secrets if any).
        runs_r = _redact_json_obj(runs, profile=prof, redaction_counter=redacted_count)
        records_r = _redact_json_obj(records, profile=prof, redaction_counter=redacted_count)
        outputs_r = _redact_json_obj(outputs, profile=prof, redaction_counter=redacted_count)
        receipts_r = _redact_json_obj(receipts, profile=prof, redaction_counter=redacted_count)
        audits_r = _redact_json_obj(audits, profile=prof, redaction_counter=redacted_count)

        # Profile-specific audit actor redaction (public demo)
        if prof == "public_demo":
            for e in audits_r:
                if isinstance(e, dict) and e.get("actor") is not None:
                    e["actor"] = "redacted_actor"
                    redacted_count[0] += 1

        # Update payload hashes for any record/output payloads (so verify can still pass).
        def _rehash(items: list[Any], *, id_key: str) -> None:
            for it in items:
                if not isinstance(it, dict):
                    continue
                payload = it.get("payload")
                if not isinstance(payload, dict):
                    continue
                prev = it.get("payload_hash")
                new_hash = compute_payload_hash(payload)
                if isinstance(prev, str) and prev and prev != new_hash:
                    it["original_payload_hash"] = prev
                    redacted_count[0] += 1
                it["payload_hash"] = new_hash
                it["redacted_payload_hash"] = new_hash

        _rehash(records_r, id_key="record_id")
        _rehash(outputs_r, id_key="output_id")

        # Manifest redaction fields
        manifest_r = _redact_json_obj(manifest, profile=prof, redaction_counter=redacted_count)
        if "source_store_dir" in manifest_r:
            manifest_r["source_store_dir"] = "redacted"
            redacted_count[0] += 1
        manifest_r["redacted"] = True
        manifest_r["redaction_profile"] = prof
        manifest_r["note"] = "Redacted sharing copy. Verification checks internal consistency only; not signatures/certification/approval."

        redaction_report = {
            "redacted_at": _now_utc_iso(),
            "profile": prof,
            "source_bundle_name": src.name,
            "output_bundle_name": out_path.name,
            "fields_redacted_count": int(redacted_count[0]),
            "files_processed": [
                "manifest.json",
                "runs.json",
                "records.json",
                "outputs.json",
                "validation_receipts.json",
                "audit_events.json",
                "safety_notes.md",
            ],
            "redaction_rules_applied": {
                "public_demo": [
                    "mask actor identifiers in audit events",
                    "mask secret-like keys (token/secret/api_key/authorization/credential/password)",
                    "mask email/phone/mobile keys",
                    "redact source_metadata/source_ref",
                    "redact manifest source_store_dir",
                ],
                "internal_review": [
                    "mask secret-like keys (token/secret/api_key/authorization/credential/password)",
                ],
            }.get(prof, []),
            "note": "Redaction creates a sharing copy. It does not verify truth, approve decisions, or certify the bundle.",
        }

        notice = """# Redaction notice

This is a **redacted copy** of an AirOS evidence bundle.

- The original bundle is unchanged.
- Some fields were masked or removed according to the selected redaction profile.
- Redaction does **not** approve, certify, sign, execute, import, or publish anything.
- Final decisions remain with authorized human and institutional processes.
"""

        # Copy non-JSON files (README + safety notes) unchanged; do not copy any other extras from the source.
        readme_text = zin.read("README.md").decode("utf-8") if "README.md" in names else ""
        safety_text = zin.read("safety_notes.md").decode("utf-8")

    file_bytes: dict[str, bytes] = {
        "README.md": (readme_text or "").encode("utf-8"),
        "manifest.json": _stable_json(manifest_r).encode("utf-8"),
        "runs.json": _stable_json(runs_r).encode("utf-8"),
        "records.json": _stable_json(records_r).encode("utf-8"),
        "outputs.json": _stable_json(outputs_r).encode("utf-8"),
        "validation_receipts.json": _stable_json(receipts_r).encode("utf-8"),
        "audit_events.json": _stable_json(audits_r).encode("utf-8"),
        "safety_notes.md": safety_text.encode("utf-8"),
        "redaction_report.json": _stable_json(redaction_report).encode("utf-8"),
        "REDACTION_NOTICE.md": notice.encode("utf-8"),
    }

    hash_manifest_bytes = _build_hash_manifest(file_bytes=file_bytes, created_at=str(redaction_report.get("redacted_at") or _now_utc_iso()))

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for path, b in file_bytes.items():
            zout.writestr(path, b)
        zout.writestr("hash_manifest.json", hash_manifest_bytes)

    return out_path

