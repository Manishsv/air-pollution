from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from urban_platform.sdk.evidence import export_evidence_bundle, inspect_evidence_bundle
from urban_platform.storage.file_store import FileAirOsStore
from urban_platform.storage.models import StoredRun, StoredValidationReceipt


def test_inspect_valid_export_succeeds(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_1",
            deployment_id="dep_1",
            application_id="app_1",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    store.put_validation_receipt(
        StoredValidationReceipt(
            receipt_id="vr_bad",
            deployment_id="dep_1",
            contract_key="x",
            validation_target_type="output",
            validation_target_id="out_x",
            status="invalid",
            validated_at="2026-05-06T00:00:10Z",
            error_count=2,
        )
    )
    out_dir = tmp_path / "evidence"
    z = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="run_1")

    rep = inspect_evidence_bundle(bundle_path=z)
    assert rep["bundle"]["run_id"] == "run_1"
    assert rep["validation_receipts"]["invalid_count"] >= 1
    assert rep["safety_notes_present"] is True
    assert rep["hash_manifest"]["present"] is True


def test_missing_manifest_fails(tmp_path: Path) -> None:
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("runs.json", "[]")
        zz.writestr("records.json", "[]")
        zz.writestr("outputs.json", "[]")
        zz.writestr("validation_receipts.json", "[]")
        zz.writestr("audit_events.json", "[]")
        zz.writestr("safety_notes.md", "ok")
    with pytest.raises(ValueError):
        inspect_evidence_bundle(bundle_path=z)


def test_unsafe_zip_path_fails(tmp_path: Path) -> None:
    z = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../manifest.json", "{}")
    with pytest.raises(ValueError):
        inspect_evidence_bundle(bundle_path=z)


def test_malformed_json_fails(tmp_path: Path) -> None:
    z = tmp_path / "malformed.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("manifest.json", json.dumps({"bundle_id": "b", "created_at": "t", "counts": {}}))
        zz.writestr("runs.json", "[")
        zz.writestr("records.json", "[]")
        zz.writestr("outputs.json", "[]")
        zz.writestr("validation_receipts.json", "[]")
        zz.writestr("audit_events.json", "[]")
        zz.writestr("safety_notes.md", "ok")
    with pytest.raises(Exception):
        inspect_evidence_bundle(bundle_path=z)

