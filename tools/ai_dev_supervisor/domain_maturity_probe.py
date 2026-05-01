from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DomainMaturityResult:
    domain: str
    completed_items: list[str]
    missing_items: list[str]
    maturity_stage: str
    recommended_next_task: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _required_paths_for_domain(domain: str) -> Optional[list[str]]:
    if domain == "flood_risk":
        return [
            # domain spec
            "specifications/domain_specs/flood_risk.v1.yaml",
            # provider contracts
            "specifications/provider_contracts/rainfall_observation_feed.v1.schema.json",
            "specifications/provider_contracts/flood_incident_feed.v1.schema.json",
            "specifications/provider_contracts/drainage_asset_feed.v1.schema.json",
            # consumer contracts
            "specifications/consumer_contracts/flood_risk_dashboard.v1.schema.json",
            "specifications/consumer_contracts/flood_decision_packet.v1.schema.json",
            "specifications/consumer_contracts/field_verification_task.v1.schema.json",
            # examples
            "specifications/examples/flood/rainfall_observation.sample.json",
            "specifications/examples/flood/flood_incident.sample.json",
            "specifications/examples/flood/drainage_asset.sample.json",
            "specifications/examples/flood/flood_risk_dashboard.sample.json",
            "specifications/examples/flood/flood_decision_packet.sample.json",
            # ingestion
            "urban_platform/connectors/flood/ingest_file.py",
            # features
            "urban_platform/processing/flood/features.py",
            # dashboard payload
            "urban_platform/applications/flood/dashboard_payload.py",
            # decision packets
            "urban_platform/applications/flood/decision_packets.py",
            # field tasks
            "urban_platform/applications/flood/field_tasks.py",
            # dashboard UI
            "review_dashboard/components/flood_panel.py",
            # tests
            "tests/test_flood_ingestion.py",
            "tests/test_flood_features.py",
            "tests/test_flood_dashboard_payload.py",
            "tests/test_flood_decision_packets.py",
            "tests/test_flood_field_tasks.py",
            "tests/test_flood_dashboard_panel_demo.py",
        ]
    return None


def _stage_for_missing(missing: list[str]) -> str:
    if not missing:
        return "complete_read_only_vertical_slice"

    has_specs_missing = any(
        p.startswith("specifications/domain_specs/") for p in missing
    )
    has_contracts_missing = any(
        p.startswith("specifications/provider_contracts/")
        or p.startswith("specifications/consumer_contracts/")
        for p in missing
    )
    has_examples_missing = any(p.startswith("specifications/examples/") for p in missing)

    if has_specs_missing or has_contracts_missing:
        return "incomplete_specs"
    if has_examples_missing:
        return "specs_present_missing_examples"

    has_impl_missing = any(
        p.startswith("urban_platform/") or p.startswith("review_dashboard/")
        for p in missing
    )
    if has_impl_missing:
        return "specs_ready_missing_implementation"

    has_tests_missing = any(p.startswith("tests/") for p in missing)
    if has_tests_missing:
        return "implementation_ready_missing_tests"

    return "partial"


def _recommended_next_task(domain: str, missing: list[str], stage: str) -> str:
    if domain == "flood_risk" and stage == "complete_read_only_vertical_slice":
        return "Add dashboard smoke testing and/or persist flood generated artifacts from fixtures or configured inputs."

    if missing:
        # keep it simple: prioritize the first missing item
        return f"Add missing maturity item: `{missing[0]}`"

    return "Add domain improvements via specs-first sequence, then run conformance."


def probe_domain_maturity(repo_root: Path, domain: str) -> DomainMaturityResult:
    errors: list[str] = []

    required = _required_paths_for_domain(domain)
    if required is None:
        return DomainMaturityResult(
            domain=domain,
            completed_items=[],
            missing_items=[],
            maturity_stage="unknown_domain",
            recommended_next_task="Add a domain maturity checklist for this domain.",
            errors=[f"Unknown domain `{domain}` (no maturity checklist configured)."],
        )

    completed: list[str] = []
    missing: list[str] = []
    for rel in required:
        if (repo_root / rel).exists():
            completed.append(rel)
        else:
            missing.append(rel)

    stage = _stage_for_missing(missing)
    rec = _recommended_next_task(domain, missing, stage)
    return DomainMaturityResult(
        domain=domain,
        completed_items=completed,
        missing_items=missing,
        maturity_stage=stage,
        recommended_next_task=rec,
        errors=errors,
    )

