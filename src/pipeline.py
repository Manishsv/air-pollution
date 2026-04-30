from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from . import aq_data, boundary as boundary_mod, cache as cache_mod, feature_engineering, fire_data, grid as grid_mod
from .config import AppConfig
from .data_audit import audit_data_coverage, print_audit_summary
from .model import predict_latest, train_models
from .osm_features import download_osm_features
from .provenance import dataset_provenance_summary
from .recommendations import attach_recommendations
from .scale_analysis import analyze_h3_resolution
from .visualization import save_hotspot_recommendations_map, save_pm25_map, save_sensor_siting_candidates_map
from .weather_data import fetch_open_meteo_hourly, generate_synthetic_weather


logger = logging.getLogger(__name__)


def _cache_ok(cfg: AppConfig, path: Path, *, refresh_scope: str = "none", artifact: str = "") -> bool:
    if not cfg.cache.enabled:
        return False
    if cfg.cache.force_refresh:
        return False
    if refresh_scope == "all":
        return False
    if refresh_scope == "aq" and artifact in {"aq_stations", "aq_panel", "model_dataset"}:
        return False
    return cache_mod.cache_exists(path) and cache_mod.is_cache_valid(path, cfg.cache.ttl_days)


def run_pipeline(
    cfg: AppConfig,
    *,
    step: str = "all",  # audit | model | visualize | all | sensor-siting
    refresh_scope: str = "none",  # none | aq | all
    no_recommendations: bool = False,
    sample_mode_override: bool | None = None,
    sensor_siting_mode: str | None = None,
) -> Dict[str, Path]:
    processed_dir = cfg.data_processed_dir
    outputs_dir = cfg.data_outputs_dir

    processed_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    if step == "sensor-siting":
        if not getattr(cfg.sensor_siting, "enabled", True):
            logger.warning("sensor_siting.disabled in config; skipping sensor siting.")
            return {"metrics_json": outputs_dir / "metrics.json"}
        from .sensor_siting import run_sensor_siting

        cand, _summary = run_sensor_siting(cfg=cfg, mode_override=sensor_siting_mode or None)
        siting_geo = outputs_dir / "sensor_siting_candidates.geojson"
        siting_map = outputs_dir / "sensor_siting_candidates_map.html"
        save_sensor_siting_candidates_map(candidates=cand, out_html=siting_map)
        return {
            "metrics_json": outputs_dir / "metrics.json",
            "sensor_siting_candidates_geojson": siting_geo,
            "sensor_siting_candidates_map_html": siting_map,
        }

    # 1) Boundary bundle (also provides cache key parts)
    bbox_input = None
    if cfg.bbox:
        bbox_input = (cfg.bbox.north, cfg.bbox.south, cfg.bbox.east, cfg.bbox.west)

    # Boundary cache path
    boundary_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "boundary",
        bbox=(cfg.bbox.south, cfg.bbox.north, cfg.bbox.west, cfg.bbox.east) if cfg.bbox else None,
        ext="geojson",
    )
    if _cache_ok(cfg, boundary_cache, refresh_scope=refresh_scope, artifact="boundary"):
        boundary_wgs84 = cache_mod.load_cached_geodata(boundary_cache)
        boundary_projected = boundary_wgs84.to_crs(cfg.local_crs)
        geom = boundary_wgs84.geometry.iloc[0]
        poly_hash = __import__("hashlib").sha1(geom.wkb_hex.encode("utf-8")).hexdigest()[:10]
        bundle = boundary_mod.BoundaryBundle(
            boundary_wgs84=boundary_wgs84,
            boundary_projected=boundary_projected,
            bbox_tuple=(cfg.bbox.south, cfg.bbox.north, cfg.bbox.west, cfg.bbox.east) if cfg.bbox else None,
            poly_hash=poly_hash,
        )
        logger.info("Loaded cached boundary: %s", boundary_cache.name)
    else:
        bundle = boundary_mod.get_boundary_bundle(
            spatial_mode=cfg.spatial_mode,
            city_name=cfg.city_name,
            fallback_city_name=cfg.fallback_city_name,
            local_crs=cfg.local_crs,
            bbox=bbox_input,
            ward_polygon_path=cfg.ward_polygon_path,
        )
        cache_mod.save_cached_geodata(bundle.boundary_wgs84, boundary_cache)
        logger.info("Saved boundary cache: %s", boundary_cache.name)

    # 2) H3 grid
    grid_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "h3_grid",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="geojson",
    )
    if _cache_ok(cfg, grid_cache, refresh_scope=refresh_scope, artifact="grid"):
        h3_grid = cache_mod.load_cached_geodata(grid_cache)
        logger.info("Loaded cached H3 grid: %s", grid_cache.name)
    else:
        h3_grid = grid_mod.create_h3_grid(bundle.boundary_wgs84, cfg.h3_resolution)
        cache_mod.save_cached_geodata(h3_grid, grid_cache)
        logger.info("Saved H3 grid cache: %s", grid_cache.name)

    # Always export requested canonical path too
    h3_grid_out = processed_dir / "h3_grid.geojson"
    cache_mod.save_cached_geodata(h3_grid, h3_grid_out)

    # 3) OSM features (cached separately)
    osm_outputs: Dict[str, gpd.GeoDataFrame] = {}
    for dtype in ["roads", "buildings", "landuse", "pois"]:
        osm_cache = cache_mod.cache_path(
            processed_dir,
            cfg.city_name,
            cfg.spatial_mode,
            cfg.h3_resolution,
            dtype,
            bbox=bundle.bbox_tuple,
            poly_hash=bundle.poly_hash,
            ext="geojson",
        )
        if _cache_ok(cfg, osm_cache, refresh_scope=refresh_scope, artifact=dtype):
            osm_outputs[dtype] = cache_mod.load_cached_geodata(osm_cache)
            logger.info("Loaded cached OSM %s: %s", dtype, osm_cache.name)
        else:
            # download once for all, then save to each cache path
            osm_outputs = download_osm_features(
                spatial_mode=cfg.spatial_mode,
                city_name=cfg.city_name,
                boundary_wgs84=bundle.boundary_wgs84,
                boundary_projected=bundle.boundary_projected,
                local_crs=cfg.local_crs,
                sample_mode=bool(cfg.development.sample_mode if sample_mode_override is None else sample_mode_override),
                sample_seed=cfg.development.sample_seed,
                max_buildings=cfg.development.max_buildings,
                max_roads=cfg.development.max_roads,
                max_pois=cfg.development.max_pois,
                max_landuse=cfg.development.max_landuse,
                road_classes=cfg.osm.road_classes,
            )
            for k, gdf in osm_outputs.items():
                path_k = cache_mod.cache_path(
                    processed_dir,
                    cfg.city_name,
                    cfg.spatial_mode,
                    cfg.h3_resolution,
                    k,
                    bbox=bundle.bbox_tuple,
                    poly_hash=bundle.poly_hash,
                    ext="geojson",
                )
                cache_mod.save_cached_geodata(gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_string() != "EPSG:4326" else gdf, path_k)
            logger.info("Downloaded and cached OSM features.")
            break

    # Ensure projected CRS for feature computation
    osm_proj = {k: v.to_crs(cfg.local_crs) if (not v.empty and v.crs) else v for k, v in osm_outputs.items()}

    # 4) Static features
    static_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "static_features",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="geojson",
    )
    if _cache_ok(cfg, static_cache, refresh_scope=refresh_scope, artifact="static_features"):
        static_features = cache_mod.load_cached_geodata(static_cache)
        logger.info("Loaded cached static features: %s", static_cache.name)
        if "osm_source_type" not in static_features.columns:
            logger.warning("Cached static features missing provenance columns; rebuilding.")
            static_features = feature_engineering.build_static_features(
                h3_grid_wgs84=h3_grid,
                boundary_projected=bundle.boundary_projected,
                osm=osm_proj,
                local_crs=cfg.local_crs,
            )
            cache_mod.save_cached_geodata(static_features, static_cache)
    else:
        static_features = feature_engineering.build_static_features(
            h3_grid_wgs84=h3_grid,
            boundary_projected=bundle.boundary_projected,
            osm=osm_proj,
            local_crs=cfg.local_crs,
        )
        cache_mod.save_cached_geodata(static_features, static_cache)
        logger.info("Saved static features cache: %s", static_cache.name)

    static_out = processed_dir / "static_features.geojson"
    cache_mod.save_cached_geodata(static_features, static_out)

    # 5) AQ data (OpenAQ -> fallback synthetic)
    aq_station_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "aq_stations",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="parquet",
    )
    if _cache_ok(cfg, aq_station_cache, refresh_scope=refresh_scope, artifact="aq_stations"):
        stations_hourly = cache_mod.load_cached_dataframe(aq_station_cache)
        logger.info("Loaded cached AQ station data: %s", aq_station_cache.name)
    else:
        # OpenAQ v2 is retired; prefer v3 via bbox when possible.
        stations_hourly = pd.DataFrame()
        if bundle.bbox_tuple is not None:
            # bundle.bbox_tuple is (south,north,west,east) → convert to (west,south,east,north)
            south, north, west, east = bundle.bbox_tuple
            stations_hourly = aq_data.fetch_openaq_pm25_v3(
                bbox_west_south_east_north=(west, south, east, north),
                lookback_days=cfg.lookback_days,
                cache_dir=cfg.data_processed_dir / "cache",
                cache_ttl_days=cfg.cache.ttl_days,
                force_refresh=cfg.cache.force_refresh,
            )
        if stations_hourly.empty:
            stations_hourly = aq_data.fetch_openaq_pm25(cfg.city_name, cfg.lookback_days)

        if stations_hourly.empty or stations_hourly["timestamp"].nunique() < 48:
            logger.warning("OpenAQ insufficient; generating synthetic AQ station data (documented).")
            poly = bundle.boundary_wgs84.geometry.iloc[0]
            stations_hourly = aq_data.generate_synthetic_station_pm25(
                boundary_wgs84_polygon=poly,
                lookback_days=cfg.lookback_days,
            )
        cache_mod.save_cached_dataframe(stations_hourly, aq_station_cache)

    aq_panel_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "aq_panel",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="parquet",
    )
    if _cache_ok(cfg, aq_panel_cache, refresh_scope=refresh_scope, artifact="aq_panel"):
        aq_panel = cache_mod.load_cached_dataframe(aq_panel_cache)
        logger.info("Loaded cached AQ panel: %s", aq_panel_cache.name)
        # Schema guard: older caches may lack provenance columns
        if "aq_source_type" not in aq_panel.columns or "nearest_station_distance_km" not in aq_panel.columns:
            logger.warning("Cached AQ panel missing provenance columns; rebuilding.")
            aq_panel = aq_data.build_aq_panel(
                h3_grid=h3_grid[["h3_id", "centroid_lat", "centroid_lon"]],
                stations_hourly=stations_hourly,
                lookback_days=cfg.lookback_days,
                h3_resolution=cfg.h3_resolution,
                idw_power=cfg.aq.idw_power,
                min_stations=cfg.aq.min_stations,
            )
            cache_mod.save_cached_dataframe(aq_panel, aq_panel_cache)
    else:
        aq_panel = aq_data.build_aq_panel(
            h3_grid=h3_grid[["h3_id", "centroid_lat", "centroid_lon"]],
            stations_hourly=stations_hourly,
            lookback_days=cfg.lookback_days,
            h3_resolution=cfg.h3_resolution,
            idw_power=cfg.aq.idw_power,
            min_stations=cfg.aq.min_stations,
        )
        cache_mod.save_cached_dataframe(aq_panel, aq_panel_cache)

    # 6) Weather data
    weather_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "weather_hourly",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="parquet",
    )
    if _cache_ok(cfg, weather_cache, refresh_scope=refresh_scope, artifact="weather"):
        weather = cache_mod.load_cached_dataframe(weather_cache)
        logger.info("Loaded cached weather: %s", weather_cache.name)
        # Schema guard: older caches may lack provenance columns
        if "weather_source_type" not in weather.columns:
            logger.warning("Cached weather missing provenance columns; rebuilding.")
            centroid_lat = float(bundle.boundary_wgs84.geometry.iloc[0].centroid.y)
            centroid_lon = float(bundle.boundary_wgs84.geometry.iloc[0].centroid.x)
            weather = fetch_open_meteo_hourly(latitude=centroid_lat, longitude=centroid_lon, lookback_days=cfg.lookback_days)
            if weather.empty or weather["timestamp"].nunique() < 48:
                logger.warning("Weather API insufficient; generating synthetic weather.")
                weather = generate_synthetic_weather(cfg.lookback_days)
            cache_mod.save_cached_dataframe(weather, weather_cache)
    else:
        centroid_lat = float(bundle.boundary_wgs84.geometry.iloc[0].centroid.y)
        centroid_lon = float(bundle.boundary_wgs84.geometry.iloc[0].centroid.x)
        weather = fetch_open_meteo_hourly(latitude=centroid_lat, longitude=centroid_lon, lookback_days=cfg.lookback_days)
        if weather.empty or weather["timestamp"].nunique() < 48:
            logger.warning("Weather API insufficient; generating synthetic weather.")
            weather = generate_synthetic_weather(cfg.lookback_days)
        cache_mod.save_cached_dataframe(weather, weather_cache)

    # 7) Fire data (optional; defaults to zeros)
    fire_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "fire_panel",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="parquet",
    )
    if _cache_ok(cfg, fire_cache, refresh_scope=refresh_scope, artifact="fire"):
        fire_panel = cache_mod.load_cached_dataframe(fire_cache)
        logger.info("Loaded cached fire panel: %s", fire_cache.name)
    else:
        fire_panel = fire_data.build_fire_features_panel(
            h3_grid=h3_grid[["h3_id", "centroid_lat", "centroid_lon"]],
            lookback_days=cfg.lookback_days,
            bbox_south_north_west_east=bundle.bbox_tuple,
        )
        cache_mod.save_cached_dataframe(fire_panel, fire_cache)

    # 8) Model dataset
    dataset_cache = cache_mod.cache_path(
        processed_dir,
        cfg.city_name,
        cfg.spatial_mode,
        cfg.h3_resolution,
        "model_dataset",
        bbox=bundle.bbox_tuple,
        poly_hash=bundle.poly_hash,
        ext="csv",
    )
    if _cache_ok(cfg, dataset_cache, refresh_scope=refresh_scope, artifact="model_dataset"):
        dataset = cache_mod.load_cached_dataframe(dataset_cache)
        logger.info("Loaded cached model dataset: %s", dataset_cache.name)
        if "data_quality_score" not in dataset.columns or "aq_source_type" not in dataset.columns:
            logger.warning("Cached model dataset missing provenance columns; rebuilding.")
            dataset = feature_engineering.build_panel_dataset(
                h3_grid_wgs84=h3_grid,
                static_features_wgs84=static_features,
                aq_panel=aq_panel,
                weather_hourly=weather,
                fire_panel=fire_panel,
                forecast_horizon_hours=cfg.forecast_horizon_hours,
            )
            cache_mod.save_cached_dataframe(dataset, dataset_cache)
    else:
        dataset = feature_engineering.build_panel_dataset(
            h3_grid_wgs84=h3_grid,
            static_features_wgs84=static_features,
            aq_panel=aq_panel,
            weather_hourly=weather,
            fire_panel=fire_panel,
            forecast_horizon_hours=cfg.forecast_horizon_hours,
        )
        cache_mod.save_cached_dataframe(dataset, dataset_cache)

    dataset_out = processed_dir / "model_dataset.csv"
    cache_mod.save_cached_dataframe(dataset, dataset_out)

    # 8.5) Data audit BEFORE modelling
    audit = audit_data_coverage(
        grid_gdf=h3_grid,
        aq_stations_hourly=stations_hourly,
        aq_panel=aq_panel,
        model_dataset=dataset,
        h3_resolution=cfg.h3_resolution,
        quality_gates=cfg.quality_gates.__dict__,
    )
    print_audit_summary(audit)
    audit_path = outputs_dir / "data_audit.json"
    cache_mod.save_json(audit, audit_path)

    # 8.6) Scale analysis (H3 resolution honesty)
    scale = analyze_h3_resolution(h3_grid, stations_hourly)
    # attach actual resolution and distance if present
    scale["h3_resolution"] = int(cfg.h3_resolution)
    scale_path = outputs_dir / "scale_analysis.json"
    cache_mod.save_json(scale, scale_path)

    if step == "audit":
        return {
            "h3_grid_geojson": h3_grid_out,
            "static_features_geojson": static_out,
            "model_dataset_csv": dataset_out,
            "data_audit_json": audit_path,
            "scale_analysis_json": scale_path,
        }

    # 9) Train/evaluate + save model
    target_col = f"pm25_t_plus_{int(cfg.forecast_horizon_hours)}h"
    artifacts, metrics_all = train_models(
        dataset,
        target_col=target_col,
        outputs_dir=outputs_dir,
        test_fraction=cfg.model.test_fraction,
        force_model=cfg.model.force_model,
        rf_params={
            "n_estimators": cfg.model.random_forest.n_estimators,
            "min_samples_leaf": cfg.model.random_forest.min_samples_leaf,
            "random_state": cfg.model.random_forest.random_state,
        },
    )

    metrics_path = outputs_dir / "metrics.json"
    # Model warning flags (non-leaky integrity check)
    model_warning_flags = ""
    best = metrics_all.get(artifacts.model_name, {})
    if best and float(best.get("RMSE_improvement_vs_persistence", 0.0)) <= 0:
        model_warning_flags = "ML model does not outperform persistence baseline"

    spatial_val = aq_data.spatial_station_holdout_validation(
        stations_hourly=stations_hourly,
        lookback_days=cfg.lookback_days,
        idw_power=cfg.aq.idw_power,
        min_real_stations=int(cfg.quality_gates.min_real_stations_required) + 1,
    )

    cache_mod.save_json(
        {
            "project_framing": "Probabilistic urban air-quality observability MVP under sparse data conditions",
            "best_model": artifacts.model_name,
            "best_metrics": artifacts.metrics,
            "all_models": metrics_all,
            "target_col": target_col,
            "data_audit": audit,
            "scale_analysis": scale,
            "provenance_summary": dataset_provenance_summary(dataset),
            "model_warning_flags": model_warning_flags,
            **spatial_val,
        },
        metrics_path,
    )

    if step == "model":
        return {
            "h3_grid_geojson": h3_grid_out,
            "static_features_geojson": static_out,
            "model_dataset_csv": dataset_out,
            "model_joblib": artifacts.model_path,
            "metrics_json": metrics_path,
            "data_audit_json": audit_path,
            "scale_analysis_json": scale_path,
        }

    # 10) Predict latest + recommendations
    latest_pred = predict_latest(dataset=dataset, model_path=artifacts.model_path, target_col=target_col)
    latest_pred = latest_pred.rename(columns={"current_pm25": "current_pm25"})

    recommendation_allowed = bool(audit.get("recommendation_allowed", True))
    recommendation_block_reason = str(audit.get("recommendation_block_reason", ""))
    if no_recommendations:
        recommendation_allowed = False
        recommendation_block_reason = "Recommendations disabled by CLI (--no-recommendations)"

    recs = attach_recommendations(
        latest_pred,
        pm25_categories=cfg.pm25_categories_india,
        recommendation_allowed=recommendation_allowed,
        recommendation_block_reason=recommendation_block_reason,
        model_warning_flags=model_warning_flags,
    )

    # Confidence score combines data quality and forecast uncertainty (heuristic, 0..1)
    if "data_quality_score" in recs.columns:
        band = pd.to_numeric(recs.get("uncertainty_band"), errors="coerce").fillna(999.0)
        # map band 0..100 to multiplier 1..0.2
        unc_mult = (1.0 - (band.clip(0, 100) / 125.0)).clip(0.2, 1.0)
        recs["confidence_score"] = (pd.to_numeric(recs["data_quality_score"], errors="coerce").fillna(0.0) * unc_mult).clip(0.0, 1.0)
    else:
        recs["confidence_score"] = 0.0

    # Output schema aliases
    recs["current_pm25_source_type"] = recs.get("aq_source_type", "unavailable")

    # Geo outputs: join with grid geometry
    grid_geo = h3_grid[["h3_id", "geometry", "centroid_lat", "centroid_lon", "area_sqkm"]].copy()
    recs_geo = gpd.GeoDataFrame(grid_geo.merge(recs, on="h3_id", how="left"), geometry="geometry", crs="EPSG:4326")
    recs_geo_path = outputs_dir / "hotspot_recommendations.geojson"
    cache_mod.save_cached_geodata(recs_geo, recs_geo_path)

    # 11) Maps
    current_map = outputs_dir / "current_pm25_map.html"
    forecast_map = outputs_dir / "forecast_pm25_map.html"
    recs_map = outputs_dir / "hotspot_recommendations_map.html"

    save_pm25_map(grid_geo=grid_geo, data_df=recs, value_col="current_pm25", out_html=current_map, title="Current PM2.5", audit=audit)
    save_pm25_map(grid_geo=grid_geo, data_df=recs, value_col="forecast_pm25_mean", out_html=forecast_map, title="Forecast PM2.5 (mean)", audit=audit)
    save_hotspot_recommendations_map(grid_geo=grid_geo, recs_df=recs, out_html=recs_map, audit=audit)

    ss_outputs: Dict[str, Path] = {}
    if bool(getattr(cfg.sensor_siting, "enabled", True)) and step in ("all", "visualize"):
        from .sensor_siting import run_sensor_siting

        cand, _summ = run_sensor_siting(cfg=cfg, mode_override=sensor_siting_mode or None)
        ss_geo_path = outputs_dir / "sensor_siting_candidates.geojson"
        ss_map_path = outputs_dir / "sensor_siting_candidates_map.html"
        save_sensor_siting_candidates_map(candidates=cand, out_html=ss_map_path)
        ss_outputs["sensor_siting_candidates_geojson"] = ss_geo_path
        ss_outputs["sensor_siting_candidates_map_html"] = ss_map_path

    base_out = {
        "h3_grid_geojson": h3_grid_out,
        "static_features_geojson": static_out,
        "model_dataset_csv": dataset_out,
        "model_joblib": artifacts.model_path,
        "metrics_json": metrics_path,
        "data_audit_json": audit_path,
        "scale_analysis_json": scale_path,
        "hotspot_recommendations_geojson": recs_geo_path,
        "current_pm25_map_html": current_map,
        "forecast_pm25_map_html": forecast_map,
        "hotspot_recommendations_map_html": recs_map,
    }
    base_out.update(ss_outputs)
    return base_out

