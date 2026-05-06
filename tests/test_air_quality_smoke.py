"""
Minimal smoke test for the legacy Air Quality pipeline path used by main.py.

Stubs external data fetches (OpenAQ, Open-Meteo, OSM) and fixes synthetic time bases
so the run is fast, offline, and deterministic. Writes only under tmp_path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

from urban_platform.applications.air_pollution.pipeline import run_air_pollution_pipeline
from urban_platform.common.config import load_config

FIXED_UTC_HOUR = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

_SMOKE_CONFIG_YAML = """
city_name: "AQ Smoke Test"
fallback_city_name: "AQ Smoke Test"
spatial_mode: bbox
ward_polygon_path: null
bbox:
  north: 12.99
  south: 12.94
  east: 77.62
  west: 77.57
h3_resolution: 7
forecast_horizon_hours: 1
lookback_days: 5
local_crs: "EPSG:4326"
pm25_hotspot_thresholds: {}
development:
  sample_mode: true
  sample_seed: 42
  max_buildings: 10
  max_roads: 10
  max_pois: 10
  max_landuse: 10
cache:
  enabled: false
conformance:
  enabled: false
  fail_on_error: false
sensor_siting:
  enabled: false
model:
  test_fraction: 0.3
  force_model: random_forest
  random_forest:
    n_estimators: 10
    min_samples_leaf: 2
    random_state: 42
"""


def _patch_offline_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    def _frozen_utc_now_hour() -> datetime:
        return FIXED_UTC_HOUR

    monkeypatch.setattr(
        "urban_platform.applications.air_pollution.aq_data._utc_now_hour",
        _frozen_utc_now_hour,
    )
    monkeypatch.setattr(
        "urban_platform.applications.air_pollution.fire_data._utc_now_hour",
        _frozen_utc_now_hour,
    )
    monkeypatch.setattr(
        "urban_platform.connectors.weather.hourly_archive._utc_now_hour",
        _frozen_utc_now_hour,
    )

    def fake_osm(**kwargs: object) -> dict[str, gpd.GeoDataFrame]:
        lc = str(kwargs["local_crs"])
        empty = gpd.GeoDataFrame(geometry=[], crs=lc)
        return {k: empty for k in ("roads", "buildings", "landuse", "pois")}

    monkeypatch.setattr(
        "urban_platform.applications.air_pollution.legacy_pipeline.download_osm_features",
        fake_osm,
    )
    monkeypatch.setattr(
        "urban_platform.applications.air_pollution.legacy_pipeline.fetch_openaq_connector",
        lambda _cfg: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "urban_platform.applications.air_pollution.legacy_pipeline.fetch_open_meteo_connector",
        lambda _ctx: pd.DataFrame(),
    )


def test_air_quality_legacy_pipeline_audit_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise main entry path: pipeline.run_air_pollution_pipeline -> legacy run_pipeline (audit step)."""
    _patch_offline_deterministic(monkeypatch)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_SMOKE_CONFIG_YAML.strip(), encoding="utf-8")

    app = load_config(cfg_path)
    outputs = run_air_pollution_pipeline(app, step="audit", refresh_scope="all")

    root = tmp_path.resolve()
    for label, p in outputs.items():
        assert p.exists(), f"missing output {label}: {p}"
        assert p.resolve().is_relative_to(root), f"output escaped tmp_path: {label} -> {p}"

    audit = json.loads(outputs["data_audit_json"].read_text(encoding="utf-8"))
    assert audit["h3_resolution"] == app.h3_resolution
    assert "recommendation_allowed" in audit

    scale = json.loads(outputs["scale_analysis_json"].read_text(encoding="utf-8"))
    assert int(scale["h3_resolution"]) == app.h3_resolution
