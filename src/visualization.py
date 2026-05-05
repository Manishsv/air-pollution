from __future__ import annotations

"""
Legacy import path for Folium HTML map outputs.

Canonical implementation: `urban_platform.applications.air_pollution.folium_maps`.
"""

from urban_platform.applications.air_pollution.folium_maps import (  # noqa: F401
    save_hotspot_recommendations_map,
    save_pm25_map,
    save_sensor_siting_candidates_map,
)
