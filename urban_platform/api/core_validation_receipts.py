from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from urban_platform.api.deps import get_store
from urban_platform.storage import FileAirOsStore

router = APIRouter(tags=["validation"])


@router.get("/validation-receipts")
def list_validation_receipts(
    deployment_id: Optional[str] = Query(None),
    contract_key: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    validation_target_type: Optional[str] = Query(None),
    store: FileAirOsStore = Depends(get_store),
) -> List[Dict[str, Any]]:
    rows = store.list_validation_receipts(
        deployment_id=deployment_id,
        contract_key=contract_key,
        status=status,
        validation_target_type=validation_target_type,
    )
    return [
        {
            "receipt_id": r.receipt_id,
            "deployment_id": r.deployment_id,
            "contract_key": r.contract_key,
            "validation_target_type": r.validation_target_type,
            "validation_target_id": r.validation_target_id,
            "status": r.status,
            "validated_at": r.validated_at,
            "payload_hash": r.payload_hash,
            "schema_ref": r.schema_ref,
            "error_count": r.error_count,
            "errors": r.errors,
            "metadata": r.metadata,
        }
        for r in rows
    ]


@router.get("/validation-receipts/{receipt_id}")
def get_validation_receipt(
    receipt_id: str,
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    r = store.get_validation_receipt(receipt_id)
    if r is None:
        raise HTTPException(status_code=404, detail={"message": f"Unknown receipt_id: {receipt_id!r}."})
    return {
        "receipt_id": r.receipt_id,
        "deployment_id": r.deployment_id,
        "contract_key": r.contract_key,
        "validation_target_type": r.validation_target_type,
        "validation_target_id": r.validation_target_id,
        "status": r.status,
        "validated_at": r.validated_at,
        "payload_hash": r.payload_hash,
        "schema_ref": r.schema_ref,
        "error_count": r.error_count,
        "errors": r.errors,
        "metadata": r.metadata,
    }

