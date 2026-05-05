from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.constants import API_PILOT_SAFE_WARNINGS
from urban_platform.api.deps import get_store
from urban_platform.api.validation import collect_validation_errors, manifest_has_artifact
from urban_platform.specifications.conformance import load_manifest
from urban_platform.storage import FileAirOsStore, StoredRecord, compute_payload_hash, now_utc_iso

router = APIRouter(tags=["records"])

DEFAULT_DEPLOYMENT_ID = "program_reporting_state_demo"


def _make_record_id(deployment_id: str, contract_key: str, payload: Dict[str, Any]) -> str:
    stable = str(payload.get("submission_id") or payload.get("record_id") or uuid.uuid4().hex)
    return f"rec_api_{deployment_id}_{contract_key}_{stable}"[:220]


def _record_to_public_dict(r: StoredRecord) -> Dict[str, Any]:
    return {
        "record_id": r.record_id,
        "deployment_id": r.deployment_id,
        "contract_key": r.contract_key,
        "payload": r.payload,
        "received_at": r.received_at,
        "source_ref": r.source_ref,
        "payload_hash": r.payload_hash,
        "metadata": r.metadata,
    }


@router.post("/records/{contract_key}")
def ingest_record(
    contract_key: str,
    payload: Dict[str, Any] = Body(...),
    deployment_id: str = Query(
        DEFAULT_DEPLOYMENT_ID,
        description="Deployment scope persisted on StoredRecord.metadata and used by application runs.",
    ),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    ck = str(contract_key or "").strip()
    if not manifest_has_artifact(ck):
        raise HTTPException(status_code=404, detail={"message": f"Unknown contract_key {ck!r} (not in manifest)."})
    errs = collect_validation_errors(payload, schema_name=ck)
    if errs:
        append_audit(
            store,
            deployment_id=deployment_id,
            action="record_rejected",
            resource_type="submission",
            resource_id=str(payload.get("submission_id") or "unknown"),
            metadata={"contract_key": ck, "errors": errs[:50]},
        )
        raise HTTPException(
            status_code=400,
            detail={"message": "Payload failed contract validation.", "errors": errs},
        )

    rid = _make_record_id(deployment_id, ck, payload)
    meta = {
        "deployment_id": deployment_id,
        "contract_key": ck,
        "ingested_via": "api",
    }
    rec = StoredRecord(
        record_id=rid,
        deployment_id=deployment_id,
        contract_key=ck,
        payload=payload,
        received_at=now_utc_iso(),
        source_ref=f"api:POST /records/{ck}",
        metadata=meta,
    )
    stored = store.put_record(rec)
    ph = stored.payload_hash or compute_payload_hash(payload)
    append_audit(
        store,
        deployment_id=deployment_id,
        action="record_ingested",
        resource_type="stored_record",
        resource_id=rid,
        metadata={"contract_key": ck, "payload_hash": ph},
    )
    extras = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    return {
        "status": "accepted",
        "record_id": rid,
        "contract_key": ck,
        "payload_hash": ph,
        "warnings": [*API_PILOT_SAFE_WARNINGS, *extras],
    }


@router.get("/records")
def list_records_endpoint(
    deployment_id: Optional[str] = Query(None),
    contract_key: Optional[str] = Query(None),
    store: FileAirOsStore = Depends(get_store),
) -> List[Dict[str, Any]]:
    # FileAirOsStore filters by deployment_id and contract_key when provided.
    rows = store.list_records(
        deployment_id=deployment_id,
        contract_key=contract_key,
    )
    return [_record_to_public_dict(r) for r in sorted(rows, key=lambda r: r.received_at)]
