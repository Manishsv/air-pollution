from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from airos.os.sdk.evidence import export_evidence_bundle, verify_evidence_bundle
from airos.os.storage.file_store import FileAirOsStore
from airos.os.storage.models import StoredOutput, StoredRecord, StoredRun


def test_verify_exported_bundle_is_verified_or_warned(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    rec = store.put_record(
        StoredRecord(
            record_id="rec_1",
            deployment_id="dep_1",
            contract_key="provider_x",
            payload={"x": 1},
            received_at="2026-05-06T00:00:00Z",
        )
    )
    out = store.put_output(
        StoredOutput(
            output_id="out_1",
            deployment_id="dep_1",
            contract_key="consumer_y",
            payload={"y": 2},
            generated_at="2026-05-06T00:01:00Z",
            generated_by="app_z",
            input_refs=[rec.record_id],
        )
    )
    store.put_run(
        StoredRun(
            run_id="run_1",
            deployment_id="dep_1",
            application_id="app_z",
            status="completed",
            started_at="2026-05-06T00:00:10Z",
            output_refs=[out.output_id],
            input_refs=[rec.record_id],
        )
    )
    out_dir = tmp_path / "evidence"
    z = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="run_1")

    rep = verify_evidence_bundle(bundle_path=z)
    assert rep["status"] in ("verified", "verified_with_warnings")
    assert "internal consistency only" in str(rep.get("note") or "").lower()


def test_manifest_count_mismatch_is_invalid(tmp_path: Path) -> None:
    z = tmp_path / "mismatch.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_id": "b",
                    "created_at": "t",
                    "counts": {"runs": 2, "records": 0, "outputs": 0, "validation_receipts": 0, "audit_events": 0},
                    "note": "not approval evidence",
                }
            ),
        )
        zz.writestr("runs.json", json.dumps([{"run_id": "r1", "status": "completed", "output_refs": []}]))
        zz.writestr("records.json", "[]")
        zz.writestr("outputs.json", "[]")
        zz.writestr("validation_receipts.json", "[]")
        zz.writestr("audit_events.json", "[]")
        zz.writestr("safety_notes.md", "no final government decision")
    rep = verify_evidence_bundle(bundle_path=z)
    assert rep["status"] == "invalid"


def test_missing_hash_manifest_is_warning_not_failure_for_legacy_bundle(tmp_path: Path) -> None:
    z = tmp_path / "legacy.zip"
    import zipfile

    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_id": "b",
                    "created_at": "t",
                    "counts": {"runs": 1, "records": 0, "outputs": 0, "validation_receipts": 0, "audit_events": 0},
                    "note": "not approval evidence",
                }
            ),
        )
        zz.writestr("runs.json", json.dumps([{"run_id": "r1", "status": "completed", "output_refs": []}]))
        zz.writestr("records.json", "[]")
        zz.writestr("outputs.json", "[]")
        zz.writestr("validation_receipts.json", "[]")
        zz.writestr("audit_events.json", "[]")
        zz.writestr("safety_notes.md", "no final government decision")

    rep = verify_evidence_bundle(bundle_path=z)
    assert rep["status"] in ("verified", "verified_with_warnings")
    assert any("hash_manifest.json missing" in w.lower() for w in rep.get("warnings") or [])


def test_tampered_payload_hash_is_invalid(tmp_path: Path) -> None:
    # Create minimal bundle where payload_hash exists and payload is modified.
    z = tmp_path / "tamper.zip"
    record = {"record_id": "rec_1", "deployment_id": "dep", "contract_key": "k", "payload": {"x": 1}, "received_at": "t"}
    from airos.os.storage.file_store import compute_payload_hash

    record["payload_hash"] = compute_payload_hash(record["payload"])
    tampered = dict(record)
    tampered["payload"] = {"x": 999}

    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr(
            "manifest.json",
            json.dumps(
                {
                    "bundle_id": "b",
                    "created_at": "t",
                    "counts": {"runs": 0, "records": 1, "outputs": 0, "validation_receipts": 0, "audit_events": 0},
                    "note": "not approval evidence",
                }
            ),
        )
        zz.writestr("runs.json", "[]")
        zz.writestr("records.json", json.dumps([tampered]))
        zz.writestr("outputs.json", "[]")
        zz.writestr("validation_receipts.json", "[]")
        zz.writestr("audit_events.json", "[]")
        zz.writestr("safety_notes.md", "no final government decision")
    rep = verify_evidence_bundle(bundle_path=z)
    assert rep["status"] == "invalid"


def test_tampering_detected_by_hash_manifest(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_hm",
            deployment_id="dep_hm",
            application_id="app_hm",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    out_dir = tmp_path / "evidence"
    z = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="run_hm")

    tampered = tmp_path / "tampered.zip"
    import zipfile

    with zipfile.ZipFile(z, "r") as zin, zipfile.ZipFile(tampered, "w") as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name == "runs.json":
                data = data.replace(b"run_hm", b"run_tampered")
            zout.writestr(name, data)

    rep = verify_evidence_bundle(bundle_path=tampered)
    assert rep["status"] == "invalid"

