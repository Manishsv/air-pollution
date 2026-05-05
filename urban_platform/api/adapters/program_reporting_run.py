from __future__ import annotations

from typing import Any, Dict, List, Tuple

from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.receipt_helpers import (
    make_receipt_id_for_output,
    safe_errors,
    schema_ref_for_contract,
)
from urban_platform.api.validation import collect_validation_errors, manifest_has_artifact
from urban_platform.applications.program_reporting.review_packets import build_program_reporting_state_summary
from urban_platform.deployments.builder_registry import get_builder
from urban_platform.storage import (
    FileAirOsStore,
    StoredOutput,
    StoredRecord,
    StoredValidationReceipt,
    compute_payload_hash,
    now_utc_iso,
)

CONTRACT_SUBMISSION = "consumer_city_program_submission"
CONTRACT_REVIEW_PACKET = "consumer_fund_release_review_packet"
STATE_SUMMARY_CONTRACT = "internal_program_reporting_state_summary_demo"
DEFAULT_STATE_NODE = "state_urban_department_demo"


def _dedupe_by_submission_id(records: List[StoredRecord]) -> List[StoredRecord]:
    by_sid: Dict[str, StoredRecord] = {}
    for r in sorted(records, key=lambda x: x.received_at):
        sid = str(r.payload.get("submission_id") or "")
        if sid:
            by_sid[sid] = r
    return list(by_sid.values())


def load_program_reporting_submissions(
    store: FileAirOsStore,
    *,
    deployment_id: str,
    program_id: str,
    reporting_period: str,
) -> List[StoredRecord]:
    rows = store.list_records(deployment_id=deployment_id, contract_key=CONTRACT_SUBMISSION)
    matching: List[StoredRecord] = []
    for r in rows:
        p = r.payload
        if str(p.get("program_id") or "") != program_id:
            continue
        if str(p.get("reporting_period") or "") != reporting_period:
            continue
        matching.append(r)
    return _dedupe_by_submission_id(matching)


def execute_program_reporting_review_run(
    store: FileAirOsStore,
    *,
    deployment_id: str,
    program_id: str,
    reporting_period: str,
    run_id: str,
    application_id: str,
) -> Tuple[int, int]:
    """
    Consume stored city submissions and emit review packets + state summary outputs.

    Returns (records_processed, outputs_generated).
    """
    submissions = load_program_reporting_submissions(
        store,
        deployment_id=deployment_id,
        program_id=program_id,
        reporting_period=reporting_period,
    )
    if not submissions:
        return (0, 0)

    builder = get_builder(application_id).resolve_callable()

    payloads = [r.payload for r in submissions]
    packets: List[Dict[str, Any]] = []
    outputs = 0

    for sub in payloads:
        pkt = builder(sub)
        errs = collect_validation_errors(pkt, schema_name=CONTRACT_REVIEW_PACKET)
        if errs:
            stored_errs = safe_errors(errs)
            store.put_validation_receipt(
                StoredValidationReceipt(
                    receipt_id=make_receipt_id_for_output(f"out_invalid_pkt_{run_id}"),
                    deployment_id=deployment_id,
                    contract_key=CONTRACT_REVIEW_PACKET,
                    validation_target_type="output",
                    validation_target_id=str(pkt.get("packet_id") or "unknown"),
                    status="invalid",
                    validated_at=now_utc_iso(),
                    payload_hash=compute_payload_hash(pkt) if isinstance(pkt, dict) else None,
                    schema_ref=schema_ref_for_contract(CONTRACT_REVIEW_PACKET),
                    error_count=len(stored_errs),
                    errors=stored_errs,
                    metadata={"run_id": run_id, "application_id": application_id},
                )
            )
            raise ValueError("Built packet failed validation.")

        oid = f"out_{pkt['packet_id']}_{run_id}"
        store.put_output(
            StoredOutput(
                output_id=oid,
                deployment_id=deployment_id,
                contract_key=CONTRACT_REVIEW_PACKET,
                payload=pkt,
                generated_at=now_utc_iso(),
                generated_by="urban_platform.applications.program_reporting.review_packets.build_fund_release_review_packet",
                input_refs=[str(sub.get("submission_id") or "")],
                metadata={
                    "deployment_id": deployment_id,
                    "program_id": program_id,
                    "reporting_period": reporting_period,
                    "run_id": run_id,
                    "application_id": application_id,
                    "kind": "fund_release_review_packet",
                },
            )
        )
        outputs += 1

        store.put_validation_receipt(
            StoredValidationReceipt(
                receipt_id=make_receipt_id_for_output(oid),
                deployment_id=deployment_id,
                contract_key=CONTRACT_REVIEW_PACKET,
                validation_target_type="output",
                validation_target_id=oid,
                status="valid",
                validated_at=now_utc_iso(),
                payload_hash=compute_payload_hash(pkt) if isinstance(pkt, dict) else None,
                schema_ref=schema_ref_for_contract(CONTRACT_REVIEW_PACKET),
                error_count=0,
                errors=[],
                metadata={"run_id": run_id, "application_id": application_id},
            )
        )

        append_audit(
            store,
            deployment_id=deployment_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=oid,
            metadata={"contract_key": CONTRACT_REVIEW_PACKET, "application_id": application_id, "run_id": run_id},
        )
        packets.append(pkt)

    state_summary = build_program_reporting_state_summary(
        packets,
        city_submissions=payloads,
        state_node_id=DEFAULT_STATE_NODE,
        program_id=program_id,
        reporting_period=reporting_period,
    )
    state_oid = f"out_state_summary_{run_id}"
    # This demo summary contract may not be manifest-registered; if not present, skip schema validation.
    if manifest_has_artifact(STATE_SUMMARY_CONTRACT):
        errs_state = collect_validation_errors(state_summary, schema_name=STATE_SUMMARY_CONTRACT)
        if errs_state:
            stored_errs = safe_errors(errs_state)
            store.put_validation_receipt(
                StoredValidationReceipt(
                    receipt_id=make_receipt_id_for_output(state_oid),
                    deployment_id=deployment_id,
                    contract_key=STATE_SUMMARY_CONTRACT,
                    validation_target_type="output",
                    validation_target_id=state_oid,
                    status="invalid",
                    validated_at=now_utc_iso(),
                    payload_hash=compute_payload_hash(state_summary) if isinstance(state_summary, dict) else None,
                    schema_ref=schema_ref_for_contract(STATE_SUMMARY_CONTRACT),
                    error_count=len(stored_errs),
                    errors=stored_errs,
                    metadata={"run_id": run_id, "application_id": application_id},
                )
            )
            raise ValueError("Built state summary failed validation.")

    store.put_output(
        StoredOutput(
            output_id=state_oid,
            deployment_id=deployment_id,
            contract_key=STATE_SUMMARY_CONTRACT,
            payload=state_summary,
            generated_at=now_utc_iso(),
            generated_by="urban_platform.applications.program_reporting.review_packets.build_program_reporting_state_summary",
            input_refs=[str(p.get("packet_id") or "") for p in packets],
            metadata={
                "deployment_id": deployment_id,
                "program_id": program_id,
                "reporting_period": reporting_period,
                "run_id": run_id,
                "application_id": application_id,
                "kind": "state_program_summary",
            },
        )
    )
    outputs += 1
    if manifest_has_artifact(STATE_SUMMARY_CONTRACT):
        store.put_validation_receipt(
            StoredValidationReceipt(
                receipt_id=make_receipt_id_for_output(state_oid),
                deployment_id=deployment_id,
                contract_key=STATE_SUMMARY_CONTRACT,
                validation_target_type="output",
                validation_target_id=state_oid,
                status="valid",
                validated_at=now_utc_iso(),
                payload_hash=compute_payload_hash(state_summary) if isinstance(state_summary, dict) else None,
                schema_ref=schema_ref_for_contract(STATE_SUMMARY_CONTRACT),
                error_count=0,
                errors=[],
                metadata={"run_id": run_id, "application_id": application_id},
            )
        )

    append_audit(
        store,
        deployment_id=deployment_id,
        action="output_generated",
        resource_type="stored_output",
        resource_id=state_oid,
        metadata={"contract_key": STATE_SUMMARY_CONTRACT, "application_id": application_id, "run_id": run_id},
    )

    return (len(submissions), outputs)
