"""Rules registry package — configurable thresholds for all domain pipelines.

Quick start
-----------
    from airos.os.rules import rules

    threshold = rules.get("crowd", "gathering_threshold_per_km2", default=500.0)
    thresholds = rules.get("air", "pm25_category_thresholds_ug_m3")

    # City-specific override (defined in rules_registry.yaml under cities:)
    threshold = rules.get("crowd", "gathering_threshold_per_km2", city_id="mumbai")

    # Hot-reload after editing data/config/rules_registry.yaml
    rules.reload()

See urban_platform/rules/registry.py for full documentation.
"""
from airos.os.rules.registry import rules, RulesRegistry

__all__ = ["rules", "RulesRegistry"]
