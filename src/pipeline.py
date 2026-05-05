from __future__ import annotations

from pathlib import Path
from typing import Dict

from urban_platform.common.config import AppConfig
from urban_platform.applications.air_pollution.legacy_pipeline import run_pipeline as _run_pipeline


def run_pipeline(
    cfg: AppConfig,
    *,
    step: str = "all",
    refresh_scope: str = "none",
    no_recommendations: bool = False,
    sample_mode_override: bool | None = None,
    sensor_siting_mode: str | None = None,
) -> Dict[str, Path]:
    return _run_pipeline(
        cfg,
        step=step,
        refresh_scope=refresh_scope,
        no_recommendations=no_recommendations,
        sample_mode_override=sample_mode_override,
        sensor_siting_mode=sensor_siting_mode,
    )

