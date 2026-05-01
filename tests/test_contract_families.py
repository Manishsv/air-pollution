from __future__ import annotations

from datetime import datetime, timezone

from urban_platform.specifications.conformance import assert_conforms, load_manifest


def test_provider_contract_validates_minimal_aq_feed():
    payload = {
        "provider_id": "demo_provider",
        "source_name": "Example AQ Feed",
        "source_type": "air_quality",
        "license": "CC-BY-4.0",
        "source_metadata": {"url": "https://example.com"},
        "records": [
            {
                "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                "observed_property": "pm25",
                "value": 42.0,
                "unit": "µg/m3",
                "quality_flag": "ok",
                "provenance": {"note": "demo"},
                "latitude": 12.9,
                "longitude": 77.6,
            }
        ],
    }
    assert_conforms(payload, schema_name="provider_air_quality_observation_feed")


def test_platform_observation_schema_validates_canonical_observation():
    obs = {
        "observation_id": "obs_1",
        "entity_id": "sensor_1",
        "observed_property": "pm25",
        "value": 55.0,
        "unit": "µg/m3",
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "source": "openaq",
        "quality_flag": "ok",
    }
    assert_conforms(obs, schema_name="platform_observation")


def test_consumer_air_quality_decision_packet_validates_existing_fixture():
    # Keep this minimal: validate the same structure as existing strict tests.
    pkt = {
        "packet_id": "pkt_0123456789abcdef",
        "event_id": "evt_0123456789abcdef",
        "h3_id": "a",
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "confidence_level": "low",
        "actionability_level": "verify_only",
        "why_this_recommendation": "demo",
        "risk_of_error": [],
        "location": {"centroid_lat": 0.0, "centroid_lon": 0.0, "geometry_geojson": None},
        "summary": "demo",
        "prediction": {
            "current_pm25": 1.0,
            "forecast_pm25_mean": 2.0,
            "forecast_pm25_p10": 1.0,
            "forecast_pm25_p50": 2.0,
            "forecast_pm25_p90": 3.0,
            "forecast_pm25_std": 0.5,
            "uncertainty_band": 2.0,
            "pm25_category_india": "good",
        },
        "confidence": {
            "confidence_score": 0.2,
            "data_quality_score": 0.3,
            "driver_confidence": "low",
            "recommendation_allowed": False,
            "recommendation_block_reason": "demo",
        },
        "provenance": {
            "aq_source_type": "real",
            "weather_source_type": "real",
            "fire_source_type": "unavailable",
            "interpolation_method": "",
            "nearest_station_distance_km": 1.0,
            "station_count_used": 1,
            "warning_flags": "",
            "aq_source_reliability_min": None,
            "aq_source_reliability_avg": None,
        },
        "data_sources": [{"source_type": "air_quality", "source_name": "real", "source_mode": "observed", "confidence": 0.2, "notes": "demo"}],
        "evidence": {
            "observed_pm25_records": [],
            "observed_pm25_note": "",
            "nearby_station_records": [],
            "nearby_station_note": "",
            "weather_records": [],
            "static_features": [],
            "dynamic_features": [],
            "top_features_used": [],
        },
        "likely_contributing_factors": "unknown",
        "recommended_action": "demo",
        "review_guidance": {"questions_for_reviewer": [], "suggested_verification_steps": [], "when_not_to_act": []},
        "audit_context": {
            "number_of_real_aq_stations": 0,
            "percent_cells_interpolated": 0.0,
            "percent_cells_synthetic": 0.0,
            "avg_nearest_station_distance_km": 0.0,
            "spatial_validation_rmse": None,
            "model_vs_persistence_summary": "",
        },
        "provenance_summary": {
            "percent_cells_interpolated": 0.0,
            "percent_cells_synthetic": 0.0,
            "percent_low_confidence": None,
            "number_of_real_aq_stations": 0,
            "avg_nearest_station_distance_km": None,
            "recommendation_allowed": True,
            "recommendation_block_reason": "",
        },
        "source_reliability_summary": {
            "aq_sensor_status_counts": {},
            "weather_source_status_counts": {},
            "low_reliability_sources_nearby": [],
            "reliability_warnings": [],
        },
    }
    assert_conforms(pkt, schema_name="decision_packet_air_quality")
    assert_conforms(pkt, schema_name="urban_decision_packet_core")


def test_manifest_has_contract_type_for_every_schema():
    m = load_manifest()
    for name, meta in (m.get("artifacts") or {}).items():
        assert "contract_type" in meta, f"Missing contract_type for {name}"


def test_backward_compatible_aliases_still_work():
    # We just assert the keys exist in manifest; deeper validation is covered elsewhere.
    m = load_manifest()
    arts = m.get("artifacts") or {}
    for k in ["decision_packet", "decision_packet_air_quality", "decision_packets", "source_reliability"]:
        assert k in arts

