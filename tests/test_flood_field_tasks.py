from __future__ import annotations

import json

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def _ex(name: str) -> str:
    return str((SPEC_ROOT / "examples" / "flood" / name).resolve())


def test_flood_field_tasks_validate_against_contract() -> None:
    from urban_platform.connectors.flood.ingest_file import (
        ingest_drainage_asset_feed_json,
        ingest_flood_incident_feed_json,
        ingest_rainfall_observation_feed_json,
    )
    from urban_platform.processing.flood.features import build_flood_feature_rows
    from urban_platform.applications.flood.decision_packets import build_flood_decision_packets
    from urban_platform.applications.flood.field_tasks import build_flood_field_verification_tasks

    rain, _ = ingest_rainfall_observation_feed_json(json_path=_ex("rainfall_observation.sample.json"))
    inc, _ = ingest_flood_incident_feed_json(json_path=_ex("flood_incident.sample.json"))
    assets, _ = ingest_drainage_asset_feed_json(json_path=_ex("drainage_asset.sample.json"))
    feats, _ = build_flood_feature_rows(rainfall_obs=rain, incident_events=inc, drainage_entities=assets, generated_at="2026-05-01T18:30:00Z")
    packets = build_flood_decision_packets(feats, generated_at="2026-05-01T18:30:00Z", city_id="demo_city")

    tasks = build_flood_field_verification_tasks(packets, generated_at="2026-05-01T18:31:00Z", assigned_role="ward_engineer")
    assert isinstance(tasks, list) and len(tasks) >= 1

    v = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve()))
    for t in tasks:
        v.validate(t)
        assert t["domain_id"] == "flood_risk"
        assert t["status"] == "open"
        assert isinstance(t["verification_questions"], list) and len(t["verification_questions"]) >= 1
        assert isinstance(t["evidence_to_collect"], list) and len(t["evidence_to_collect"]) >= 1
        json.dumps(t, default=str)

