from __future__ import annotations

import json

import pandas as pd

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file


def test_property_buildings_field_tasks_validate_against_contract() -> None:
    from urban_platform.applications.property_buildings.field_tasks import (
        build_property_buildings_field_verification_tasks,
    )
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
    tasks = build_property_buildings_field_verification_tasks(
        packets, generated_at="2026-05-01T18:31:00Z", assigned_role="field_inspector"
    )
    assert isinstance(tasks, list) and len(tasks) >= 1

    v = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve())
    )
    for t in tasks:
        v.validate(t)
        assert t["domain_id"] == "property_buildings"
        assert t["status"] == "open"
        assert isinstance(t["verification_questions"], list) and len(t["verification_questions"]) >= 1
        assert isinstance(t["evidence_to_collect"], list) and len(t["evidence_to_collect"]) >= 1
        json.dumps(t, default=str)

