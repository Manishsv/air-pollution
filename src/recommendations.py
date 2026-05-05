from __future__ import annotations

"""
Legacy import path for PM2.5 recommendation rule attachment.

Canonical: `urban_platform.decision_support.pm25_recommendation_rules`.
"""

from urban_platform.decision_support.pm25_recommendation_rules import (  # noqa: F401
    ACTION_LIBRARY,
    attach_recommendations,
    likely_contributing_factors_rules,
    pm25_category_india,
)
