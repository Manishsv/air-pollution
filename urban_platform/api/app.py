from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Query

from urban_platform.api.program_reporting import get_store, router as program_reporting_router
from urban_platform.storage import FileAirOsStore


def create_app() -> FastAPI:
    app = FastAPI(
        title="AirOS Core API",
        version="0.1.0",
        description="Pilot-runtime HTTP surface (Program Reporting slice). Not production-secured.",
    )

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {
            "status": "ok",
            "service": "airos-core",
            "mode": "pilot-runtime",
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

    app.include_router(program_reporting_router)
    return app


app = create_app()
