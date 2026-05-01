from __future__ import annotations

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def test_flood_demo_artifacts_are_contract_shaped() -> None:
    from review_dashboard.components.flood_panel import build_demo_flood_artifacts

    artifacts = build_demo_flood_artifacts()

    v_dash = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()))
    v_pkt = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve()))
    v_task = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve()))

    v_dash.validate(artifacts.dashboard_payload)
    for p in artifacts.decision_packets:
        v_pkt.validate(p)
    for t in artifacts.field_tasks:
        v_task.validate(t)

