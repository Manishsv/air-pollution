from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from . import aq_data, boundary as boundary_mod, cache as cache_mod, feature_engineering, fire_data, grid as grid_mod
from .config import AppConfig
from .model import predict_latest, train_models
from .osm_features import download_osm_features
from .recommendations import attach_recommendations
from .visualization import save_hotspot_recommendations_map, save_pm25_map
from .weather_data import fetch_open_meteo_hourly, generate_synthetic_weather


logger = logging.getLogger(__name__)


def _cache_ok(cfg: AppConfig, path: Path) -> bool:
    if not cfg.cache.enabled:
        return False
    if cfg.cache.force_refresh:
        return False
    return cache_mod.cache_exists(path) and cache_mod.is_cache_valid(path, cfg.cache.ttl_days)


def run_pipeline(cfg: AppConfig) -> Dict[str, Path]:
    processed_dir = cfg.data_processed_dir
    outputs_dir = cfg.data_outputs_dir

    processed_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

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
    if _cache_ok(cfg, boundary_cache):
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
    if _cache_ok(cfg, grid_cache):
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
        if _cache_ok(cfg, osm_cache):
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
                sample_mode=cfg.development.sample_mode,
                max_buildings=cfg.development.max_buildings,
                max_roads=cfg.development.max_roads,
                max_pois=cfg.development.max_pois,
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
    if _cache_ok(cfg, static_cache):
        static_features = cache_mod.load_cached_geodata(static_cache)
        logger.info("Loaded cached static features: %s", static_cache.name)
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
    if _cache_ok(cfg, aq_station_cache):
        stations_hourly = cache_mod.load_cached_dataframe(aq_station_cache)
        logger.info("Loaded cached AQ station data: %s", aq_station_cache.name)
    else:
        stations_hourly = aq_data.fetch_openaq_pm25(cfg.city_name, cfg.lookback_days)
        if stations_hourly.empty or stations_hourly["timestamp"].nunique() < 48:
            logger.warning("OpenAQ insufficient; generating synthetic AQ station data (documented).")
            poly = bundle.boundary_wgs84.geometry.iloc[0]
            stations_hourly = aq_data.generate_synthetic_station_pm25(boundary_wgs84_polygon=poly, lookback_days=cfg.lookback_days)
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
    if _cache_ok(cfg, aq_panel_cache):
        aq_panel = cache_mod.load_cached_dataframe(aq_panel_cache)
        logger.info("Loaded cached AQ panel: %s", aq_panel_cache.name)
    else:
        aq_panel = aq_data.build_aq_panel(
            h3_grid=h3_grid[["h3_id", "centroid_lat", "centroid_lon"]],
            stations_hourly=stations_hourly,
            lookback_days=cfg.lookback_days,
            h3_resolution=cfg.h3_resolution,
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
    if _cache_ok(cfg, weather_cache):
        weather = cache_mod.load_cached_dataframe(weather_cache)
        logger.info("Loaded cached weather: %s", weather_cache.name)
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
    if _cache_ok(cfg, fire_cache):
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
    if _cache_ok(cfg, dataset_cache):
        dataset = cache_mod.load_cached_dataframe(dataset_cache)
        logger.info("Loaded cached model dataset: %s", dataset_cache.name)
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

    # 9) Train/evaluate + save model
    target_col = f"pm25_t_plus_{int(cfg.forecast_horizon_hours)}h"
    artifacts, metrics_all = train_models(dataset, target_col=target_col, outputs_dir=outputs_dir)

    metrics_path = outputs_dir / "metrics.json"
    cache_mod.save_json(
        {
            "best_model": artifacts.model_name,
            "best_metrics": artifacts.metrics,
            "all_models": metrics_all,
            "target_col": target_col,
        },
        metrics_path,
    )

    # 10) Predict latest + recommendations
    latest_pred = predict_latest(dataset=dataset, model_path=artifacts.model_path, target_col=target_col)
    latest_pred = latest_pred.rename(columns={"current_pm25": "current_pm25"})
    recs = attach_recommendations(latest_pred, thresholds=cfg.pm25_hotspot_thresholds)

    # Geo outputs: join with grid geometry
    grid_geo = h3_grid[["h3_id", "geometry", "centroid_lat", "centroid_lon", "area_sqkm"]].copy()
    recs_geo = gpd.GeoDataFrame(grid_geo.merge(recs, on="h3_id", how="left"), geometry="geometry", crs="EPSG:4326")
    recs_geo_path = outputs_dir / "hotspot_recommendations.geojson"
    cache_mod.save_cached_geodata(recs_geo, recs_geo_path)

    # 11) Maps
    current_map = outputs_dir / "current_pm25_map.html"
    forecast_map = outputs_dir / "forecast_pm25_map.html"
    recs_map = outputs_dir / "hotspot_recommendations_map.html"

    save_pm25_map(grid_geo=grid_geo, data_df=recs, value_col="current_pm25", out_html=current_map, title="Current PM2.5")
    save_pm25_map(grid_geo=grid_geo, data_df=recs, value_col="forecast_pm25", out_html=forecast_map, title="Forecast PM2.5")
    save_hotspot_recommendations_map(grid_geo=grid_geo, recs_df=recs, out_html=recs_map)

    return {
        "h3_grid_geojson": h3_grid_out,
        "static_features_geojson": static_out,
        "model_dataset_csv": dataset_out,
        "model_joblib": artifacts.model_path,
        "metrics_json": metrics_path,
        "hotspot_recommendations_geojson": recs_geo_path,
        "current_pm25_map_html": current_map,
        "forecast_pm25_map_html": forecast_map,
        "hotspot_recommendations_map_html": recs_map,
    }

