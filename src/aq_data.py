from __future__ import annotations

"""
Legacy import path for OpenAQ helpers, synthetic stations, AQ panel IDW, spatial validation.

Canonical: `urban_platform.applications.air_pollution.aq_data`.
"""

from urban_platform.applications.air_pollution.aq_data import (  # noqa: F401
    assign_stations_to_h3,
    build_aq_panel,
    fetch_openaq_pm25,
    fetch_openaq_pm25_v3,
    generate_synthetic_station_pm25,
    spatial_station_holdout_validation,
)
