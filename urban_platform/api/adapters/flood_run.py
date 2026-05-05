from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.receipt_helpers import make_receipt_id_for_output, safe_errors, schema_ref_for_contract
from urban_platform.api.validation import collect_validation_errors
from urban_platform.connectors.flood.ingest_file import (
    ingest_drainage_asset_feed_json,
    ingest_flood_incident_feed_json,
    ingest_rainfall_observation_feed_json,
)
from urban_platform.deployments.builder_registry import get_builder
from urban_platform.processing.flood.features import build_flood_feature_rows
from urban_platform.storage import (
    FileAirOsStore,
    StoredOutput,
    StoredRecord,
    StoredValidationReceipt,
    compute_payload_hash,
    now_utc_iso,
)

CONTRACT_RAINFALL = "provider_rainfall_observation_feed"
CONTRACT_INCIDENT = "provider_flood_incident_feed"
CONTRACT_DRAINAGE = "provider_drainage_asset_feed"

OUT_DASHBOARD = "consumer_flood_risk_dashboard"
OUT_DECISION_PACKET = "consumer_flood_decision_packet"
OUT_FIELD_TASK = "consumer_field_verification_task"

FLOOD_PILOT_WARNINGS: List[str] = [
    "fixture/demo data only",
    "decision support only",
    "field verification required",
    "no emergency orders",
]


def required_flood_input_contracts() -> List[str]:
    return [CONTRACT_RAINFALL, CONTRACT_INCIDENT, CONTRACT_DRAINAGE]


def _latest_record(records: Sequence[StoredRecord]) -> StoredRecord | None:
    if not records:
        return None
    return sorted(records, key=lambda r: r.received_at)[-1]


def missing_flood_inputs(store: FileAirOsStore, *, deployment_id: str) -> List[str]:
    missing: List[str] = []
    for ck in required_flood_input_contracts():
        rows = store.list_records(deployment_id=deployment_id, contract_key=ck)
        if not rows:
            missing.append(ck)
    return missing


def _write_payload_to_temp_json(payload: Dict[str, Any]) -> Path:
    td = tempfile.mkdtemp(prefix="airos_flood_ingest_")
    p = Path(td) / "payload.json"
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def _load_latest_payload(store: FileAirOsStore, *, deployment_id: str, contract_key: str) -> Dict[str, Any]:
    rows = store.list_records(deployment_id=deployment_id, contract_key=contract_key)
    rec = _latest_record(rows)
    if rec is None:
        raise ValueError(f"Missing required record: {contract_key}")
    if not isinstance(rec.payload, dict):
        raise ValueError(f"Record payload must be an object for contract {contract_key}")
    return dict(rec.payload)


def execute_flood_demo_run(
    store: FileAirOsStore,
    *,
    deployment_id: str,
    run_id: str,
    requested_application_id: str,
) -> Tuple[int, int]:
    """
    Flood demo execution for the generic Core API.

    Loads latest provider feed payloads from StoredRecord, normalizes them using the existing
    fixture ingestors, builds feature rows, then generates:
    - consumer_flood_risk_dashboard (single payload)
    - consumer_flood_decision_packet (one StoredOutput per packet)
    - consumer_field_verification_task (one StoredOutput per task)

    Returns (records_processed, outputs_generated).
    """
    rainfall_payload = _load_latest_payload(store, deployment_id=deployment_id, contract_key=CONTRACT_RAINFALL)
    incident_payload = _load_latest_payload(store, deployment_id=deployment_id, contract_key=CONTRACT_INCIDENT)
    drainage_payload = _load_latest_payload(store, deployment_id=deployment_id, contract_key=CONTRACT_DRAINAGE)

    rainfall_path = _write_payload_to_temp_json(rainfall_payload)
    incident_path = _write_payload_to_temp_json(incident_payload)
    drainage_path = _write_payload_to_temp_json(drainage_payload)

    rainfall_obs, _ = ingest_rainfall_observation_feed_json(json_path=rainfall_path)
    incident_events, _ = ingest_flood_incident_feed_json(json_path=incident_path)
    drainage_entities, _ = ingest_drainage_asset_feed_json(json_path=drainage_path)

    feature_rows, _stats = build_flood_feature_rows(
        rainfall_obs=rainfall_obs,
        incident_events=incident_events,
        drainage_entities=drainage_entities,
    )

    dashboard_builder = get_builder("flood_risk_dashboard_payload").resolve_callable()
    packets_builder = get_builder("flood_decision_packets").resolve_callable()
    tasks_builder = get_builder("flood_field_verification_tasks").resolve_callable()

    dashboard_payload = dashboard_builder(feature_rows)
    packets = packets_builder(feature_rows)
    tasks = tasks_builder(packets)

    # Validate outputs (fail closed).
    errs_dash = collect_validation_errors(dashboard_payload, schema_name=OUT_DASHBOARD)
    if errs_dash:
        stored_errs = safe_errors(errs_dash)
        store.put_validation_receipt(
            StoredValidationReceipt(
                receipt_id=make_receipt_id_for_output(f"out_invalid_dash_{run_id}"),
                deployment_id=deployment_id,
                contract_key=OUT_DASHBOARD,
                validation_target_type="output",
                validation_target_id=f"out_invalid_dash_{run_id}",
                status="invalid",
                validated_at=now_utc_iso(),
                payload_hash=compute_payload_hash(dashboard_payload) if isinstance(dashboard_payload, dict) else None,
                schema_ref=schema_ref_for_contract(OUT_DASHBOARD),
                error_count=len(stored_errs),
                errors=stored_errs,
                metadata={"run_id": run_id, "application_id": "flood_risk_dashboard_payload"},
            )
        )
        raise ValueError("Generated flood dashboard payload failed validation.")
    for pkt in packets:
        errs = collect_validation_errors(pkt, schema_name=OUT_DECISION_PACKET)
        if errs:
            stored_errs = safe_errors(errs)
            store.put_validation_receipt(
                StoredValidationReceipt(
                    receipt_id=make_receipt_id_for_output(f"out_invalid_packet_{run_id}"),
                    deployment_id=deployment_id,
                    contract_key=OUT_DECISION_PACKET,
                    validation_target_type="output",
                    validation_target_id=str(pkt.get("packet_id") or "unknown"),
                    status="invalid",
                    validated_at=now_utc_iso(),
                    payload_hash=compute_payload_hash(pkt) if isinstance(pkt, dict) else None,
                    schema_ref=schema_ref_for_contract(OUT_DECISION_PACKET),
                    error_count=len(stored_errs),
                    errors=stored_errs,
                    metadata={"run_id": run_id, "application_id": "flood_decision_packets"},
                )
            )
            raise ValueError("Generated flood decision packet failed validation.")
    for t in tasks:
        errs = collect_validation_errors(t, schema_name=OUT_FIELD_TASK)
        if errs:
            stored_errs = safe_errors(errs)
            store.put_validation_receipt(
                StoredValidationReceipt(
                    receipt_id=make_receipt_id_for_output(f"out_invalid_task_{run_id}"),
                    deployment_id=deployment_id,
                    contract_key=OUT_FIELD_TASK,
                    validation_target_type="output",
                    validation_target_id=str(t.get("task_id") or "unknown"),
                    status="invalid",
                    validated_at=now_utc_iso(),
                    payload_hash=compute_payload_hash(t) if isinstance(t, dict) else None,
                    schema_ref=schema_ref_for_contract(OUT_FIELD_TASK),
                    error_count=len(stored_errs),
                    errors=stored_errs,
                    metadata={"run_id": run_id, "application_id": "flood_field_verification_tasks"},
                )
            )
            raise ValueError("Generated flood field verification task failed validation.")

    outputs = 0

    # Persist dashboard payload.
    dash_oid = f"out_{deployment_id}_flood_risk_dashboard_{run_id}"
    store.put_output(
        StoredOutput(
            output_id=dash_oid,
            deployment_id=deployment_id,
            contract_key=OUT_DASHBOARD,
            payload=dashboard_payload,
            generated_at=now_utc_iso(),
            generated_by="application:flood_risk_dashboard_payload",
            input_refs=[CONTRACT_RAINFALL, CONTRACT_INCIDENT, CONTRACT_DRAINAGE],
            metadata={
                "deployment_id": deployment_id,
                "run_id": run_id,
                "application_id": "flood_risk_dashboard_payload",
                "requested_application_id": requested_application_id,
                "kind": "flood_risk_dashboard_payload",
            },
        )
    )
    outputs += 1

    store.put_validation_receipt(
        StoredValidationReceipt(
            receipt_id=make_receipt_id_for_output(dash_oid),
            deployment_id=deployment_id,
            contract_key=OUT_DASHBOARD,
            validation_target_type="output",
            validation_target_id=dash_oid,
            status="valid",
            validated_at=now_utc_iso(),
            payload_hash=compute_payload_hash(dashboard_payload) if isinstance(dashboard_payload, dict) else None,
            schema_ref=schema_ref_for_contract(OUT_DASHBOARD),
            error_count=0,
            errors=[],
            metadata={"run_id": run_id, "application_id": "flood_risk_dashboard_payload"},
        )
    )

    append_audit(
        store,
        deployment_id=deployment_id,
        action="output_generated",
        resource_type="stored_output",
        resource_id=dash_oid,
        metadata={"contract_key": OUT_DASHBOARD, "application_id": "flood_risk_dashboard_payload", "run_id": run_id},
    )

    # Persist packets and tasks as one output per item (contract-key consistent).
    for i, pkt in enumerate(packets):
        oid = f"out_{deployment_id}_decision_packet_{run_id}_{i}"
        store.put_output(
            StoredOutput(
                output_id=oid,
                deployment_id=deployment_id,
                contract_key=OUT_DECISION_PACKET,
                payload=pkt,
                generated_at=now_utc_iso(),
                generated_by="application:flood_decision_packets",
                input_refs=[dash_oid],
                metadata={
                    "deployment_id": deployment_id,
                    "run_id": run_id,
                    "application_id": "flood_decision_packets",
                    "requested_application_id": requested_application_id,
                    "kind": "flood_decision_packet",
                },
            )
        )
        outputs += 1

        store.put_validation_receipt(
            StoredValidationReceipt(
                receipt_id=make_receipt_id_for_output(oid),
                deployment_id=deployment_id,
                contract_key=OUT_DECISION_PACKET,
                validation_target_type="output",
                validation_target_id=oid,
                status="valid",
                validated_at=now_utc_iso(),
                payload_hash=compute_payload_hash(pkt) if isinstance(pkt, dict) else None,
                schema_ref=schema_ref_for_contract(OUT_DECISION_PACKET),
                error_count=0,
                errors=[],
                metadata={"run_id": run_id, "application_id": "flood_decision_packets"},
            )
        )

        append_audit(
            store,
            deployment_id=deployment_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=oid,
            metadata={"contract_key": OUT_DECISION_PACKET, "application_id": "flood_decision_packets", "run_id": run_id},
        )

    for i, task in enumerate(tasks):
        oid = f"out_{deployment_id}_field_task_{run_id}_{i}"
        store.put_output(
            StoredOutput(
                output_id=oid,
                deployment_id=deployment_id,
                contract_key=OUT_FIELD_TASK,
                payload=task,
                generated_at=now_utc_iso(),
                generated_by="application:flood_field_verification_tasks",
                input_refs=[str(i) for i in range(len(packets))],
                metadata={
                    "deployment_id": deployment_id,
                    "run_id": run_id,
                    "application_id": "flood_field_verification_tasks",
                    "requested_application_id": requested_application_id,
                    "kind": "flood_field_verification_task",
                },
            )
        )
        outputs += 1

        store.put_validation_receipt(
            StoredValidationReceipt(
                receipt_id=make_receipt_id_for_output(oid),
                deployment_id=deployment_id,
                contract_key=OUT_FIELD_TASK,
                validation_target_type="output",
                validation_target_id=oid,
                status="valid",
                validated_at=now_utc_iso(),
                payload_hash=compute_payload_hash(task) if isinstance(task, dict) else None,
                schema_ref=schema_ref_for_contract(OUT_FIELD_TASK),
                error_count=0,
                errors=[],
                metadata={"run_id": run_id, "application_id": "flood_field_verification_tasks"},
            )
        )

        append_audit(
            store,
            deployment_id=deployment_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=oid,
            metadata={"contract_key": OUT_FIELD_TASK, "application_id": "flood_field_verification_tasks", "run_id": run_id},
        )

    # We consider one record per required contract processed (latest-in per contract).
    return 3, outputs

