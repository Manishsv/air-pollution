from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from urban_platform.api.deps import get_store
from urban_platform.storage import FileAirOsStore, StoredOutput

router = APIRouter(tags=["outputs"])


def _stored_output_public(o: StoredOutput) -> Dict[str, Any]:
    d = asdict(o)
    return d


def _metadata_matches(
    md: Dict[str, Any],
    *,
    application_id: Optional[str],
    program_id: Optional[str],
    reporting_period: Optional[str],
) -> bool:
    if application_id is not None and str(md.get("application_id") or "") != application_id:
        return False
    if program_id is not None and str(md.get("program_id") or "") != program_id:
        return False
    if reporting_period is not None and str(md.get("reporting_period") or "") != reporting_period:
        return False
    return True


@router.get("/outputs")
def list_outputs(
    deployment_id: Optional[str] = Query(None),
    contract_key: Optional[str] = Query(None),
    application_id: Optional[str] = Query(None),
    program_id: Optional[str] = Query(None),
    reporting_period: Optional[str] = Query(None),
    store: FileAirOsStore = Depends(get_store),
) -> List[Dict[str, Any]]:
    ck = str(contract_key) if contract_key is not None else None
    cand = store.list_outputs(deployment_id=deployment_id, contract_key=ck)

    out_list: List[StoredOutput] = []
    seen: set[str] = set()
    for o in sorted(cand, key=lambda x: x.generated_at):
        if o.output_id in seen:
            continue
        seen.add(o.output_id)
        if deployment_id is not None and o.deployment_id != deployment_id:
            continue
        if contract_key is not None and o.contract_key != contract_key:
            continue
        if not _metadata_matches(o.metadata or {}, application_id=application_id, program_id=program_id, reporting_period=reporting_period):
            continue
        out_list.append(o)
    return [_stored_output_public(o) for o in out_list]


@router.get("/outputs/{output_id}")
def get_output_detail(
    output_id: str,
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    o = store.get_output(str(output_id))
    if o is None:
        raise HTTPException(status_code=404, detail={"message": f"No output found for output_id={output_id!r}."})
    return _stored_output_public(o)
