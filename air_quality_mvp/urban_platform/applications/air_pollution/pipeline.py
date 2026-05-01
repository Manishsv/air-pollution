from __future__ import annotations

from pathlib import Path
from typing import Dict

from src.pipeline import run_pipeline as _legacy_run
from urban_platform.common.config import AppConfig


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

    Migration note: currently delegates to legacy `src.pipeline.run_pipeline` while
    layers are introduced incrementally.
    """
    return _legacy_run(
        config,
        step=step,
        refresh_scope=refresh_scope,
        no_recommendations=no_recommendations,
        sample_mode_override=sample_mode_override,
        sensor_siting_mode=sensor_siting_mode,
    )

