from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from airos.network.api.app_descriptors import build_app_summaries, get_app_descriptor, load_all_app_descriptors

router = APIRouter(tags=["apps"])


@router.get("/apps")
def list_apps() -> List[Dict[str, Any]]:
    """
    Read-only app discovery endpoint.

    Returns summaries derived from governed app descriptors under `specifications/app_descriptors/`.
    """
    desc = load_all_app_descriptors(validate=True)
    return build_app_summaries(desc)


@router.get("/apps/{app_id}")
def get_app(app_id: str) -> Dict[str, Any]:
    """
    Read-only app descriptor endpoint.

    Returns the full descriptor by app_id.
    """
    d = get_app_descriptor(app_id, validate=True)
    if d is None:
        raise HTTPException(status_code=404, detail={"message": f"Unknown app_id: {str(app_id or '').strip()!r}."})
    return d

