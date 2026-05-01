from __future__ import annotations

from review_dashboard.components.map_view import _sensor_reliability_color, prepare_layer_names


def test_prepare_layer_names_defaults_contains_expected_layers():
    names = prepare_layer_names({"areas": True, "selected": True, "aq_sensors": True})
    assert "Areas needing review" in names
    assert "Selected area" in names
    assert "AQ sensors" in names


def test_sensor_reliability_color_mapping():
    assert _sensor_reliability_color("healthy").startswith("#")
    assert _sensor_reliability_color("offline") == "#2c3e50"
    assert _sensor_reliability_color("unknown") == "#95a5a6"

