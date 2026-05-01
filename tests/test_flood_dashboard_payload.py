from __future__ import annotations

import json

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def _ex(name: str) -> str:
    return str((SPEC_ROOT / "examples" / "flood" / name).resolve())


def test_flood_dashboard_payload_validates_against_contract() -> None:
    from urban_platform.connectors.flood.ingest_file import (
        ingest_drainage_asset_feed_json,
        ingest_flood_incident_feed_json,
        ingest_rainfall_observation_feed_json,
    )
    from urban_platform.processing.flood.features import build_flood_feature_rows
    from urban_platform.applications.flood.dashboard_payload import build_flood_risk_dashboard_payload

    rain, _ = ingest_rainfall_observation_feed_json(json_path=_ex("rainfall_observation.sample.json"))
    inc, _ = ingest_flood_incident_feed_json(json_path=_ex("flood_incident.sample.json"))
    assets, _ = ingest_drainage_asset_feed_json(json_path=_ex("drainage_asset.sample.json"))
    feats, _ = build_flood_feature_rows(rainfall_obs=rain, incident_events=inc, drainage_entities=assets, generated_at="2026-05-01T18:30:00Z")

    payload = build_flood_risk_dashboard_payload(feats, generated_at="2026-05-01T18:30:00Z", city_id="demo_city")

    v = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()))
    v.validate(payload)

    # Should remain non-operational and explicitly warning-heavy.
    assert payload["data_quality_summary"]["synthetic_data_used"] is False
    assert isinstance(payload["active_warnings"], list) and len(payload["active_warnings"]) >= 1

    # Ensure JSON-serializable (dashboard consumers often persist payloads).
    json.dumps(payload, default=str)

