from __future__ import annotations

from pathlib import Path

from urban_platform.storage.file_store import FileAirOsStore, compute_payload_hash
from urban_platform.storage.models import AuditEvent, StoredOutput, StoredRecord


def test_put_get_list_record(tmp_path: Path) -> None:
    store = FileAirOsStore(tmp_path)
    r = StoredRecord(
        record_id="rec_1",
        deployment_id="dep_a",
        contract_key="provider_demo",
        payload={"a": 1},
        received_at="2026-01-01T00:00:00Z",
        source_ref="fixture:demo",
        payload_hash=None,
        metadata={"k": "v"},
    )
    stored = store.put_record(r)
    assert stored.payload_hash
    assert store.get_record("rec_1") is not None
    assert len(store.list_records()) == 1
    assert len(store.list_records(deployment_id="dep_a")) == 1
    assert len(store.list_records(deployment_id="dep_b")) == 0
    assert len(store.list_records(contract_key="provider_demo")) == 1
    assert len(store.list_records(contract_key="other")) == 0


def test_put_get_list_output(tmp_path: Path) -> None:
    store = FileAirOsStore(tmp_path)
    o = StoredOutput(
        output_id="out_1",
        deployment_id="dep_a",
        contract_key="consumer_demo",
        payload={"x": 2},
        generated_at="2026-01-01T00:05:00Z",
        generated_by="builder_demo",
        input_refs=["rec_1"],
        payload_hash=None,
        metadata={},
    )
    stored = store.put_output(o)
    assert stored.payload_hash
    assert store.get_output("out_1") is not None
    assert len(store.list_outputs()) == 1
    assert len(store.list_outputs(deployment_id="dep_a")) == 1
    assert len(store.list_outputs(contract_key="consumer_demo")) == 1


def test_append_list_audit_events(tmp_path: Path) -> None:
    store = FileAirOsStore(tmp_path)
    e = AuditEvent(
        event_id="evt_1",
        deployment_id="dep_a",
        actor="system",
        action="ingest",
        resource_type="record",
        resource_id="rec_1",
        occurred_at="2026-01-01T00:01:00Z",
        metadata={"ok": True},
    )
    store.append_audit_event(e)
    assert len(store.list_audit_events()) == 1
    assert len(store.list_audit_events(deployment_id="dep_a")) == 1
    assert len(store.list_audit_events(deployment_id="dep_b")) == 0


def test_missing_files_return_empty_lists(tmp_path: Path) -> None:
    store = FileAirOsStore(tmp_path)
    # root dir exists, but JSONL files may not.
    assert store.list_records() == []
    assert store.list_outputs() == []
    assert store.list_audit_events() == []


def test_payload_hash_deterministic_for_key_order() -> None:
    a = {"b": 2, "a": 1, "nested": {"z": 9, "y": 8}}
    b = {"a": 1, "nested": {"y": 8, "z": 9}, "b": 2}
    assert compute_payload_hash(a) == compute_payload_hash(b)


def test_optional_program_reporting_output_can_be_stored(tmp_path: Path) -> None:
    # Optional integration demonstration: store a known output shape without wiring the runner.
    store = FileAirOsStore(tmp_path)
    payload = {
        "state_node_id": "node:state_urban_department_demo",
        "program_id": "stormwater_resilience_grant_2026",
        "reporting_period": "2026_Q1",
    }
    o = StoredOutput(
        output_id="state_summary_1",
        deployment_id="program_reporting_state_demo",
        contract_key="state_program_summary",
        payload=payload,
        generated_at="2026-01-01T00:05:00Z",
        generated_by="demo_test",
        input_refs=[],
        payload_hash=None,
        metadata={},
    )
    store.put_output(o)
    got = store.get_output("state_summary_1")
    assert got is not None
    assert got.deployment_id == "program_reporting_state_demo"

