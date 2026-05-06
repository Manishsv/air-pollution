from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Query

from urban_platform.api.pagination import paginate_items

from urban_platform.api.core_apps import router as apps_router
from urban_platform.api.core_adapters import router as adapters_router
from urban_platform.api.core_applications import router as applications_router
from urban_platform.api.core_catalogs import router as catalogs_router
from urban_platform.api.core_deployments import router as deployments_router
from urban_platform.api.core_health import router as health_router
from urban_platform.api.core_inventory import router as inventory_router
from urban_platform.api.core_outputs import router as outputs_router
from urban_platform.api.core_records import router as records_router
from urban_platform.api.core_runs import router as runs_router
from urban_platform.api.core_validation_receipts import router as validation_receipts_router
from urban_platform.api.contracts import router as contracts_router
from urban_platform.api.deps import get_store
from urban_platform.specifications.conformance import load_manifest
from urban_platform.storage import FileAirOsStore


def create_app() -> FastAPI:
    app = FastAPI(
        title="AirOS Core API",
        version="0.1.0",
        description="Generic pilot-runtime HTTP surface over FileAirOsStore + allowlisted applications. Not production-secured.",
    )

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {
            "status": "ok",
            "service": "airos-core",
            "mode": "pilot-runtime",
        }

    @app.get("/manifest")
    def manifest_summary() -> Dict[str, Any]:
        m = load_manifest()
        arts = m.get("artifacts") or {}
        return {
            "artifact_count": len(arts),
            "contract_keys": sorted(arts.keys()),
        }

    @app.get("/audit-events")
    def list_audit_events(
        deployment_id: Optional[str] = Query(None),
        action: Optional[str] = Query(None),
        resource_type: Optional[str] = Query(None),
        resource_id: Optional[str] = Query(None),
        paginated: bool = Query(False, description="If true, return pagination envelope instead of raw array."),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        store: FileAirOsStore = Depends(get_store),
    ) -> Any:
        events = store.list_audit_events(deployment_id=deployment_id)
        items = [
            {
                "event_id": e.event_id,
                "deployment_id": e.deployment_id,
                "actor": e.actor,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "occurred_at": e.occurred_at,
                "metadata": e.metadata,
            }
            for e in events
        ]
        if action is not None:
            items = [x for x in items if str(x.get("action") or "") == action]
        if resource_type is not None:
            items = [x for x in items if str(x.get("resource_type") or "") == resource_type]
        if resource_id is not None:
            items = [x for x in items if str(x.get("resource_id") or "") == resource_id]

        if not paginated:
            return items
        try:
            items = sorted(items, key=lambda x: str(x.get("occurred_at") or ""), reverse=True)
        except Exception:
            pass
        return paginate_items(items, limit=limit, offset=offset)

    app.include_router(records_router)
    app.include_router(health_router)
    app.include_router(apps_router)
    app.include_router(adapters_router)
    app.include_router(catalogs_router)
    app.include_router(deployments_router)
    app.include_router(inventory_router)
    app.include_router(applications_router)
    app.include_router(runs_router)
    app.include_router(validation_receipts_router)
    app.include_router(outputs_router)
    app.include_router(contracts_router)

    return app


app = create_app()
