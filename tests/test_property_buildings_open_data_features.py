from __future__ import annotations

import pandas as pd


def _fp_row(*, ward_id: str, building_id: str, area_sq: float, source: str = "osm_demo") -> dict:
    return {
        "ward_id": ward_id,
        "building_id": building_id,
        "footprint_area_sq_m": area_sq,
        "source": source,
        "provenance": {"license": "ODbL-1.0"},
    }


def test_open_data_features_current_footprints_only() -> None:
    from urban_platform.processing.property_buildings.open_data_features import (
        STANDARD_BLOCKED_USES,
        build_built_environment_change_features,
    )

    current = pd.DataFrame(
        [
            _fp_row(ward_id="ward_12", building_id="b1", area_sq=100.0),
            _fp_row(ward_id="ward_12", building_id="b2", area_sq=120.0),
        ]
    )
    df, meta = build_built_environment_change_features(
        current,
        previous_building_footprints=None,
        satellite_change_signals=None,
        boundary_units=None,
        generated_at="2026-05-02T12:00:00Z",
        lookback_window_days=180,
    )

    assert len(df) == 1
    row = df.iloc[0]
    assert row["area_id"] == "ward_12"
    assert row["current_building_count"] == 2
    assert row["built_up_area_current_sq_m"] == 220.0
    assert row["previous_building_count"] is None
    assert row["new_building_candidate_count"] is None
    assert row["satellite_change_signal_count"] is None
    assert row["change_detection_readiness"] == "partial"
    assert row["lookback_window_days"] == 180

    flags = list(row["warning_flags"])
    assert "BASELINE_MISSING" in flags
    assert "SATELLITE_CHANGE_SIGNALS_MISSING" in flags
    assert "LOW_GEOMETRY_COVERAGE" not in flags

    assert row["blocked_uses"] == STANDARD_BLOCKED_USES
    assert set(STANDARD_BLOCKED_USES) == {
        "NOT_LEGAL_PROPERTY_RECORD",
        "NOT_PERMIT_VIOLATION_EVIDENCE",
        "FIELD_VERIFICATION_REQUIRED",
        "MUNICIPAL_INTEGRATION_REQUIRED_FOR_TAX_OR_ENFORCEMENT_USE",
    }
    assert isinstance(row["provenance_summary"], dict)
    assert "sources" in row["provenance_summary"]

    assert meta["has_current_footprints"] is True
    assert meta["has_previous_footprints"] is False


def test_open_data_features_with_previous_and_satellite_ready() -> None:
    from urban_platform.processing.property_buildings.open_data_features import (
        build_built_environment_change_features,
    )

    current = pd.DataFrame(
        [
            _fp_row(ward_id="ward_12", building_id="b1", area_sq=100.0),
            _fp_row(ward_id="ward_12", building_id="b2", area_sq=100.0),
            _fp_row(ward_id="ward_12", building_id="b3", area_sq=50.0),
        ]
    )
    previous = pd.DataFrame(
        [
            _fp_row(ward_id="ward_12", building_id="p1", area_sq=100.0),
            _fp_row(ward_id="ward_12", building_id="p2", area_sq=100.0),
        ]
    )
    satellite = pd.DataFrame(
        [
            {"ward_id": "ward_12", "source": "sentinel_demo", "provenance": {"license": "CC-BY-4.0"}},
            {"ward_id": "ward_12", "source": "sentinel_demo", "provenance": {"license": "CC-BY-4.0"}},
        ]
    )
    df, meta = build_built_environment_change_features(
        current,
        previous_building_footprints=previous,
        satellite_change_signals=satellite,
        boundary_units=None,
        generated_at="2026-05-02T12:00:00Z",
    )

    row = df.iloc[0]
    assert row["change_detection_readiness"] == "ready_for_review"
    assert row["previous_building_count"] == 2
    assert row["new_building_candidate_count"] == 1
    assert row["removed_or_changed_building_candidate_count"] == 0
    assert row["satellite_change_signal_count"] == 2
    assert "BASELINE_MISSING" not in row["warning_flags"]
    assert "SATELLITE_CHANGE_SIGNALS_MISSING" not in row["warning_flags"]
    assert meta["has_satellite_signals"] is True


def test_open_data_features_ready_with_previous_only() -> None:
    from urban_platform.processing.property_buildings.open_data_features import build_built_environment_change_features

    current = pd.DataFrame([_fp_row(ward_id="ward_1", building_id="b", area_sq=10.0)])
    previous = pd.DataFrame([_fp_row(ward_id="ward_1", building_id="p", area_sq=10.0)])
    df, _ = build_built_environment_change_features(current, previous_building_footprints=previous)
    assert df.iloc[0]["change_detection_readiness"] == "ready_for_review"
    assert "SATELLITE_CHANGE_SIGNALS_MISSING" in df.iloc[0]["warning_flags"]


def test_open_data_features_ready_with_satellite_only() -> None:
    from urban_platform.processing.property_buildings.open_data_features import build_built_environment_change_features

    current = pd.DataFrame([_fp_row(ward_id="ward_9", building_id="b", area_sq=25.0)])
    satellite = pd.DataFrame(
        [{"ward_id": "ward_9", "source": "landsat_demo", "provenance": {"license": "CC-BY-4.0"}}]
    )
    df, _ = build_built_environment_change_features(current, satellite_change_signals=satellite)
    assert df.iloc[0]["change_detection_readiness"] == "ready_for_review"
    assert "BASELINE_MISSING" in df.iloc[0]["warning_flags"]


def test_open_data_features_low_geometry_coverage_not_ready() -> None:
    from urban_platform.processing.property_buildings.open_data_features import build_built_environment_change_features

    current = pd.DataFrame(
        [
            {"ward_id": "ward_x", "building_id": "a", "source": "osm", "provenance": {"license": "ODbL-1.0"}},
            {"ward_id": "ward_x", "building_id": "b", "source": "osm", "provenance": {"license": "ODbL-1.0"}},
        ]
    )
    df, meta = build_built_environment_change_features(current)
    row = df.iloc[0]
    assert row["change_detection_readiness"] == "not_ready"
    assert "LOW_GEOMETRY_COVERAGE" in row["warning_flags"]
    assert "LOW_GEOMETRY_COVERAGE" in meta["warning_flags_global"]


def test_open_data_features_no_municipal_registry_required() -> None:
    from urban_platform.processing.property_buildings.open_data_features import build_built_environment_change_features

    current = pd.DataFrame([_fp_row(ward_id="ward_5", building_id="x", area_sq=40.0)])
    df, _meta = build_built_environment_change_features(current, generated_at="2026-05-02T12:00:00Z")
    assert "property_registry" not in df.columns
    assert "tax" not in df.columns
    assert len(df) == 1


def test_open_data_features_empty_current_still_returns_row() -> None:
    from urban_platform.processing.property_buildings.open_data_features import build_built_environment_change_features

    df, meta = build_built_environment_change_features(
        pd.DataFrame(),
        generated_at="2026-05-02T12:00:00Z",
    )
    assert len(df) == 1
    assert df.iloc[0]["area_id"] == "__unassigned__"
    assert df.iloc[0]["change_detection_readiness"] == "not_ready"
    assert meta["has_current_footprints"] is False
