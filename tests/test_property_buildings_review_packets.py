from __future__ import annotations

import json

import pandas as pd

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def test_property_buildings_review_packets_validate_against_contract() -> None:
    from urban_platform.applications.property_buildings.review_packets import (
        build_property_building_review_packets,
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

    packets = build_property_building_review_packets(
        feats, generated_at="2026-05-01T18:30:00Z", area_id="ward_12"
    )
    assert isinstance(packets, list) and len(packets) >= 1

    v = validator_for_schema_file(
        str(
            (SPEC_ROOT / "consumer_contracts" / "property_building_review_packet.v1.schema.json").resolve()
        )
    )
    for p in packets:
        v.validate(p)
        assert p["domain_id"] == "property_buildings"
        assert p["field_verification_required"] is True
        assert isinstance(p["safety_gates"], list) and len(p["safety_gates"]) >= 1

    json.dumps(packets, default=str)


def test_property_buildings_review_packets_handle_empty_features() -> None:
    from urban_platform.applications.property_buildings.review_packets import (
        build_property_building_review_packets,
    )

    packets = build_property_building_review_packets(
        pd.DataFrame(), generated_at="2026-05-01T18:30:00Z", area_id="ward_12"
    )
    assert len(packets) == 1

