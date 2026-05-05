from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd

# Allow running as a standalone script from repo root:
# `python tools/deployment_runner/run_deployment.py --deployment ...`
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT_FOR_IMPORTS = _THIS_FILE.parents[2]
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from urban_platform.applications.program_reporting.review_packets import (
    build_program_reporting_state_summary,
)
from urban_platform.connectors.flood.ingest_file import (
    ingest_drainage_asset_feed_json,
    ingest_flood_incident_feed_json,
    ingest_rainfall_observation_feed_json,
)
from urban_platform.processing.flood.features import build_flood_feature_rows
from urban_platform.deployments.config_loader import load_deployment_config
from urban_platform.deployments.builder_registry import get_builder, has_builder
from urban_platform.specifications.conformance import assert_conforms, load_manifest
from urban_platform.storage import (
    AuditEvent,
    FileAirOsStore,
    StoredOutput,
    StoredRecord,
    compute_payload_hash,
    now_utc_iso,
)


@dataclass(frozen=True)
class DeploymentRunSummary:
    deployment_id: str
    deployment_dir: str
    output_dir: str
    providers_enabled: list[str]
    applications_enabled: list[str]
    warnings: list[str]
    validated_outputs: dict[str, bool]
    submissions_processed: int = 0
    review_packets_generated: int = 0
    cities_ready_for_authorized_review: list[str] | None = None
    cities_needing_clarification: list[str] | None = None
    store_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("store_dir") is None:
            d.pop("store_dir", None)
        return d


def _ensure_exists(repo_root: Path, rel_path: str) -> Path:
    p = (repo_root / rel_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Missing file: {rel_path}")
    return p


def _validate_manifest_refs(manifest: dict[str, Any], *, artifact_keys: list[str]) -> None:
    arts = manifest.get("artifacts") or {}
    for k in artifact_keys:
        if k not in arts:
            raise KeyError(f"Unknown manifest artifact key: {k}")


def _emit_audit(
    store: FileAirOsStore | None,
    *,
    deployment_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if store is None:
        return
    store.append_audit_event(
        AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex}",
            deployment_id=deployment_id,
            actor="deployment_runner",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            occurred_at=now_utc_iso(),
            metadata=metadata or {},
        )
    )


# Allowlisted safe callables for this minimal POC.
PROVIDER_INGEST_ALLOWLIST: dict[str, Callable[[Path], pd.DataFrame]] = {
    "rainfall_fixture": lambda p: ingest_rainfall_observation_feed_json(json_path=p)[0],
    "flood_incident_fixture": lambda p: ingest_flood_incident_feed_json(json_path=p)[0],
    "drainage_asset_fixture": lambda p: ingest_drainage_asset_feed_json(json_path=p)[0],
}

def _resolve_application_callable(application_id: str) -> Callable[..., Any]:
    """Resolve allowlisted application builder callable (fail closed)."""
    reg = get_builder(application_id)
    return reg.resolve_callable()


def _run_program_reporting_state_demo(
    *,
    deployment_dir: Path,
    repo_root: Path,
    output_root: Path | None = None,
    store: FileAirOsStore | None = None,
    store_dir: str | None = None,
) -> DeploymentRunSummary:
    """Allowlisted Phase 1 path: fixture submission → review packet (no providers)."""
    dep_id = "program_reporting_state_demo"
    if store is not None:
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="deployment_run_started",
            resource_type="deployment",
            resource_id=dep_id,
            metadata={"deployment_dir": str(deployment_dir)},
        )

    fixture_paths = [
        "specifications/examples/program_reporting/city_program_submission.sample.json",
        "specifications/examples/program_reporting/city_program_submission_city_b.sample.json",
    ]
    submissions: list[dict[str, Any]] = []
    for rel in fixture_paths:
        p = _ensure_exists(repo_root, rel)
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert_conforms(doc, schema_name="consumer_city_program_submission")
        submissions.append(doc)
        if store is not None:
            rid = str(doc.get("submission_id") or rel.replace("/", "_"))
            store.put_record(
                StoredRecord(
                    record_id=f"rec_{rid}",
                    deployment_id=dep_id,
                    contract_key="consumer_city_program_submission",
                    payload=doc,
                    received_at=now_utc_iso(),
                    source_ref=rel,
                    metadata={"kind": "fixture"},
                )
            )
            _emit_audit(
                store,
                deployment_id=dep_id,
                action="fixture_record_loaded",
                resource_type="stored_record",
                resource_id=rid,
                metadata={"fixture_path": rel, "contract_key": "consumer_city_program_submission"},
            )

    packets: list[dict[str, Any]] = []
    for sub in submissions:
        # Use the allowlisted builder registry (do not resolve from YAML strings).
        pkt_builder = _resolve_application_callable("program_reporting_review_packet")
        pkt = pkt_builder(sub)
        assert_conforms(pkt, schema_name="consumer_fund_release_review_packet")
        packets.append(pkt)
        if store is not None:
            oid = str(pkt.get("packet_id") or "fund_release_review_packet")
            store.put_output(
                StoredOutput(
                    output_id=f"out_{oid}",
                    deployment_id=dep_id,
                    contract_key="consumer_fund_release_review_packet",
                    payload=pkt,
                    generated_at=now_utc_iso(),
                    generated_by="application:program_reporting_review_packet",
                    input_refs=[str(sub.get("submission_id") or "")],
                    metadata={"artifact": "fund_release_review_packet"},
                )
            )
            _emit_audit(
                store,
                deployment_id=dep_id,
                action="output_generated",
                resource_type="stored_output",
                resource_id=f"out_{oid}",
                metadata={"contract_key": "consumer_fund_release_review_packet"},
            )
            _emit_audit(
                store,
                deployment_id=dep_id,
                action="output_validated",
                resource_type="stored_output",
                resource_id=f"out_{oid}",
                metadata={"schema": "consumer_fund_release_review_packet"},
            )

    out_dir = (output_root or (repo_root / "data" / "outputs" / "deployments")).resolve() / dep_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Backward compatibility: keep a single-file output (first packet).
    (out_dir / "fund_release_review_packet.json").write_text(
        json.dumps(packets[0], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "fund_release_review_packets.json").write_text(
        json.dumps(packets, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    state_summary = build_program_reporting_state_summary(
        packets,
        city_submissions=submissions,
        state_node_id="state_urban_department_demo",
        program_id="stormwater_resilience_grant_2026",
        reporting_period="2026_Q1",
    )
    (out_dir / "state_program_summary.json").write_text(
        json.dumps(state_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if store is not None:
        store.put_output(
            StoredOutput(
                output_id="out_state_program_summary",
                deployment_id=dep_id,
                contract_key="internal_program_reporting_state_summary_demo",
                payload=state_summary,
                generated_at=now_utc_iso(),
                generated_by="application:build_program_reporting_state_summary",
                input_refs=[str(p.get("packet_id") or "") for p in packets],
                metadata={"artifact": "state_program_summary"},
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id="out_state_program_summary",
            metadata={"contract_key": "internal_program_reporting_state_summary_demo"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id="out_state_program_summary",
            metadata={"note": "internal demo summary (no formal consumer contract yet)"},
        )

    warnings = [
        "fixture/demo data only",
        "review support only",
        "no automatic fund release",
        "authorized finance process required",
    ]

    cities_ready = list(state_summary.get("cities_ready_for_authorized_review") or [])
    cities_clarify = list(state_summary.get("cities_needing_clarification") or [])

    summary = DeploymentRunSummary(
        deployment_id=dep_id,
        deployment_dir=str(deployment_dir),
        output_dir=str(out_dir),
        providers_enabled=[],
        applications_enabled=["program_reporting_review_packet"],
        warnings=warnings,
        validated_outputs={
            "consumer_fund_release_review_packet": True,
            "state_program_summary": True,
        },
        submissions_processed=len(submissions),
        review_packets_generated=len(packets),
        cities_ready_for_authorized_review=cities_ready,
        cities_needing_clarification=cities_clarify,
        store_dir=store_dir,
    )
    (out_dir / "deployment_run_summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if store is not None:
        summary_payload = dict(summary.to_dict())
        store.put_output(
            StoredOutput(
                output_id=f"out_{dep_id}_deployment_run_summary",
                deployment_id=dep_id,
                contract_key="internal_deployment_run_summary_demo",
                payload=summary_payload,
                generated_at=now_utc_iso(),
                generated_by="tool:deployment_runner",
                input_refs=[str(p.get("packet_id") or "") for p in packets],
                metadata={
                    "artifact": "deployment_run_summary",
                    "payload_sha256": compute_payload_hash(summary_payload),
                },
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_deployment_run_summary",
            metadata={"contract_key": "internal_deployment_run_summary_demo"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_deployment_run_summary",
            metadata={
                "note": "runner summary self-check",
                "payload_sha256": compute_payload_hash(summary_payload),
            },
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="deployment_run_completed",
            resource_type="deployment",
            resource_id=dep_id,
            metadata={"output_dir": str(out_dir), "payload_sha256": compute_payload_hash(summary_payload)},
        )

    return summary


def run_deployment(
    *,
    deployment_dir: Path,
    repo_root: Path,
    output_root: Path | None = None,
    store_dir: Path | None = None,
) -> DeploymentRunSummary:
    manifest = load_manifest()

    cfg = load_deployment_config(deployment_dir)
    dep_id = str(cfg.deployment_id or "").strip()
    if not dep_id:
        raise ValueError("deployment_profile.yaml missing deployment_id")

    store: FileAirOsStore | None = None
    store_dir_str: str | None = None
    if store_dir is not None:
        store_dir_str = str(store_dir.resolve())
        store = FileAirOsStore(store_dir.resolve())

    if dep_id == "program_reporting_state_demo":
        return _run_program_reporting_state_demo(
            deployment_dir=deployment_dir,
            repo_root=repo_root,
            output_root=output_root,
            store=store,
            store_dir=store_dir_str,
        )

    provider_reg = cfg.provider_registry_document
    app_reg = cfg.application_registry_document
    if provider_reg is None or app_reg is None:
        raise ValueError("provider_registry.yaml or application_registry.yaml could not be loaded")

    # Validate manifest references (contracts) where practical.
    provider_artifacts: list[str] = []
    for p in provider_reg.get("providers") or []:
        if isinstance(p, dict) and isinstance(p.get("provider_contract"), str):
            provider_artifacts.append(str(p["provider_contract"]))
    app_artifacts: list[str] = []
    for a in app_reg.get("applications") or []:
        if not isinstance(a, dict):
            continue
        for ck in a.get("consumer_contracts") or []:
            if isinstance(ck, str):
                app_artifacts.append(ck)
    _validate_manifest_refs(manifest, artifact_keys=sorted(set(provider_artifacts + app_artifacts)))

    out_dir = (output_root or (repo_root / "data" / "outputs" / "deployments")).resolve() / dep_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if store is not None:
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="deployment_run_started",
            resource_type="deployment",
            resource_id=dep_id,
            metadata={"deployment_dir": str(deployment_dir)},
        )

    # Ingest fixtures (explicit allowlist; no dynamic imports).
    rainfall_obs = None
    incident_events = None
    drainage_entities = None
    providers_enabled: list[str] = []

    for p in provider_reg.get("providers") or []:
        if not isinstance(p, dict):
            continue
        if p.get("enabled_by_default") is not True:
            continue
        pid = str(p.get("provider_id") or "")
        fixture_path = str(p.get("fixture_path") or "").strip()
        if not fixture_path:
            raise ValueError(f"provider:{pid} missing fixture_path")
        fixture_file = _ensure_exists(repo_root, fixture_path)
        if store is not None:
            try:
                raw_fixture = json.loads(fixture_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw_fixture = None
            if isinstance(raw_fixture, dict):
                rec_payload: dict[str, Any] = raw_fixture
            elif raw_fixture is not None:
                rec_payload = {"fixture_root": raw_fixture}
            else:
                rec_payload = {"parse_error": True, "fixture_path": fixture_path}
            contract_key = str(p.get("provider_contract") or "provider_unknown")
            rec_id = f"rec_{pid}_{Path(fixture_path).name}"
            store.put_record(
                StoredRecord(
                    record_id=rec_id,
                    deployment_id=dep_id,
                    contract_key=contract_key,
                    payload=rec_payload,
                    received_at=now_utc_iso(),
                    source_ref=fixture_path,
                    metadata={"provider_id": pid},
                )
            )
            _emit_audit(
                store,
                deployment_id=dep_id,
                action="fixture_record_loaded",
                resource_type="stored_record",
                resource_id=rec_id,
                metadata={"fixture_path": fixture_path, "contract_key": contract_key},
            )
        if pid not in PROVIDER_INGEST_ALLOWLIST:
            raise ValueError(f"provider_id not allowlisted for this POC: {pid}")
        df = PROVIDER_INGEST_ALLOWLIST[pid](fixture_file)
        providers_enabled.append(pid)
        if pid == "rainfall_fixture":
            rainfall_obs = df
        elif pid == "flood_incident_fixture":
            incident_events = df
        elif pid == "drainage_asset_fixture":
            drainage_entities = df

    # Build features.
    feature_rows, _stats = build_flood_feature_rows(
        rainfall_obs=rainfall_obs,
        incident_events=incident_events,
        drainage_entities=drainage_entities,
    )

    # Build application outputs (explicit allowlist).
    dashboard_payload: dict[str, Any] | None = None
    decision_packets: list[dict[str, Any]] = []
    field_tasks: list[dict[str, Any]] = []
    applications_enabled: list[str] = []

    for a in app_reg.get("applications") or []:
        if not isinstance(a, dict):
            continue
        if a.get("enabled_by_default") is not True:
            continue
        aid = str(a.get("application_id") or "")
        if not has_builder(aid):
            raise ValueError(f"application_id not allowlisted for this POC: {aid}")
        applications_enabled.append(aid)

        if aid == "flood_risk_dashboard_payload":
            dashboard_payload = _resolve_application_callable(aid)(feature_rows)
        elif aid == "flood_decision_packets":
            decision_packets = _resolve_application_callable(aid)(feature_rows)
        elif aid == "flood_field_verification_tasks":
            field_tasks = _resolve_application_callable(aid)(decision_packets)

    if dashboard_payload is None:
        raise ValueError("Deployment did not produce flood dashboard payload (missing enabled application).")

    # Validate outputs against consumer contracts.
    assert_conforms(dashboard_payload, schema_name="consumer_flood_risk_dashboard")
    for pkt in decision_packets:
        assert_conforms(pkt, schema_name="consumer_flood_decision_packet")
    for t in field_tasks:
        assert_conforms(t, schema_name="consumer_field_verification_task")

    if store is not None:
        store.put_output(
            StoredOutput(
                output_id=f"out_{dep_id}_flood_risk_dashboard_payload",
                deployment_id=dep_id,
                contract_key="consumer_flood_risk_dashboard",
                payload=dashboard_payload,
                generated_at=now_utc_iso(),
                generated_by="application:flood_risk_dashboard_payload",
                input_refs=providers_enabled.copy(),
                metadata={"artifact": "flood_risk_dashboard_payload.json"},
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_risk_dashboard_payload",
            metadata={"contract_key": "consumer_flood_risk_dashboard"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_risk_dashboard_payload",
            metadata={"schema": "consumer_flood_risk_dashboard"},
        )
        store.put_output(
            StoredOutput(
                output_id=f"out_{dep_id}_flood_decision_packets",
                deployment_id=dep_id,
                contract_key="consumer_flood_decision_packet",
                payload={"flood_decision_packets": decision_packets},
                generated_at=now_utc_iso(),
                generated_by="application:flood_decision_packets",
                input_refs=providers_enabled.copy(),
                metadata={"artifact": "flood_decision_packets.json", "packet_count": len(decision_packets)},
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_decision_packets",
            metadata={"contract_key": "consumer_flood_decision_packet"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_decision_packets",
            metadata={"schema": "consumer_flood_decision_packet"},
        )
        store.put_output(
            StoredOutput(
                output_id=f"out_{dep_id}_flood_field_verification_tasks",
                deployment_id=dep_id,
                contract_key="consumer_field_verification_task",
                payload={"flood_field_verification_tasks": field_tasks},
                generated_at=now_utc_iso(),
                generated_by="application:flood_field_verification_tasks",
                input_refs=[str(i) for i in range(len(decision_packets))],
                metadata={"artifact": "flood_field_verification_tasks.json", "task_count": len(field_tasks)},
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_field_verification_tasks",
            metadata={"contract_key": "consumer_field_verification_task"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_flood_field_verification_tasks",
            metadata={"schema": "consumer_field_verification_task"},
        )

    # Write outputs.
    (out_dir / "flood_risk_dashboard_payload.json").write_text(
        json.dumps(dashboard_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "flood_decision_packets.json").write_text(
        json.dumps(decision_packets, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "flood_field_verification_tasks.json").write_text(
        json.dumps(field_tasks, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    warnings = [
        "fixture/demo data only",
        "decision support only",
        "field verification required",
        "no emergency orders",
    ]

    summary = DeploymentRunSummary(
        deployment_id=dep_id,
        deployment_dir=str(deployment_dir),
        output_dir=str(out_dir),
        providers_enabled=providers_enabled,
        applications_enabled=applications_enabled,
        warnings=warnings,
        validated_outputs={
            "consumer_flood_risk_dashboard": True,
            "consumer_flood_decision_packet": True,
            "consumer_field_verification_task": True,
        },
        store_dir=store_dir_str,
    )
    (out_dir / "deployment_run_summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if store is not None:
        summary_payload = dict(summary.to_dict())
        store.put_output(
            StoredOutput(
                output_id=f"out_{dep_id}_deployment_run_summary",
                deployment_id=dep_id,
                contract_key="internal_deployment_run_summary_demo",
                payload=summary_payload,
                generated_at=now_utc_iso(),
                generated_by="tool:deployment_runner",
                input_refs=applications_enabled.copy(),
                metadata={
                    "artifact": "deployment_run_summary.json",
                    "payload_sha256": compute_payload_hash(summary_payload),
                },
            )
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_generated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_deployment_run_summary",
            metadata={"contract_key": "internal_deployment_run_summary_demo"},
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="output_validated",
            resource_type="stored_output",
            resource_id=f"out_{dep_id}_deployment_run_summary",
            metadata={
                "note": "runner summary self-check",
                "payload_sha256": compute_payload_hash(summary_payload),
            },
        )
        _emit_audit(
            store,
            deployment_id=dep_id,
            action="deployment_run_completed",
            resource_type="deployment",
            resource_id=dep_id,
            metadata={"output_dir": str(out_dir), "payload_sha256": compute_payload_hash(summary_payload)},
        )

    return summary


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / "specifications").exists() and (cur / "README.md").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal registry-driven deployment runner (POC).")
    parser.add_argument(
        "--deployment",
        required=True,
        type=str,
        help="Deployment directory (e.g. deployments/examples/flood_local_demo).",
    )
    parser.add_argument(
        "--store-dir",
        default=None,
        type=str,
        metavar="PATH",
        help="Optional FileAirOsStore root (records.jsonl, outputs.jsonl, audit_events.jsonl). Additive; data/outputs unchanged.",
    )
    args = parser.parse_args()

    repo_root = _find_repo_root(Path(__file__).resolve())
    deployment_dir = (repo_root / str(args.deployment)).resolve()
    if not deployment_dir.exists():
        raise SystemExit(f"Deployment directory not found: {args.deployment}")

    sdir = Path(args.store_dir).resolve() if args.store_dir else None
    run_deployment(deployment_dir=deployment_dir, repo_root=repo_root, store_dir=sdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

