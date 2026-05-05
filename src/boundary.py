from __future__ import annotations

"""
Legacy import path for boundary helpers.

Canonical: `urban_platform.applications.air_pollution.boundary`.
"""

from urban_platform.applications.air_pollution.boundary import (  # noqa: F401
    BoundaryBundle,
    boundary_from_bbox,
    boundary_from_ward_geojson,
    get_boundary_bundle,
    get_city_boundary,
)
