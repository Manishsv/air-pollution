from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd
import yaml

# Allow running as a standalone script from repo root:
# `python tools/deployment_runner/run_deployment.py --deployment ...`
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT_FOR_IMPORTS = _THIS_FILE.parents[2]
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from urban_platform.applications.flood.dashboard_payload import build_flood_risk_dashboard_payload
from urban_platform.applications.flood.decision_packets import build_flood_decision_packets
from urban_platform.applications.flood.field_tasks import build_flood_field_verification_tasks
from urban_platform.connectors.flood.ingest_file import (
    ingest_drainage_asset_feed_json,
    ingest_flood_incident_feed_json,
    ingest_rainfall_observation_feed_json,
)
from urban_platform.processing.flood.features import build_flood_feature_rows
from urban_platform.specifications.conformance import assert_conforms, load_manifest


@dataclass(frozen=True)
class DeploymentRunSummary:
    deployment_id: str
    deployment_dir: str
    output_dir: str
    providers_enabled: list[str]
    applications_enabled: list[str]
    warnings: list[str]
    validated_outputs: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_yaml(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return doc


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


# Allowlisted safe callables for this minimal POC.
PROVIDER_INGEST_ALLOWLIST: dict[str, Callable[[Path], pd.DataFrame]] = {
    "rainfall_fixture": lambda p: ingest_rainfall_observation_feed_json(json_path=p)[0],
    "flood_incident_fixture": lambda p: ingest_flood_incident_feed_json(json_path=p)[0],
    "drainage_asset_fixture": lambda p: ingest_drainage_asset_feed_json(json_path=p)[0],
}

APPLICATION_ALLOWLIST: dict[str, Callable[..., Any]] = {
    "flood_risk_dashboard_payload": build_flood_risk_dashboard_payload,
    "flood_decision_packets": build_flood_decision_packets,
    "flood_field_verification_tasks": build_flood_field_verification_tasks,
}


def run_deployment(*, deployment_dir: Path, repo_root: Path, output_root: Path | None = None) -> DeploymentRunSummary:
    manifest = load_manifest()

    prof = _read_yaml(deployment_dir / "deployment_profile.yaml")
    dep_id = str(prof.get("deployment_id") or "").strip()
    if not dep_id:
        raise ValueError("deployment_profile.yaml missing deployment_id")

    provider_reg = _read_yaml(deployment_dir / "provider_registry.yaml")
    app_reg = _read_yaml(deployment_dir / "application_registry.yaml")

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
        if aid not in APPLICATION_ALLOWLIST:
            raise ValueError(f"application_id not allowlisted for this POC: {aid}")
        applications_enabled.append(aid)

        if aid == "flood_risk_dashboard_payload":
            dashboard_payload = APPLICATION_ALLOWLIST[aid](feature_rows)
        elif aid == "flood_decision_packets":
            decision_packets = APPLICATION_ALLOWLIST[aid](feature_rows)
        elif aid == "flood_field_verification_tasks":
            field_tasks = APPLICATION_ALLOWLIST[aid](decision_packets)

    if dashboard_payload is None:
        raise ValueError("Deployment did not produce flood dashboard payload (missing enabled application).")

    # Validate outputs against consumer contracts.
    assert_conforms(dashboard_payload, schema_name="consumer_flood_risk_dashboard")
    for pkt in decision_packets:
        assert_conforms(pkt, schema_name="consumer_flood_decision_packet")
    for t in field_tasks:
        assert_conforms(t, schema_name="consumer_field_verification_task")

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
    )
    (out_dir / "deployment_run_summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
    args = parser.parse_args()

    repo_root = _find_repo_root(Path(__file__).resolve())
    deployment_dir = (repo_root / str(args.deployment)).resolve()
    if not deployment_dir.exists():
        raise SystemExit(f"Deployment directory not found: {args.deployment}")

    run_deployment(deployment_dir=deployment_dir, repo_root=repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

