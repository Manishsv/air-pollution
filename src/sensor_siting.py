from __future__ import annotations

"""
Legacy import path for sensor siting (planning support).

Canonical: `urban_platform.applications.air_pollution.sensor_siting`.
"""

from urban_platform.applications.air_pollution.sensor_siting import (  # noqa: F401
    DEMO_LOW_CONFIDENCE_WARNING,
    compute_sensor_candidates,
    merge_sensor_siting_into_metrics,
    run_sensor_siting,
    _normalize_01,
)
