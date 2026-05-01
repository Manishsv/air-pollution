from __future__ import annotations

from urban_platform.common.provenance_summary import build_provenance_summary


def test_build_provenance_summary_basic_fields_and_low_confidence():
    metrics = {"provenance_low_confidence_ratio": 12.5}
    audit = {
        "percent_cells_interpolated": 80.0,
        "percent_cells_synthetic": 0.0,
        "number_of_real_aq_stations": 7,
        "avg_nearest_station_distance_km": 2.25,
        "recommendation_allowed": True,
        "recommendation_block_reason": "",
    }
    s = build_provenance_summary(metrics, audit)
    assert s["percent_cells_interpolated"] == 80.0
    assert s["percent_cells_synthetic"] == 0.0
    assert s["percent_low_confidence"] == 12.5
    assert s["number_of_real_aq_stations"] == 7
    assert float(s["avg_nearest_station_distance_km"]) == 2.25
    assert s["recommendation_allowed"] is True

