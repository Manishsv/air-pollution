from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.settings import api_store_dir
from urban_platform.api.validation import collect_validation_errors
from urban_platform.applications.program_reporting.review_packets import (
    build_fund_release_review_packet,
    build_program_reporting_state_summary,
)
from urban_platform.storage import FileAirOsStore, StoredOutput, StoredRecord, compute_payload_hash, now_utc_iso

CONTRACT_SUBMISSION = "consumer_city_program_submission"
CONTRACT_REVIEW_PACKET = "consumer_fund_release_review_packet"
CONTRACT_STATE_SUMMARY = "internal_program_reporting_state_summary_demo"

DEFAULT_DEPLOYMENT_ID = "program_reporting_state_demo"
DEFAULT_PROGRAM_ID = "stormwater_resilience_grant_2026"
DEFAULT_REPORTING_PERIOD = "2026_Q1"
DEFAULT_STATE_NODE = "state_urban_department_demo"

API_SAFE_WARNINGS = [
    "Pilot-runtime API: review support only. No disbursement, treasury, or enforcement automation is performed by this service.",
    "Fund release and finance authorization remain outside AirOS and require appropriately authorized human processes.",
]

router = APIRouter(prefix="/program-reporting", tags=["program-reporting"])


def get_store() -> FileAirOsStore:
    return FileAirOsStore(api_store_dir())


def _dedupe_submissions_latest(records: List[StoredRecord]) -> List[StoredRecord]:
    by_sid: dict[str, StoredRecord] = {}
    for r in sorted(records, key=lambda x: x.received_at):
        sid = str(r.payload.get("submission_id") or "")
        if sid:
            by_sid[sid] = r
    return list(by_sid.values())


def _load_run_submissions(
    store: FileAirOsStore,
    *,
    deployment_id: str,
    program_id: str,
    reporting_period: str,
) -> List[StoredRecord]:
    records = store.list_records(deployment_id=deployment_id, contract_key=CONTRACT_SUBMISSION)
    matching: List[StoredRecord] = []
    for r in records:
        p = r.payload
        if str(p.get("program_id") or "") != program_id:
            continue
        if str(p.get("reporting_period") or "") != reporting_period:
            continue
        matching.append(r)
    return _dedupe_submissions_latest(matching)


def _output_matches_filters(
    o: StoredOutput,
    *,
    deployment_id: Optional[str],
    program_id: Optional[str],
    reporting_period: Optional[str],
) -> bool:
    md = o.metadata or {}
    if deployment_id is not None and str(md.get("deployment_id") or "") != deployment_id:
        return False
    if program_id is not None and str(md.get("program_id") or "") != program_id:
        return False
    if reporting_period is not None and str(md.get("reporting_period") or "") != reporting_period:
        return False
    return True


def _packet_matches_filters(
    pkt: Dict[str, Any],
    *,
    program_id: Optional[str],
    reporting_period: Optional[str],
) -> bool:
    if program_id is not None and str(pkt.get("program_id") or "") != program_id:
        return False
    if reporting_period is not None and str(pkt.get("reporting_period") or "") != reporting_period:
        return False
    return True


@router.post("/submissions")
def post_city_submission(
    payload: Dict[str, Any] = Body(...),
    deployment_id: str = Query(DEFAULT_DEPLOYMENT_ID, description="Logical deployment scope for stored records."),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    errors = collect_validation_errors(payload, schema_name=CONTRACT_SUBMISSION)
    if errors:
        append_audit(
            store,
            deployment_id=deployment_id,
            action="program_reporting_submission_rejected",
            resource_type="submission",
            resource_id=str(payload.get("submission_id") or "unknown"),
            metadata={"errors": errors[:50]},
        )
        raise HTTPException(
            status_code=400,
            detail={"message": "Submission failed contract validation.", "errors": errors},
        )

    submission_id = str(payload["submission_id"])
    record_id = f"rec_api_{deployment_id}_{submission_id}"
    meta = {
        "deployment_id": deployment_id,
        "ingested_via": "api",
        "program_id": str(payload.get("program_id") or ""),
        "reporting_period": str(payload.get("reporting_period") or ""),
    }
    rec = StoredRecord(
        record_id=record_id,
        deployment_id=deployment_id,
        contract_key=CONTRACT_SUBMISSION,
        payload=payload,
        received_at=now_utc_iso(),
        source_ref="api:POST /program-reporting/submissions",
        metadata=meta,
    )
    stored = store.put_record(rec)
    ph = stored.payload_hash or compute_payload_hash(payload)
    append_audit(
        store,
        deployment_id=deployment_id,
        action="program_reporting_submission_ingested",
        resource_type="stored_record",
        resource_id=record_id,
        metadata={"contract_key": CONTRACT_SUBMISSION, "payload_hash": ph},
    )
    extra = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    warnings = [*API_SAFE_WARNINGS, *extra]
    return {
        "status": "accepted",
        "record_id": record_id,
        "contract_key": CONTRACT_SUBMISSION,
        "payload_hash": ph,
        "warnings": warnings,
    }


@router.post("/run")
def run_program_reporting(
    body: Optional[Dict[str, Any]] = Body(default=None),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    b = body or {}
    deployment_id = str(b.get("deployment_id") or DEFAULT_DEPLOYMENT_ID).strip()
    program_id = str(b.get("program_id") or DEFAULT_PROGRAM_ID).strip()
    reporting_period = str(b.get("reporting_period") or DEFAULT_REPORTING_PERIOD).strip()

    submissions = _load_run_submissions(
        store,
        deployment_id=deployment_id,
        program_id=program_id,
        reporting_period=reporting_period,
    )
    if not submissions:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No stored city program submissions found. POST submissions first.",
                "deployment_id": deployment_id,
                "program_id": program_id,
                "reporting_period": reporting_period,
            },
        )

    run_id = uuid.uuid4().hex[:16]
    append_audit(
        store,
        deployment_id=deployment_id,
        action="program_reporting_run_started",
        resource_type="program_reporting_run",
        resource_id=run_id,
        metadata={"program_id": program_id, "reporting_period": reporting_period, "submission_count": len(submissions)},
    )

    payloads = [r.payload for r in submissions]
    packets: List[Dict[str, Any]] = []
    output_refs: List[Dict[str, Any]] = []

    for sub in payloads:
        pkt = build_fund_release_review_packet(sub, state_node_id=DEFAULT_STATE_NODE)
        pkt_errors = collect_validation_errors(pkt, schema_name=CONTRACT_REVIEW_PACKET)
        if pkt_errors:
            raise HTTPException(
                status_code=500,
                detail={"message": "Generated review packet failed validation (internal).", "errors": pkt_errors},
            )
        oid = f"out_{pkt['packet_id']}_{run_id}"
        omd = {
            "deployment_id": deployment_id,
            "program_id": program_id,
            "reporting_period": reporting_period,
            "run_id": run_id,
            "kind": "fund_release_review_packet",
        }
        store.put_output(
            StoredOutput(
                output_id=oid,
                deployment_id=deployment_id,
                contract_key=CONTRACT_REVIEW_PACKET,
                payload=pkt,
                generated_at=now_utc_iso(),
                generated_by="urban_platform.applications.program_reporting.review_packets.build_fund_release_review_packet",
                input_refs=[str(sub.get("submission_id") or "")],
                metadata=omd,
            )
        )
        append_audit(
            store,
            deployment_id=deployment_id,
            action="program_reporting_output_generated",
            resource_type="stored_output",
            resource_id=oid,
            metadata={"contract_key": CONTRACT_REVIEW_PACKET, "run_id": run_id},
        )
        packets.append(pkt)
        output_refs.append({"output_id": oid, "contract_key": CONTRACT_REVIEW_PACKET, "kind": "review_packet"})

    state_summary = build_program_reporting_state_summary(
        packets,
        city_submissions=payloads,
        state_node_id=DEFAULT_STATE_NODE,
        program_id=program_id,
        reporting_period=reporting_period,
    )
    state_oid = f"out_state_summary_{run_id}"
    store.put_output(
        StoredOutput(
            output_id=state_oid,
            deployment_id=deployment_id,
            contract_key=CONTRACT_STATE_SUMMARY,
            payload=state_summary,
            generated_at=now_utc_iso(),
            generated_by="urban_platform.applications.program_reporting.review_packets.build_program_reporting_state_summary",
            input_refs=[str(p.get("packet_id") or "") for p in packets],
            metadata={
                "deployment_id": deployment_id,
                "program_id": program_id,
                "reporting_period": reporting_period,
                "run_id": run_id,
                "kind": "state_program_summary",
            },
        )
    )
    append_audit(
        store,
        deployment_id=deployment_id,
        action="program_reporting_output_generated",
        resource_type="stored_output",
        resource_id=state_oid,
        metadata={"contract_key": CONTRACT_STATE_SUMMARY, "run_id": run_id},
    )
    output_refs.append({"output_id": state_oid, "contract_key": CONTRACT_STATE_SUMMARY, "kind": "state_summary"})

    append_audit(
        store,
        deployment_id=deployment_id,
        action="program_reporting_run_completed",
        resource_type="program_reporting_run",
        resource_id=run_id,
        metadata={
            "submissions_processed": len(submissions),
            "review_packets_generated": len(packets),
            "program_id": program_id,
            "reporting_period": reporting_period,
        },
    )

    return {
        "status": "completed",
        "run_id": run_id,
        "submissions_processed": len(submissions),
        "review_packets_generated": len(packets),
        "outputs": output_refs,
        "warnings": API_SAFE_WARNINGS,
    }


@router.get("/review-packets")
def list_review_packets(
    deployment_id: Optional[str] = Query(None),
    program_id: Optional[str] = Query(None),
    reporting_period: Optional[str] = Query(None),
    store: FileAirOsStore = Depends(get_store),
) -> List[Dict[str, Any]]:
    rows = store.list_outputs(deployment_id=None, contract_key=CONTRACT_REVIEW_PACKET)
    seen: set[str] = set()
    packets: List[Dict[str, Any]] = []
    for o in sorted(rows, key=lambda x: x.generated_at):
        if o.output_id in seen:
            continue
        seen.add(o.output_id)
        if not _output_matches_filters(o, deployment_id=deployment_id, program_id=program_id, reporting_period=reporting_period):
            continue
        if not _packet_matches_filters(o.payload, program_id=program_id, reporting_period=reporting_period):
            continue
        packets.append(o.payload)
    return packets


@router.get("/state-summary")
def get_state_summary(
    deployment_id: Optional[str] = Query(None),
    program_id: Optional[str] = Query(None),
    reporting_period: Optional[str] = Query(None),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    candidates = store.list_outputs(deployment_id=None, contract_key=CONTRACT_STATE_SUMMARY)
    filtered: List[StoredOutput] = []
    for o in candidates:
        if not _output_matches_filters(o, deployment_id=deployment_id, program_id=program_id, reporting_period=reporting_period):
            continue
        filtered.append(o)
    if not filtered:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "No stored state program summary found for the given filters. Run POST /program-reporting/run after ingesting submissions.",
            },
        )
    latest = max(filtered, key=lambda x: x.generated_at)
    return latest.payload

