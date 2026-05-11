from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from airos.os.specifications.conformance import SPEC_ROOT, load_manifest

router = APIRouter(tags=["contracts"])


def _safe_schema_relpath(rel: str) -> str:
    """
    Return a repo-relative schema path string for API responses.

    - must live under specifications/
    - must not expose absolute paths
    """
    p = (SPEC_ROOT / rel).resolve()
    try:
        p.relative_to(SPEC_ROOT)
    except ValueError as e:  # outside specifications/
        raise HTTPException(status_code=400, detail={"message": "Schema path resolves outside specifications/."}) from e
    return str(Path("specifications") / rel)


def _load_schema_json(rel: str) -> Dict[str, Any]:
    p = (SPEC_ROOT / rel).resolve()
    try:
        p.relative_to(SPEC_ROOT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"message": "Schema path resolves outside specifications/."}) from e
    if not p.is_file():
        raise HTTPException(status_code=404, detail={"message": f"Schema file not found for schema_path={rel!r}."})

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": "Artifact is not JSON schema (non-JSON content).", "schema_path": rel},
        ) from e
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail={"message": "Schema JSON must be an object."})
    return obj


@router.get("/contracts/{contract_key}")
def get_contract(contract_key: str) -> Dict[str, Any]:
    ck = str(contract_key or "").strip()
    m = load_manifest()
    arts = m.get("artifacts") or {}
    if ck not in arts:
        raise HTTPException(status_code=404, detail={"message": f"Unknown contract_key {ck!r} (not in manifest)."})
    meta = arts.get(ck) or {}
    rel = meta.get("schema_path")
    if not isinstance(rel, str) or not rel.strip():
        raise HTTPException(status_code=400, detail={"message": f"Artifact {ck!r} is not schema-backed (missing schema_path)."})
    contract_type = meta.get("contract_type")
    if contract_type == "openapi":
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Artifact {ck!r} is an OpenAPI stub, not a JSON schema contract.",
                "contract_type": "openapi",
                "schema_path": _safe_schema_relpath(rel),
            },
        )

    schema = _load_schema_json(rel)
    return {
        "contract_key": ck,
        "artifact_type": contract_type,
        "schema_path": _safe_schema_relpath(rel),
        "schema": schema,
    }


@router.get("/contracts")
def list_contracts() -> Dict[str, Any]:
    """Lightweight index of contract keys grouped by contract_type."""
    m = load_manifest()
    arts = m.get("artifacts") or {}
    groups: Dict[str, List[str]] = {}
    for k, meta in arts.items():
        if not isinstance(k, str) or not isinstance(meta, dict):
            continue
        ct = str(meta.get("contract_type") or "unknown")
        groups.setdefault(ct, []).append(k)
    for ct in list(groups.keys()):
        groups[ct] = sorted(groups[ct])
    return {"contract_types": sorted(groups.keys()), "contracts": groups}

