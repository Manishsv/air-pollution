"""GEE connectors for waste site detection signals.

Provides two signals per H3 cell:
  NDVI  — Sentinel-2 SR. NDVI < 0.15 in urban context = likely exposed waste/dump.
  CH4   — Sentinel-5P TROPOMI. Elevation above ~1880 ppb background = landfill gas.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Sentinel-5P CH4 background for South Asia (ppb)
_CH4_BACKGROUND_PPB = 1880.0


def _gee_init(project: str | None) -> None:
    import ee
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    sa_email = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
    if key_file and sa_email:
        creds = ee.ServiceAccountCredentials(email=sa_email, key_file=key_file)
        ee.Initialize(credentials=creds, project=project)
    else:
        try:
            ee.Initialize(project=project)
        except Exception:
            ee.Initialize()


def fetch_ndvi_for_cells(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 10,
) -> dict[str, float]:
    """Return {h3_id: ndvi} using Sentinel-2 SR median composite.

    NDVI < 0.1  → bare soil / exposed debris (candidate dump site)
    NDVI 0.1–0.2 → sparse vegetation / degraded surface
    NDVI > 0.3  → healthy vegetation (unlikely dump)
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping NDVI fetch")
        return {}

    try:
        import ee
        import h3

        _gee_init(project)

        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=lookback_days)
        region   = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

        s2 = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            .filterBounds(region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
            .select(["B4", "B8"])
            .median()
        )
        ndvi_img = s2.normalizedDifference(["B8", "B4"]).rename("ndvi")

        points = [
            ee.Feature(ee.Geometry.Point([h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]]), {"h3_id": c})
            for c in h3_cells
        ]
        sampled = ndvi_img.sampleRegions(
            collection=ee.FeatureCollection(points),
            scale=10,
            geometries=False,
            tileScale=4,
        )
        result: dict[str, float] = {}
        for feat in sampled.getInfo().get("features", []):
            props = feat.get("properties", {})
            h3_id = props.get("h3_id")
            val   = props.get("ndvi")
            if h3_id and val is not None:
                result[h3_id] = round(float(val), 4)

        logger.info("Sentinel-2 NDVI: sampled %d / %d cells", len(result), len(h3_cells))
        return result

    except Exception as exc:
        logger.warning("NDVI fetch failed: %s", exc)
        return {}


def fetch_ch4_for_cells(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 10,
) -> dict[str, float]:
    """Return {h3_id: ch4_ppb} using Sentinel-5P TROPOMI.

    Values are column-averaged dry-air mixing ratio (ppb).
    Elevation above _CH4_BACKGROUND_PPB signals landfill gas or agricultural emissions.
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping CH4 fetch")
        return {}

    try:
        import ee
        import h3

        _gee_init(project)

        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=lookback_days)
        region   = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

        ch4_img = (
            ee.ImageCollection("COPERNICUS/S5P/NRTI/L3_CH4")
            .filterDate(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            .filterBounds(region)
            .select("CH4_column_volume_mixing_ratio_dry_air")
            .mean()
        )

        points = [
            ee.Feature(ee.Geometry.Point([h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]]), {"h3_id": c})
            for c in h3_cells
        ]
        sampled = ch4_img.sampleRegions(
            collection=ee.FeatureCollection(points),
            scale=7000,
            geometries=False,
            tileScale=4,
        )
        result: dict[str, float] = {}
        for feat in sampled.getInfo().get("features", []):
            props = feat.get("properties", {})
            h3_id = props.get("h3_id")
            val   = props.get("CH4_column_volume_mixing_ratio_dry_air")
            if h3_id and val is not None:
                result[h3_id] = round(float(val), 2)

        logger.info("Sentinel-5P CH4: sampled %d / %d cells", len(result), len(h3_cells))
        return result

    except Exception as exc:
        logger.warning("CH4 fetch failed: %s", exc)
        return {}
