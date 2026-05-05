from __future__ import annotations

"""
Legacy import path for runtime configuration objects.

Canonical implementation lives in `urban_platform.common.runtime_config`.
"""

from urban_platform.common.runtime_config import (  # noqa: F401
    AQConfig,
    AppConfig,
    BBox,
    CacheConfig,
    ConformanceConfig,
    DevConfig,
    ModelConfig,
    OSMConfig,
    QualityGates,
    RandomForestConfig,
    SensorSitingConfig,
    env_bool,
    load_config,
)
