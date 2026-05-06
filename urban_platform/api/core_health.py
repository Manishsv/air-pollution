from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from urban_platform.api.deps import get_store
from urban_platform.deployments import builder_registry
from urban_platform.specifications.conformance import load_manifest
from urban_platform.storage import FileAirOsStore

from urban_platform.sdk.adapters import list_provider_adapter_descriptors
from urban_platform.sdk.apps import list_app_descriptors
from urban_platform.sdk.catalogs import list_reference_catalogs
from urban_platform.sdk.deployments import list_deployment_profiles

router = APIRouter()


@router.get("/health/live")
def health_live() -> Dict[str, str]:
    # Liveness: lightweight process-alive check only.
    return {
        "status": "ok",
        "service": "airos-core",
        "check": "live",
    }


@router.get("/health/ready")
def health_ready(store: FileAirOsStore = Depends(get_store)) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    required_failed = False

    def _ok(name: str, **extra: Any) -> None:
        checks.append({"name": name, "status": "ok", **extra})

    def _fail(name: str, detail: str) -> None:
        nonlocal required_failed
        required_failed = True
        checks.append({"name": name, "status": "fail", "detail": detail})

    # manifest + contracts
    try:
        m = load_manifest()
        _ok("manifest", detail="manifest loaded")
        arts = m.get("artifacts") or {}
        contract_count = len(arts) if isinstance(arts, dict) else 0
        if contract_count > 0:
            _ok("contracts", count=contract_count)
        else:
            _fail("contracts", "no contracts found in manifest")
    except Exception:
        _fail("manifest", "manifest load failed")
        _fail("contracts", "contracts unavailable (manifest not loaded)")

    # governed metadata discovery (read-only)
    try:
        _ok("apps", count=len(list_app_descriptors()))
    except Exception:
        _fail("apps", "app descriptors unavailable")

    try:
        _ok("adapters", count=len(list_provider_adapter_descriptors()))
    except Exception:
        _fail("adapters", "provider adapter descriptors unavailable")

    try:
        _ok("catalogs", count=len(list_reference_catalogs()))
    except Exception:
        _fail("catalogs", "reference catalogs unavailable")

    try:
        _ok("deployments", count=len(list_deployment_profiles()))
    except Exception:
        _fail("deployments", "deployment profiles unavailable")

    # store accessibility (no mutation beyond normal API runtime behavior)
    try:
        store.list_runs(limit=1)
        _ok("store", detail="store accessible")
    except Exception:
        _fail("store", "store not accessible")

    # builder registry listing only (do not resolve callables)
    try:
        _ok("builder_registry", count=len(builder_registry.list_builders()))
    except Exception:
        _fail("builder_registry", "builder registry unavailable")

    status = "not_ready" if required_failed else "ready"
    return {
        "status": status,
        "service": "airos-core",
        "check": "ready",
        "checks": checks,
    }

