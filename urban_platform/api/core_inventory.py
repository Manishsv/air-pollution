from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from urban_platform.api.deps import get_store
from urban_platform.sdk.inventory import get_platform_inventory
from urban_platform.storage import FileAirOsStore

router = APIRouter(tags=["inventory"])


@router.get("/inventory")
def inventory(
    include_runtime: bool = Query(False),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    """
    Platform inventory for developer/operator discovery.

    Read-only: does not validate, run, or execute apps/adapters/deployments.
    """
    inv = get_platform_inventory(include_runtime=False)

    if not include_runtime:
        inv["runtime"] = {"included": False}
        return inv

    inv["runtime"] = {
        "included": True,
        "record_count": len(store.list_records()),
        "run_count": len(store.list_runs()),
        "output_count": len(store.list_outputs()),
        "validation_receipt_count": len(store.list_validation_receipts()),
        "audit_event_count": len(store.list_audit_events()),
        "note": "Counts are from the local FileAirOsStore configured by AIROS_STORE_DIR (pilot runtime).",
    }
    return inv

