from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Open-data-first maturity path for `property_buildings` (see docs/USE_CASE_ROADMAP.md).
PROPERTY_BUILDINGS_OPEN_DATA_SEQUENCE: tuple[str, ...] = (
    "1. Domain spec: property_buildings.v1.yaml (phasing, open_data_inputs, authorized_municipal_inputs, blocked_uses, required_human_review).",
    "2. Open-data provider contracts + examples: building_footprint, ward_boundary, satellite_change_signal, land_use; road_network_feed for context.",
    "3. Open-data feature scaffolding: urban_platform/processing/property_buildings/open_data_features.py (+ tests).",
    "4. Open-data-aligned dashboard payload: consumer property_building_dashboard + applications/property_buildings/dashboard_payload.py.",
    "5. Review packet: consumer property_building_review_packet + review_packets.py.",
    "6. Field verification task: field_verification_task contract + field_tasks.py.",
    "7. Read-only dashboard: review_dashboard/components/property_buildings_panel.py (+ panel demo test).",
    "8. Later-stage municipal integration contracts: property_registry_feed, building_permit_feed (specs only until authorized; not Phase 1 defaults).",
)


@dataclass(frozen=True)
class DomainMaturityResult:
    domain: str
    completed_items: list[str]
    missing_items: list[str]
    maturity_stage: str
    recommended_next_task: str
    errors: list[str]
    open_data_first_sequence: tuple[str, ...] = ()

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
    if domain == "property_buildings":
        return [
            # domain spec
            "specifications/domain_specs/property_buildings.v1.yaml",
            # provider contracts (open-data MVP path + optional partner feeds)
            "specifications/provider_contracts/building_footprint_feed.v1.schema.json",
            "specifications/provider_contracts/ward_boundary_feed.v1.schema.json",
            "specifications/provider_contracts/satellite_change_signal_feed.v1.schema.json",
            "specifications/provider_contracts/land_use_feed.v1.schema.json",
            "specifications/provider_contracts/property_registry_feed.v1.schema.json",
            "specifications/provider_contracts/building_permit_feed.v1.schema.json",
            # consumer contracts
            "specifications/consumer_contracts/property_building_dashboard.v1.schema.json",
            "specifications/consumer_contracts/property_building_review_packet.v1.schema.json",
            "specifications/consumer_contracts/field_verification_task.v1.schema.json",
            # examples
            "specifications/examples/property_buildings/building_footprint.sample.json",
            "specifications/examples/property_buildings/ward_boundary.sample.json",
            "specifications/examples/property_buildings/satellite_change_signal.sample.json",
            "specifications/examples/property_buildings/land_use.sample.json",
            "specifications/examples/property_buildings/property_registry.sample.json",
            "specifications/examples/property_buildings/building_permit.sample.json",
            "specifications/examples/property_buildings/property_building_dashboard.sample.json",
            "specifications/examples/property_buildings/property_building_review_packet.sample.json",
            # features
            "urban_platform/processing/property_buildings/features.py",
            "urban_platform/processing/property_buildings/open_data_features.py",
            # dashboard payload
            "urban_platform/applications/property_buildings/dashboard_payload.py",
            # review packets
            "urban_platform/applications/property_buildings/review_packets.py",
            # field tasks
            "urban_platform/applications/property_buildings/field_tasks.py",
            # dashboard UI (read-only tab) - not implemented yet
            "review_dashboard/components/property_buildings_panel.py",
            # tests
            "tests/test_property_buildings_features.py",
            "tests/test_property_buildings_open_data_features.py",
            "tests/test_property_buildings_dashboard_payload.py",
            "tests/test_property_buildings_review_packets.py",
            "tests/test_property_buildings_field_tasks.py",
            "tests/test_property_buildings_dashboard_panel_demo.py",
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
    if domain == "property_buildings":
        if stage == "complete_read_only_vertical_slice":
            return (
                "Follow docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md: bounded open-data ingest or payload alignment next; "
                "keep registry/permit contracts later-stage only."
            )
        if any(p.startswith("review_dashboard/components/property_buildings_panel.py") for p in missing) or any(
            p.endswith("test_property_buildings_dashboard_panel_demo.py") for p in missing
        ):
            return "Add a read-only `property_buildings` dashboard panel and a panel demo test (no connectors, no tax/enforcement claims)."

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
            open_data_first_sequence=(),
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
    seq: tuple[str, ...] = PROPERTY_BUILDINGS_OPEN_DATA_SEQUENCE if domain == "property_buildings" else ()
    return DomainMaturityResult(
        domain=domain,
        completed_items=completed,
        missing_items=missing,
        maturity_stage=stage,
        recommended_next_task=rec,
        errors=errors,
        open_data_first_sequence=seq,
    )

