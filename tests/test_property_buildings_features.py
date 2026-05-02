from __future__ import annotations

import pandas as pd


def test_build_property_buildings_features_scaffold_runs() -> None:
    from urban_platform.processing.property_buildings.features import (
        build_property_buildings_feature_rows,
    )

    property_registry = pd.DataFrame(
        [
            {
                "property_id": "prop_000123",
                "ward_id": "ward_12",
                "source": "city_property_registry_demo",
                "provenance": {"license": "demo_only"},
            }
        ]
    )

    footprints = pd.DataFrame(
        [
            {
                "building_id": "bldg_778",
                "ward_id": "ward_12",
                "source": "footprints_demo",
                "provenance": {"license": "demo_only"},
            }
        ]
    )

    feats, stats = build_property_buildings_feature_rows(
        property_registry=property_registry,
        building_footprints=footprints,
        building_permits=None,
        land_use=None,
        generated_at="2026-05-01T18:30:00Z",
    )

    assert len(feats) >= 1
    assert "ward_12" in set(feats["area_id"].astype(str).tolist())
    assert "MATCHING_NOT_IMPLEMENTED" in feats.iloc[0]["warning_flags"]
    assert stats.rows_out == len(feats)


def test_build_property_buildings_features_no_inputs_has_warning() -> None:
    from urban_platform.processing.property_buildings.features import (
        build_property_buildings_feature_rows,
    )

    feats, stats = build_property_buildings_feature_rows(
        property_registry=None,
        building_footprints=None,
        building_permits=None,
        land_use=None,
        generated_at="2026-05-01T18:30:00Z",
    )

    assert len(feats) == 1
    assert feats.iloc[0]["area_id"] == "__unassigned__"
    assert "NO_INPUTS_PROVIDED" in feats.iloc[0]["warning_flags"]
    assert stats.rows_out == 1

