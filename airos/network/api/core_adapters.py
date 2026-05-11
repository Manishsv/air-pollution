from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from airos.os.sdk.adapters import (
    get_provider_adapter_descriptor,
    list_provider_adapter_descriptors,
)

router = APIRouter(tags=["adapters"])


def _build_adapter_summaries(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for d in descriptors:
        cfg = d.get("configuration") if isinstance(d.get("configuration"), dict) else {}
        safety = d.get("safety") if isinstance(d.get("safety"), dict) else {}
        items.append(
            {
                "adapter_id": d.get("adapter_id"),
                "name": d.get("name"),
                "version": d.get("version"),
                "status": d.get("status"),
                "adapter_type": d.get("adapter_type"),
                "source_system_type": d.get("source_system_type"),
                "description": d.get("description"),
                "output_contracts": d.get("output_contracts") or [],
                "configuration": {
                    "required_settings": (cfg.get("required_settings") if isinstance(cfg, dict) else []) or [],
                    "optional_settings": (cfg.get("optional_settings") if isinstance(cfg, dict) else []) or [],
                    "secrets_required": (cfg.get("secrets_required") if isinstance(cfg, dict) else False),
                },
                "safety": {
                    "produces_final_decisions": (safety.get("produces_final_decisions") if isinstance(safety, dict) else False),
                    "records_include_provenance": (safety.get("records_include_provenance") if isinstance(safety, dict) else False),
                    "records_include_quality_flags": (safety.get("records_include_quality_flags") if isinstance(safety, dict) else False),
                },
            }
        )
    return items


@router.get("/adapters")
def list_adapters() -> List[Dict[str, Any]]:
    """
    Read-only provider adapter discovery endpoint.

    Returns summaries derived from governed provider adapter descriptors under
    `specifications/provider_adapters/`.
    """
    desc = list_provider_adapter_descriptors()
    return _build_adapter_summaries(desc)


@router.get("/adapters/{adapter_id}")
def get_adapter(adapter_id: str) -> Dict[str, Any]:
    """
    Read-only provider adapter descriptor endpoint.

    Returns the full descriptor by adapter_id.
    """
    d = get_provider_adapter_descriptor(adapter_id)
    if d is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"Unknown adapter_id: {str(adapter_id or '').strip()!r}."},
        )
    return d

