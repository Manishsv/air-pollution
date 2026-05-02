from __future__ import annotations

import json

import pandas as pd

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def test_property_buildings_dashboard_payload_validates_against_contract() -> None:
    from urban_platform.applications.property_buildings.dashboard_payload import (
        build_property_building_dashboard_payload,
    )
    from urban_platform.processing.property_buildings.features import (
        build_property_buildings_feature_rows,
    )

    feats, _ = build_property_buildings_feature_rows(
        property_registry=pd.DataFrame(
            [
                {
                    "ward_id": "ward_12",
                    "source": "city_property_registry_demo",
                    "provenance": {"license": "demo_only"},
                }
            ]
        ),
        building_footprints=pd.DataFrame(
            [
                {
                    "ward_id": "ward_12",
                    "source": "footprints_demo",
                    "provenance": {"license": "demo_only"},
                }
            ]
        ),
        building_permits=None,
        land_use=None,
        generated_at="2026-05-01T18:30:00Z",
    )

    payload = build_property_building_dashboard_payload(
        feats, generated_at="2026-05-01T18:30:00Z", area_id="ward_12"
    )

    v = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "property_building_dashboard.v1.schema.json").resolve())
    )
    v.validate(payload)

    # Should remain verification-first / non-operational.
    assert isinstance(payload["active_warnings"], list) and len(payload["active_warnings"]) >= 1
    assert payload["data_quality_summary"]["synthetic_data_used"] is True
    assert payload["mismatch_summary"]["total_candidates"] == 0

    json.dumps(payload, default=str)


def test_property_buildings_dashboard_payload_handles_empty_features() -> None:
    from urban_platform.applications.property_buildings.dashboard_payload import (
        build_property_building_dashboard_payload,
    )

    payload = build_property_building_dashboard_payload(
        pd.DataFrame(), generated_at="2026-05-01T18:30:00Z", city_id="demo_city"
    )
    assert payload["city_id"] == "demo_city"
    assert "map_layers" in payload and len(payload["map_layers"]) >= 1

