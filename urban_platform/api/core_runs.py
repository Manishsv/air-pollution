from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from urban_platform.api.deps import get_store
from urban_platform.api.pagination import paginate_items
from urban_platform.storage import FileAirOsStore

router = APIRouter(tags=["runs"])


@router.get("/runs")
def list_runs(
    deployment_id: Optional[str] = Query(None),
    application_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    paginated: bool = Query(False, description="If true, return pagination envelope instead of raw array."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store: FileAirOsStore = Depends(get_store),
) -> Any:
    runs = store.list_runs(deployment_id=deployment_id, application_id=application_id, status=status)
    items: List[Dict[str, Any]] = [
        {
            "run_id": r.run_id,
            "deployment_id": r.deployment_id,
            "application_id": r.application_id,
            "status": r.status,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "records_processed": r.records_processed,
            "outputs_generated": r.outputs_generated,
            "input_refs": r.input_refs,
            "output_refs": r.output_refs,
            "warnings": r.warnings,
            "metadata": r.metadata,
        }
        for r in runs
    ]
    if not paginated:
        return items
    # newest-first by started_at when available (fallback: input order)
    try:
        items = sorted(items, key=lambda x: str(x.get("started_at") or ""), reverse=True)
    except Exception:
        pass
    return paginate_items(items, limit=limit, offset=offset)


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    r = store.get_run(run_id)
    if r is None:
        raise HTTPException(status_code=404, detail={"message": f"Unknown run_id: {run_id!r}."})
    return {
        "run_id": r.run_id,
        "deployment_id": r.deployment_id,
        "application_id": r.application_id,
        "status": r.status,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "records_processed": r.records_processed,
        "outputs_generated": r.outputs_generated,
        "input_refs": r.input_refs,
        "output_refs": r.output_refs,
        "warnings": r.warnings,
        "metadata": r.metadata,
    }

