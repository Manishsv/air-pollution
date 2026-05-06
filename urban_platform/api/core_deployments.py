from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from urban_platform.sdk.deployments import get_deployment_profile, list_deployment_profiles

router = APIRouter(tags=["deployments"])


@router.get("/deployments")
def list_deployments() -> List[Dict[str, Any]]:
    """
    Read-only discovery endpoint for example deployments under deployments/examples/.

    This is metadata only: it does not validate or run deployments, and does not execute builders.
    """
    out: list[dict[str, Any]] = []
    for d in list_deployment_profiles():
        out.append(
            {
                "deployment_id": d.get("deployment_id"),
                "deployment_name": d.get("deployment_name"),
                "path": d.get("path"),
                "enabled_domains": d.get("enabled_domains") or [],
                "provider_count": d.get("provider_count"),
                "application_count": d.get("application_count"),
                "description": d.get("description") or "",
                "available_commands": ["validate", "run"],
            }
        )
    return out


@router.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: str) -> Dict[str, Any]:
    d = get_deployment_profile(deployment_id)
    if d is None:
        raise HTTPException(status_code=404, detail={"message": f"Unknown deployment_id: {str(deployment_id or '').strip()!r}."})

    rel = str(d.get("relative_path") or d.get("path") or "").strip()
    return {
        "deployment_id": d.get("deployment_id"),
        "deployment_name": d.get("deployment_name"),
        "path": d.get("path"),
        "relative_path": rel,
        "enabled_domains": d.get("enabled_domains") or [],
        "provider_count": d.get("provider_count"),
        "application_count": d.get("application_count"),
        "has_provider_registry": d.get("has_provider_registry"),
        "has_application_registry": d.get("has_application_registry"),
        "has_network_adapter_registry": d.get("has_network_adapter_registry"),
        "description": d.get("description") or "",
        "deployment_profile": d.get("deployment_profile") or {},
        "provider_registry": d.get("provider_registry") or {},
        "application_registry": d.get("application_registry") or {},
        "network_adapter_registry": d.get("network_adapter_registry") or {},
        "provider_registrations": d.get("provider_registrations") or [],
        "application_registrations": d.get("application_registrations") or [],
        "network_adapter_registrations": d.get("network_adapter_registrations") or [],
        "warnings": d.get("warnings") or [],
        "errors": d.get("errors") or [],
        "suggested_cli_commands": [
            f"python tools/airos_cli.py deployment validate {rel}" if rel else "python tools/airos_cli.py deployment validate <path>",
            f"python tools/airos_cli.py deployment run {rel}" if rel else "python tools/airos_cli.py deployment run <path>",
        ],
    }

