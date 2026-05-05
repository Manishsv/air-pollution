from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Query

from urban_platform.api.core_applications import router as applications_router
from urban_platform.api.core_outputs import router as outputs_router
from urban_platform.api.core_records import router as records_router
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
        store: FileAirOsStore = Depends(get_store),
    ) -> List[Dict[str, Any]]:
        events = store.list_audit_events(deployment_id=deployment_id)
        return [
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

    app.include_router(records_router)
    app.include_router(applications_router)
    app.include_router(outputs_router)
    app.include_router(contracts_router)

    return app


app = create_app()
