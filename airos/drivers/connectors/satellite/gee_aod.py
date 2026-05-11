"""MODIS MAIAC Aerosol Optical Depth (AOD) connector via Google Earth Engine."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_PRODUCT = "MODIS/061/MCD19A2_GRANULES"
_BAND = "Optical_Depth_055"
_SCALE_FACTOR = 0.001  # MODIS AOD stored as int * 1000


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


def fetch_aod_for_cells(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 3,
) -> dict[str, float]:
    """Return dict mapping h3_id → AOD value (550 nm) for each cell.

    Uses MODIS MAIAC MCD19A2 product. Falls back to empty dict on any error.
    Lookback is 3 days by default because MAIAC NRT has ~1-2 day latency.
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping MODIS AOD")
        return {}

    try:
        import ee
        import h3

        _gee_init(project)

        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=lookback_days)
        start    = start_dt.strftime("%Y-%m-%d")
        end      = end_dt.strftime("%Y-%m-%d")

        region = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

        image = (
            ee.ImageCollection(_PRODUCT)
            .filterDate(start, end)
            .filterBounds(region)
            .select(_BAND)
            .mean()
            .multiply(_SCALE_FACTOR)
        )

        # Build sample points from H3 cell centres
        points = []
        for cell in h3_cells:
            lat, lon = h3.cell_to_latlng(cell)
            points.append(ee.Feature(ee.Geometry.Point([lon, lat]), {"h3_id": cell}))
        fc = ee.FeatureCollection(points)

        sampled = image.sampleRegions(
            collection=fc,
            scale=1000,
            geometries=False,
            tileScale=4,
        )
        rows = sampled.getInfo().get("features", [])
        result: dict[str, float] = {}
        for feat in rows:
            props = feat.get("properties", {})
            h3_id = props.get("h3_id")
            aod   = props.get(_BAND)
            if h3_id and aod is not None:
                result[h3_id] = round(float(aod), 4)

        logger.info("MODIS AOD: sampled %d / %d cells", len(result), len(h3_cells))
        return result

    except Exception as exc:
        logger.warning("MODIS AOD fetch failed: %s", exc)
        return {}
