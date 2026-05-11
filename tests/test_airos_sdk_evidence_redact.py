from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from airos.os.sdk.evidence import export_evidence_bundle, inspect_evidence_bundle, redact_evidence_bundle, verify_evidence_bundle
from airos.os.storage.file_store import FileAirOsStore
from airos.os.storage.models import AuditEvent, StoredOutput, StoredRecord, StoredRun


def test_redact_public_demo_creates_new_zip_and_preserves_original(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    rec = store.put_record(
        StoredRecord(
            record_id="rec_1",
            deployment_id="dep_1",
            contract_key="provider_demo",
            payload={"email": "user@example.com", "token": "abc", "nested": {"api_key": "k"}},
            received_at="2026-05-06T00:00:00Z",
            metadata={"source_metadata": {"url": "http://example.com", "authorization": "bearer x"}},
        )
    )
    out = store.put_output(
        StoredOutput(
            output_id="out_1",
            deployment_id="dep_1",
            contract_key="consumer_demo",
            payload={"phone": "999", "secret": "s"},
            generated_at="2026-05-06T00:01:00Z",
            generated_by="app_demo",
            input_refs=[rec.record_id],
            metadata={"run_id": "run_1"},
        )
    )
    run = store.put_run(
        StoredRun(
            run_id="run_1",
            deployment_id="dep_1",
            application_id="app_demo",
            status="completed",
            started_at="2026-05-06T00:00:10Z",
            output_refs=[out.output_id],
            input_refs=[rec.record_id],
        )
    )
    store.append_audit_event(
        AuditEvent(
            event_id="ae_1",
            deployment_id="dep_1",
            actor="operator@example.com",
            action="application_run_completed",
            resource_type="run",
            resource_id=run.run_id,
            occurred_at="2026-05-06T00:01:10Z",
        )
    )

    out_dir = tmp_path / "evidence"
    orig = export_evidence_bundle(store_dir=store_dir, output_dir=out_dir, run_id="run_1")
    orig_bytes = orig.read_bytes()

    red_dir = tmp_path / "redacted"
    red = redact_evidence_bundle(bundle_path=orig, output_dir=red_dir, profile="public_demo")
    assert red.is_file()
    assert red.read_bytes() != orig_bytes
    assert orig.read_bytes() == orig_bytes, "Original bundle must not change"

    with zipfile.ZipFile(red, "r") as zz:
        assert "REDACTION_NOTICE.md" in zz.namelist()
        assert "redaction_report.json" in zz.namelist()
        assert "hash_manifest.json" in zz.namelist()
        audits = json.loads(zz.read("audit_events.json").decode("utf-8"))
        assert audits and audits[0]["actor"] == "redacted_actor"
        records = json.loads(zz.read("records.json").decode("utf-8"))
        assert records[0]["payload"]["email"] == "redacted"
        assert records[0]["payload"]["token"] == "redacted"
        assert records[0]["payload"]["nested"]["api_key"] == "redacted"

    # Redacted bundle can be inspected and verified
    inspect_evidence_bundle(bundle_path=red)
    rep = verify_evidence_bundle(bundle_path=red)
    assert rep["status"] in ("verified", "verified_with_warnings")


def test_invalid_profile_fails(tmp_path: Path) -> None:
    z = tmp_path / "x.zip"
    z.write_bytes(b"notzip")
    with pytest.raises(ValueError):
        redact_evidence_bundle(bundle_path=z, output_dir=tmp_path, profile="nope")

