"""
Google Earth Engine connector for flood risk.

Fetches recent precipitation (GPM IMERG) and terrain elevation (SRTM)
for a city bounding box. Returns per-point observations compatible with
the flood pipeline's rainfall input format.

Requires:
  - earthengine-api installed  (pip install earthengine-api)
  - GEE authenticated          (earthengine authenticate, or service account)

Precipitation source:  NASA/GPM_L3/IMERG_V07  — 0.1° (~11 km), 30-min, near-real-time
Elevation source:      USGS/SRTMGL1_003        — 30 m
JRC surface water:     JRC/GSW1_4/GlobalSurfaceWater — historical flood extent

Flood risk score (0–1):
  rain_score     = clip(precip_3h_mm / 50, 0, 1)    # 50 mm/3h → 1
  terrain_score  = clip(1 - elev_m / 100, 0, 1)     # <10 m elev → higher risk
  water_score    = jrc_occurrence / 100              # historical surface water fraction
  flood_risk     = 0.5 * rain_score + 0.3 * terrain_score + 0.2 * water_score
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_COLUMNS = [
    "station_id", "latitude", "longitude", "timestamp",
    "rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm",
    "elevation_m", "jrc_water_occurrence",
    "flood_risk_score",
    "data_source", "quality_flag",
]

_GPM_COLLECTION  = "NASA/GPM_L3/IMERG_V07"
_SRTM_DATASET    = "USGS/SRTMGL1_003"
_JRC_DATASET     = "JRC/GSW1_4/GlobalSurfaceWater"

# Sample every ~0.1° (~11 km, matching GPM resolution) for speed
_SAMPLE_STEP_DEG = 0.09


def _make_grid(lat_min, lon_min, lat_max, lon_max) -> list[tuple[float, float]]:
    lats = list(np.arange(lat_min, lat_max, _SAMPLE_STEP_DEG))
    lons = list(np.arange(lon_min, lon_max, _SAMPLE_STEP_DEG))
    # Ensure at least a 2×2 grid for small city bboxes
    if len(lats) < 2:
        mid_lat = (lat_min + lat_max) / 2
        lats = [lat_min, mid_lat, lat_max]
    if len(lons) < 2:
        mid_lon = (lon_min + lon_max) / 2
        lons = [lon_min, mid_lon, lon_max]
    return [(round(lat, 6), round(lon, 6)) for lat in lats for lon in lons]


def _flood_risk(
    precip_3h: Optional[float],
    elev_m: Optional[float],
    jrc_occ: Optional[float],
) -> Optional[float]:
    rain_score    = float(np.clip((precip_3h or 0) / 50.0, 0.0, 1.0))
    terrain_score = float(np.clip(1.0 - (elev_m or 50) / 100.0, 0.0, 1.0)) if elev_m is not None else 0.3
    water_score   = float(np.clip((jrc_occ or 0) / 100.0, 0.0, 1.0))
    return round(0.5 * rain_score + 0.3 * terrain_score + 0.2 * water_score, 4)


def fetch_rainfall_observations(
    city_name: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    lookback_hours: int = 3,
    project: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch precipitation + terrain data from GEE for a city bounding box.

    Returns a DataFrame with columns matching the flood pipeline's
    rainfall_observation_feed contract. Falls back to empty DataFrame on
    any GEE error so the pipeline can continue with a synthetic fallback.

    Parameters
    ----------
    city_name : str
        Used for logging.
    lat_min, lon_min, lat_max, lon_max : float
        City bounding box.
    lookback_hours : int
        Accumulation window for precipitation (default 3h).
    project : str, optional
        GEE cloud project ID.
    """
    empty = pd.DataFrame(columns=_COLUMNS)

    try:
        import ee
    except ImportError:
        logger.error("earthengine-api not installed — pip install earthengine-api")
        return empty

    try:
        try:
            ee.Initialize(project=project)
        except Exception:
            ee.Initialize()
    except Exception as exc:
        logger.error("GEE authentication failed: %s", exc)
        return empty

    end_dt    = datetime.now(timezone.utc)
    start_dt  = end_dt - timedelta(hours=lookback_hours)
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:00")
    end_str   = end_dt.strftime("%Y-%m-%dT%H:%M:00")
    ts_label  = end_dt.strftime("%Y-%m-%dT%H:00:00Z")

    bbox = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

    # ── GPM IMERG precipitation sum over lookback window ──────────────────
    try:
        gpm = (
            ee.ImageCollection(_GPM_COLLECTION)
            .filterDate(start_str, end_str)
            .filterBounds(bbox)
            .select("precipitation")
            # GPM gives mm/hr; sum over 30-min images → multiply by 0.5 each
            .map(lambda img: img.multiply(0.5))
            .sum()
            .rename("precip_3h_mm")
        )
        gpm_intensity = (
            ee.ImageCollection(_GPM_COLLECTION)
            .filterDate(start_str, end_str)
            .filterBounds(bbox)
            .select("precipitation")
            .mean()
            .rename("precip_intensity")
        )
    except Exception as exc:
        logger.error("GEE GPM image build failed: %s", exc)
        return empty

    # ── SRTM elevation ────────────────────────────────────────────────────
    try:
        srtm = ee.Image(_SRTM_DATASET).select("elevation").rename("elevation_m")
    except Exception as exc:
        logger.warning("GEE SRTM load failed (continuing without): %s", exc)
        srtm = None

    # ── JRC surface water occurrence ──────────────────────────────────────
    try:
        jrc = ee.Image(_JRC_DATASET).select("occurrence").rename("jrc_occurrence")
    except Exception as exc:
        logger.warning("GEE JRC load failed (continuing without): %s", exc)
        jrc = None

    # ── Build combined image ───────────────────────────────────────────────
    combined = gpm.addBands(gpm_intensity)
    if srtm is not None:
        combined = combined.addBands(srtm)
    if jrc is not None:
        combined = combined.addBands(jrc)

    # ── Sample at grid points ─────────────────────────────────────────────
    points = _make_grid(lat_min, lon_min, lat_max, lon_max)

    try:
        fc = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([lon, lat]), {"lat": lat, "lon": lon})
            for lat, lon in points
        ])
        sampled  = combined.sampleRegions(
            collection=fc,
            scale=11000,    # ~11 km — matches GPM resolution
            geometries=True,
        )
        features = sampled.getInfo()["features"]
    except Exception as exc:
        logger.error("GEE sampling failed: %s", exc)
        return empty

    rows = []
    for feat in features:
        props     = feat.get("properties", {})
        lat       = props.get("lat")
        lon       = props.get("lon")
        precip_3h = props.get("precip_3h_mm")
        intensity = props.get("precip_intensity")
        elev_m    = props.get("elevation_m")
        jrc_occ   = props.get("jrc_occurrence")

        if lat is None or lon is None:
            continue

        rows.append({
            "station_id":                  f"gee_gpm_{round(lat, 3)}_{round(lon, 3)}",
            "latitude":                    lat,
            "longitude":                   lon,
            "timestamp":                   ts_label,
            "rainfall_intensity_mm_per_hr": round(intensity, 3) if intensity is not None else 0.0,
            "rainfall_accumulation_3h_mm":  round(precip_3h, 3) if precip_3h is not None else 0.0,
            "elevation_m":                 round(elev_m, 1) if elev_m is not None else None,
            "jrc_water_occurrence":        round(jrc_occ, 1) if jrc_occ is not None else None,
            "flood_risk_score":            _flood_risk(precip_3h, elev_m, jrc_occ),
            "data_source":                 "gee_gpm_srtm",
            "quality_flag":                "real",
        })

    if not rows:
        logger.warning("GEE flood: no samples returned for city '%s'", city_name)
        return empty

    df = pd.DataFrame(rows)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = None

    logger.info(
        "GEE flood: %d sample points for city '%s' (%.1f mm max 3h accumulation)",
        len(df), city_name,
        df["rainfall_accumulation_3h_mm"].max() or 0,
    )
    return df[_COLUMNS]
