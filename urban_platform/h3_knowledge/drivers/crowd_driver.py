"""AirOS built-in crowd / gatherings driver — CCTV observation store."""
from __future__ import annotations

import os
from pathlib import Path
from urban_platform.h3_knowledge.drivers._base import _InTreeDriver
from urban_platform.sdk.driver_types import ConformanceResult


_DEFAULT_OBS_STORE = "data/processed/observation_store.parquet"
_DEFAULT_CAM_REGISTRY = "data/config/camera_registry.json"


class CrowdDriver(_InTreeDriver):
    domain = "crowd"
    cadence_hours = 0.25          # 15 minutes
    produces_assessments = True   # writes high-risk assessment on GATHERING_ALERT

    signal_names = [
        "PEOPLE_COUNT", "CAMERA_COUNT", "CROWD_DENSITY",
        "CROWD_INDEX", "GATHERING_ALERT", "DATA_CONFIDENCE",
    ]
    data_sources = ["CCTV observation store (observation_store.parquet)"]
    _required_env_vars = []

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from urban_platform.h3_knowledge.ingestor import _ingest_crowd
        return _ingest_crowd(city_id, bbox, force=force)

    def conformance_check(self) -> ConformanceResult:
        result = super().conformance_check()
        obs_path = Path(os.getenv("OBSERVATION_STORE_PATH", _DEFAULT_OBS_STORE))
        cam_path = Path(os.getenv("CAMERA_REGISTRY_PATH", _DEFAULT_CAM_REGISTRY))
        if not obs_path.exists():
            result.warnings.append(
                f"Observation store not found at {obs_path} — "
                "crowd domain will produce no data until the camera pipeline runs"
            )
        if not cam_path.exists():
            result.failures.append(
                f"Camera registry not found at {cam_path} — "
                "crowd domain cannot map entity_ids to H3 cells"
            )
            result.ok = False
        return result
