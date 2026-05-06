from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from urban_platform.sdk.evidence import export_evidence_bundle
from urban_platform.storage.file_store import FileAirOsStore
from urban_platform.storage.models import AuditEvent, StoredOutput, StoredRecord, StoredRun, StoredValidationReceipt


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes() if p.exists() else b""


def test_export_by_run_id_creates_zip_and_is_read_only(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)

    rec = store.put_record(
        StoredRecord(
            record_id="rec_1",
            deployment_id="demo_dep",
            contract_key="provider_x",
            payload={"x": 1},
            received_at="2026-05-06T00:00:00Z",
        )
    )
    out = store.put_output(
        StoredOutput(
            output_id="out_1",
            deployment_id="demo_dep",
            contract_key="consumer_y",
            payload={"y": 2},
            generated_at="2026-05-06T00:01:00Z",
            generated_by="app_z",
            input_refs=[rec.record_id],
        )
    )
    run = store.put_run(
        StoredRun(
            run_id="run_1",
            deployment_id="demo_dep",
            application_id="app_z",
            status="completed",
            started_at="2026-05-06T00:00:10Z",
            completed_at="2026-05-06T00:01:10Z",
            input_refs=[rec.record_id],
            output_refs=[out.output_id],
            records_processed=1,
            outputs_generated=1,
        )
    )
    store.put_validation_receipt(
        StoredValidationReceipt(
            receipt_id="vr_1",
            deployment_id="demo_dep",
            contract_key="consumer_y",
            validation_target_type="output",
            validation_target_id=out.output_id,
            status="valid",
            validated_at="2026-05-06T00:01:05Z",
            error_count=0,
        )
    )
    store.append_audit_event(
        AuditEvent(
            event_id="ae_1",
            deployment_id="demo_dep",
            actor="core_api",
            action="application_run_completed",
            resource_type="run",
            resource_id=run.run_id,
            occurred_at="2026-05-06T00:01:10Z",
            metadata={"run_id": run.run_id},
        )
    )

    before = {p.name: _read_bytes(p) for p in store_dir.iterdir()}

    out_dir = tmp_path / "evidence"
    z = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="run_1")
    assert z.is_file()
    assert z.suffix == ".zip"

    after = {p.name: _read_bytes(p) for p in store_dir.iterdir()}
    assert before == after, "Evidence export must not mutate the store"

    with zipfile.ZipFile(z, "r") as zz:
        names = set(zz.namelist())
        for req in (
            "README.md",
            "manifest.json",
            "hash_manifest.json",
            "runs.json",
            "records.json",
            "outputs.json",
            "validation_receipts.json",
            "audit_events.json",
            "safety_notes.md",
        ):
            assert req in names
        hm = json.loads(zz.read("hash_manifest.json").decode("utf-8"))
        assert hm.get("algorithm") == "sha256"
        paths = [x.get("path") for x in (hm.get("files") or []) if isinstance(x, dict)]
        assert "hash_manifest.json" not in paths
        manifest = json.loads(zz.read("manifest.json").decode("utf-8"))
        assert manifest["note"].lower().find("not approval") >= 0
        assert manifest["counts"]["runs"] == 1


def test_export_by_deployment_id_works(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_a",
            deployment_id="dep_a",
            application_id="app_a",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    out_dir = tmp_path / "evidence"
    z = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, deployment_id="dep_a")
    assert z.is_file()


def test_unknown_run_id_fails(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    FileAirOsStore(store_dir)
    out_dir = tmp_path / "evidence"
    with pytest.raises(ValueError):
        export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="nope")

