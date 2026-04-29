from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = True
    force_refresh: bool = False
    ttl_days: int = 30


@dataclass(frozen=True)
class DevConfig:
    sample_mode: bool = True
    max_buildings: int = 5000
    max_roads: int = 5000
    max_pois: int = 3000


@dataclass(frozen=True)
class BBox:
    north: float
    south: float
    east: float
    west: float


@dataclass(frozen=True)
class AppConfig:
    city_name: str
    fallback_city_name: str
    spatial_mode: str
    bbox: Optional[BBox]
    ward_polygon_path: Optional[str]
    h3_resolution: int
    forecast_horizon_hours: int
    lookback_days: int
    local_crs: str
    pm25_hotspot_thresholds: Dict[str, float]
    cache: CacheConfig
    development: DevConfig
    project_root: Path
    data_raw_dir: Path
    data_processed_dir: Path
    data_outputs_dir: Path


def _as_path(p: str | Path) -> Path:
    return p if isinstance(p, Path) else Path(p)


def load_config(config_path: str | Path) -> AppConfig:
    config_path = _as_path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = yaml.safe_load(f)

    project_root = config_path.parent
    data_raw_dir = project_root / "data" / "raw"
    data_processed_dir = project_root / "data" / "processed"
    data_outputs_dir = project_root / "data" / "outputs"

    bbox_cfg = cfg.get("bbox")
    bbox = None
    if bbox_cfg:
        bbox = BBox(
            north=float(bbox_cfg["north"]),
            south=float(bbox_cfg["south"]),
            east=float(bbox_cfg["east"]),
            west=float(bbox_cfg["west"]),
        )

    cache_cfg = cfg.get("cache", {}) or {}
    dev_cfg = cfg.get("development", {}) or {}

    return AppConfig(
        city_name=str(cfg.get("city_name", "Bengaluru, India")),
        fallback_city_name=str(cfg.get("fallback_city_name", "Delhi, India")),
        spatial_mode=str(cfg.get("spatial_mode", "bbox")),
        bbox=bbox,
        ward_polygon_path=cfg.get("ward_polygon_path"),
        h3_resolution=int(cfg.get("h3_resolution", 7)),
        forecast_horizon_hours=int(cfg.get("forecast_horizon_hours", 12)),
        lookback_days=int(cfg.get("lookback_days", 14)),
        local_crs=str(cfg.get("local_crs", "EPSG:32643")),
        pm25_hotspot_thresholds=dict(cfg.get("pm25_hotspot_thresholds", {})),
        cache=CacheConfig(
            enabled=bool(cache_cfg.get("enabled", True)),
            force_refresh=bool(cache_cfg.get("force_refresh", False)),
            ttl_days=int(cache_cfg.get("ttl_days", 30)),
        ),
        development=DevConfig(
            sample_mode=bool(dev_cfg.get("sample_mode", True)),
            max_buildings=int(dev_cfg.get("max_buildings", 5000)),
            max_roads=int(dev_cfg.get("max_roads", 5000)),
            max_pois=int(dev_cfg.get("max_pois", 3000)),
        ),
        project_root=project_root,
        data_raw_dir=data_raw_dir,
        data_processed_dir=data_processed_dir,
        data_outputs_dir=data_outputs_dir,
    )


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

