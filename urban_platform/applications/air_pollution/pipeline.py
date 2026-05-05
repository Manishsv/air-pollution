from __future__ import annotations

from pathlib import Path
from typing import Dict

from urban_platform.common.config import AppConfig
from urban_platform.applications.air_pollution.legacy_pipeline import run_pipeline as _legacy_run


def run_air_pollution_pipeline(
    config: AppConfig,
    *,
    step: str = "all",
    refresh_scope: str = "none",
    no_recommendations: bool = False,
    sample_mode_override: bool | None = None,
    sensor_siting_mode: str | None = None,
) -> Dict[str, Path]:
    """
    Reference application entrypoint.

    Migration note: delegates to `urban_platform.applications.air_pollution.legacy_pipeline.run_pipeline`
    (historical AQ orchestration consolidated here incrementally).
    """
    return _legacy_run(
        config,
        step=step,
        refresh_scope=refresh_scope,
        no_recommendations=no_recommendations,
        sample_mode_override=sample_mode_override,
        sensor_siting_mode=sensor_siting_mode,
    )

