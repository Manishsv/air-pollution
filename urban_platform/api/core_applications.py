from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from urban_platform.api.adapters.flood_run import (
    FLOOD_PILOT_WARNINGS,
    execute_flood_demo_run,
    missing_flood_inputs,
)
from urban_platform.api.adapters.program_reporting_run import (
    execute_program_reporting_review_run,
    load_program_reporting_submissions,
)
from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.constants import API_PILOT_SAFE_WARNINGS
from urban_platform.api.deps import get_store
from urban_platform.deployments.builder_registry import has_builder
from urban_platform.storage import FileAirOsStore

router = APIRouter(tags=["applications"])

DEFAULT_DEPLOYMENT_ID = "program_reporting_state_demo"
DEFAULT_PROGRAM_ID = "stormwater_resilience_grant_2026"
DEFAULT_REPORTING_PERIOD = "2026_Q1"


@router.post("/applications/{application_id}/runs")
def run_application(
    application_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
    store: FileAirOsStore = Depends(get_store),
) -> Dict[str, Any]:
    aid = str(application_id or "").strip()
    if not has_builder(aid):
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Unknown allowlisted application_id: {aid!r}.",
                "hint": "Use an application_id from the safe builder registry (see GET /manifest for related contracts only).",
            },
        )

    b = dict(body or {})
    deployment_id = str(b.get("deployment_id") or DEFAULT_DEPLOYMENT_ID).strip()
    program_id = str(b.get("program_id") or DEFAULT_PROGRAM_ID).strip()
    reporting_period = str(b.get("reporting_period") or DEFAULT_REPORTING_PERIOD).strip()

    if aid in ("flood_risk_dashboard_payload", "flood_decision_packets", "flood_field_verification_tasks"):
        missing = missing_flood_inputs(store, deployment_id=deployment_id)
        if missing:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "No stored records found for this application run.",
                    "missing_contract_keys": missing,
                },
            )

        run_id = uuid.uuid4().hex[:16]
        append_audit(
            store,
            deployment_id=deployment_id,
            action="application_run_started",
            resource_type="application_run",
            resource_id=run_id,
            metadata={"application_id": aid},
        )

        try:
            rec_processed, outs_generated = execute_flood_demo_run(
                store,
                deployment_id=deployment_id,
                run_id=run_id,
                requested_application_id=aid,
            )
        except ValueError as e:
            raise HTTPException(status_code=500, detail={"message": str(e)}) from e

        append_audit(
            store,
            deployment_id=deployment_id,
            action="application_run_completed",
            resource_type="application_run",
            resource_id=run_id,
            metadata={
                "application_id": aid,
                "records_processed": rec_processed,
                "outputs_generated": outs_generated,
            },
        )

        return {
            "status": "completed",
            "run_id": run_id,
            "application_id": aid,
            "records_processed": rec_processed,
            "outputs_generated": outs_generated,
            "warnings": [*FLOOD_PILOT_WARNINGS, *list(API_PILOT_SAFE_WARNINGS)],
        }

    if aid != "program_reporting_review_packet":
        raise HTTPException(
            status_code=400,
            detail={"message": f"Application '{aid}' has no Core API executor wired yet (fail closed)."},
        )

    if not load_program_reporting_submissions(
        store,
        deployment_id=deployment_id,
        program_id=program_id,
        reporting_period=reporting_period,
    ):
        raise HTTPException(
            status_code=400,
            detail={"message": "No stored records found for this application run."},
        )

    run_id = uuid.uuid4().hex[:16]
    append_audit(
        store,
        deployment_id=deployment_id,
        action="application_run_started",
        resource_type="application_run",
        resource_id=run_id,
        metadata={"application_id": aid, "program_id": program_id, "reporting_period": reporting_period},
    )

    try:
        rec_processed, outs_generated = execute_program_reporting_review_run(
            store,
            deployment_id=deployment_id,
            program_id=program_id,
            reporting_period=reporting_period,
            run_id=run_id,
            application_id=aid,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail={"message": str(e)}) from e

    append_audit(
        store,
        deployment_id=deployment_id,
        action="application_run_completed",
        resource_type="application_run",
        resource_id=run_id,
        metadata={
            "application_id": aid,
            "records_processed": rec_processed,
            "outputs_generated": outs_generated,
        },
    )

    return {
        "status": "completed",
        "run_id": run_id,
        "application_id": aid,
        "records_processed": rec_processed,
        "outputs_generated": outs_generated,
        "warnings": list(API_PILOT_SAFE_WARNINGS),
    }
