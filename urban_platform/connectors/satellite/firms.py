"""NASA FIRMS VIIRS active fire connector."""
from __future__ import annotations

import io
import logging
import os

import pandas as pd

from urban_platform.common.cache import with_source_metadata

logger = logging.getLogger(__name__)

_FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_PRODUCTS = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]
_AIRSHED_BUFFER_DEG = 0.5  # ~50 km buffer beyond city bbox

# VIIRS confidence strings → numeric %
_CONF_MAP = {"l": 30, "n": 60, "h": 90}


def fetch_firms_fires(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    day_range: int = 1,
) -> pd.DataFrame:
    """Fetch VIIRS SNPP fire hotspots for city bbox + airshed buffer.

    Returns DataFrame with columns: latitude, longitude, frp,
    detection_confidence, acq_date, acq_time, satellite, within_bbox.
    Empty DataFrame when FIRMS_API_KEY is absent or fetch fails.
    """
    api_key = os.environ.get("FIRMS_API_KEY", "").strip()
    if not api_key:
        logger.debug("FIRMS_API_KEY not set — skipping fire hotspot fetch")
        return with_source_metadata(
            pd.DataFrame(),
            source="firms_viirs",
            retrieval_type="skipped",
            details={"note": "FIRMS_API_KEY not configured"},
        )

    # Expand bbox for airshed context (FIRMS area limit: 10×10 degrees)
    area = (
        f"{lon_min - _AIRSHED_BUFFER_DEG:.4f},"
        f"{lat_min - _AIRSHED_BUFFER_DEG:.4f},"
        f"{lon_max + _AIRSHED_BUFFER_DEG:.4f},"
        f"{lat_max + _AIRSHED_BUFFER_DEG:.4f}"
    )
    # Clamp day_range: NRT products support 1-10 days
    day_range = max(1, min(10, day_range))

    import requests
    df = pd.DataFrame()
    last_exc: Exception | None = None
    for product in _PRODUCTS:
        url = f"{_FIRMS_BASE}/{api_key}/{product}/{area}/{day_range}"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 400:
                logger.debug("FIRMS %s returned 400 — trying next product", product)
                continue
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            if not df.empty and "latitude" in df.columns:
                break
        except Exception as exc:
            last_exc = exc
            logger.debug("FIRMS %s failed: %s", product, exc)

    if df.empty and last_exc is not None:
        logger.warning("FIRMS fetch failed for all products: %s", last_exc)
        return with_source_metadata(
            pd.DataFrame(),
            source="firms_viirs",
            retrieval_type="error",
            details={"error": str(last_exc)},
        )

    if df.empty or "latitude" not in df.columns:
        return with_source_metadata(
            pd.DataFrame(),
            source="firms_viirs",
            retrieval_type="live",
            details={"count": 0},
        )

    # Normalise confidence: VIIRS returns 'l' / 'n' / 'h' strings
    if "confidence" in df.columns:
        df = df.rename(columns={"confidence": "detection_confidence"})
    if "detection_confidence" in df.columns and df["detection_confidence"].dtype == object:
        df["detection_confidence"] = df["detection_confidence"].map(
            lambda x: _CONF_MAP.get(str(x).lower(), 50)
        ).fillna(50).astype(int)

    df["within_bbox"] = (
        df["latitude"].between(lat_min, lat_max) &
        df["longitude"].between(lon_min, lon_max)
    )

    logger.info("FIRMS: %d fire detections (%d within city bbox)",
                len(df), df["within_bbox"].sum())
    return with_source_metadata(
        df,
        source="firms_viirs",
        retrieval_type="live",
        details={"count": len(df), "day_range": day_range},
    )
