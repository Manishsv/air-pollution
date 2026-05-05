from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from urban_platform.api.adapters.flood_run import (
    FLOOD_PILOT_WARNINGS,
    execute_flood_demo_run,
    missing_flood_inputs,
    required_flood_input_contracts,
)
from urban_platform.api.adapters.program_reporting_run import (
    execute_program_reporting_review_run,
    load_program_reporting_submissions,
)
from urban_platform.api.audit_helpers import append_audit
from urban_platform.api.constants import API_PILOT_SAFE_WARNINGS
from urban_platform.api.deps import get_store
from urban_platform.deployments.builder_registry import has_builder
from urban_platform.storage import FileAirOsStore, StoredRun, now_utc_iso

router = APIRouter(tags=["applications"])

DEFAULT_DEPLOYMENT_ID = "program_reporting_state_demo"
DEFAULT_PROGRAM_ID = "stormwater_resilience_grant_2026"
DEFAULT_REPORTING_PERIOD = "2026_Q1"


def _safe_error_message(e: Exception) -> str:
    # Intentionally avoid stack traces in the API surface.
    # ValueErrors raised by adapters are treated as safe summaries.
    if isinstance(e, ValueError):
        return str(e)
    return "Unexpected error during application run."


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
        started_at = now_utc_iso()

        input_refs: list[str] = []
        for ck in required_flood_input_contracts():
            rows = store.list_records(deployment_id=deployment_id, contract_key=ck)
            if not rows:
                continue
            latest = sorted(rows, key=lambda r: r.received_at)[-1]
            input_refs.append(latest.record_id)

        store.put_run(
            StoredRun(
                run_id=run_id,
                deployment_id=deployment_id,
                application_id=aid,
                status="running",
                started_at=started_at,
                completed_at=None,
                input_refs=input_refs,
                output_refs=[],
                records_processed=0,
                outputs_generated=0,
                warnings=[*FLOOD_PILOT_WARNINGS, *list(API_PILOT_SAFE_WARNINGS)],
                metadata={},
            )
        )

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
        except Exception as e:  # noqa: BLE001
            completed_at = now_utc_iso()
            store.put_run(
                StoredRun(
                    run_id=run_id,
                    deployment_id=deployment_id,
                    application_id=aid,
                    status="failed",
                    started_at=started_at,
                    completed_at=completed_at,
                    input_refs=input_refs,
                    output_refs=[],
                    records_processed=0,
                    outputs_generated=0,
                    warnings=[*FLOOD_PILOT_WARNINGS, *list(API_PILOT_SAFE_WARNINGS)],
                    metadata={"error": _safe_error_message(e)},
                )
            )
            raise HTTPException(
                status_code=500,
                detail={"message": "Application run failed.", "run_id": run_id},
            ) from e

        completed_at = now_utc_iso()
        outs = [
            o.output_id
            for o in store.list_outputs(deployment_id=deployment_id)
            if str((o.metadata or {}).get("run_id") or "") == run_id
        ]
        store.put_run(
            StoredRun(
                run_id=run_id,
                deployment_id=deployment_id,
                application_id=aid,
                status="completed",
                started_at=started_at,
                completed_at=completed_at,
                input_refs=input_refs,
                output_refs=outs,
                records_processed=rec_processed,
                outputs_generated=outs_generated,
                warnings=[*FLOOD_PILOT_WARNINGS, *list(API_PILOT_SAFE_WARNINGS)],
                metadata={},
            )
        )

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
    started_at = now_utc_iso()

    submissions = load_program_reporting_submissions(
        store,
        deployment_id=deployment_id,
        program_id=program_id,
        reporting_period=reporting_period,
    )
    input_refs = [r.record_id for r in submissions]
    store.put_run(
        StoredRun(
            run_id=run_id,
            deployment_id=deployment_id,
            application_id=aid,
            status="running",
            started_at=started_at,
            completed_at=None,
            input_refs=input_refs,
            output_refs=[],
            records_processed=0,
            outputs_generated=0,
            warnings=list(API_PILOT_SAFE_WARNINGS),
            metadata={"program_id": program_id, "reporting_period": reporting_period},
        )
    )

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
    except Exception as e:  # noqa: BLE001
        completed_at = now_utc_iso()
        store.put_run(
            StoredRun(
                run_id=run_id,
                deployment_id=deployment_id,
                application_id=aid,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                input_refs=input_refs,
                output_refs=[],
                records_processed=0,
                outputs_generated=0,
                warnings=list(API_PILOT_SAFE_WARNINGS),
                metadata={"program_id": program_id, "reporting_period": reporting_period, "error": _safe_error_message(e)},
            )
        )
        raise HTTPException(
            status_code=500,
            detail={"message": "Application run failed.", "run_id": run_id},
        ) from e

    completed_at = now_utc_iso()
    outs = [
        o.output_id
        for o in store.list_outputs(deployment_id=deployment_id)
        if str((o.metadata or {}).get("run_id") or "") == run_id
    ]
    store.put_run(
        StoredRun(
            run_id=run_id,
            deployment_id=deployment_id,
            application_id=aid,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            input_refs=input_refs,
            output_refs=outs,
            records_processed=rec_processed,
            outputs_generated=outs_generated,
            warnings=list(API_PILOT_SAFE_WARNINGS),
            metadata={"program_id": program_id, "reporting_period": reporting_period},
        )
    )

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
