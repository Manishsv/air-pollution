from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from urban_platform.sdk.catalogs import get_reference_catalog, list_reference_catalogs

router = APIRouter(tags=["catalogs"])


def _summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in items:
        entries = c.get("entries") or []
        out.append(
            {
                "catalog_id": c.get("catalog_id"),
                "version": c.get("version"),
                "catalog_type": c.get("catalog_type"),
                "publisher_node_id": c.get("publisher_node_id"),
                "status": c.get("status"),
                "valid_from": c.get("valid_from"),
                "expires_at": c.get("expires_at"),
                "entries_count": len(entries) if isinstance(entries, list) else 0,
            }
        )
    return out


@router.get("/catalogs")
def list_catalogs() -> List[Dict[str, Any]]:
    """
    Read-only discovery endpoint for local reference catalog examples.

    This is local fixture discovery only; no pull/cache/TTL, signatures, or federation.
    """
    return _summaries(list_reference_catalogs())


@router.get("/catalogs/{catalog_id}")
def get_catalog(catalog_id: str) -> Dict[str, Any]:
    c = get_reference_catalog(catalog_id)
    if c is None:
        raise HTTPException(status_code=404, detail={"message": f"Unknown catalog_id: {str(catalog_id or '').strip()!r}."})
    return c

