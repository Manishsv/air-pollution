"""Sentinel-2 urban green cover change connector via Google Earth Engine.

Computes per-H3-cell vegetation indices and change detection:

  NDVI    (NIR − Red) / (NIR + Red)                      overall greenness
  EVI     2.5 × (NIR−Red) / (NIR + 6Red − 7.5Blue + 1)  canopy-sensitive index
  ΔNDVI   recent_NDVI − baseline_NDVI                    change magnitude

Change categories:
  significant_loss  ΔNDVI < −0.15
  moderate_loss     ΔNDVI −0.15 to −0.05
  stable            ΔNDVI −0.05 to 0.05
  gain              ΔNDVI > 0.05

Only cells with current NDVI > _VEG_THRESHOLD or |ΔNDVI| > _CHANGE_THRESHOLD
are returned — bare concrete is not useful here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_VEG_THRESHOLD    = 0.15   # minimum NDVI to include a cell
_CHANGE_THRESHOLD = 0.05   # minimum |ΔNDVI| to flag a change
_CLOUD_THRESHOLD  = 30     # % cloud cover filter


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


def fetch_green_cover(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    recent_days: int = 30,
    baseline_days: int = 365,
) -> dict[str, dict]:
    """Return {h3_id: green_cover_dict} for vegetated or changing cells.

    Dict keys: ndvi, evi, ndvi_baseline, ndvi_change, change_category,
               coverage_class, green_cover_change_index (−1 to 1).
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping green cover fetch")
        return {}

    try:
        import ee
        import h3

        _gee_init(project)

        now         = datetime.now(timezone.utc)
        recent_end  = now
        recent_start= now - timedelta(days=recent_days)
        base_start  = now - timedelta(days=baseline_days)
        base_end    = now - timedelta(days=recent_days)

        region = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

        def _s2_median(start: datetime, end: datetime) -> "ee.Image":
            return (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                .filterBounds(region)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _CLOUD_THRESHOLD))
                .select(["B2", "B4", "B8"])     # Blue, Red, NIR
                .median()
                .divide(10000)
            )

        recent_s2   = _s2_median(recent_start, recent_end)
        baseline_s2 = _s2_median(base_start, base_end)

        def _ndvi(img: "ee.Image") -> "ee.Image":
            return img.normalizedDifference(["B8", "B4"]).rename("ndvi")

        def _evi(img: "ee.Image") -> "ee.Image":
            nir  = img.select("B8")
            red  = img.select("B4")
            blue = img.select("B2")
            return (
                nir.subtract(red)
                .multiply(2.5)
                .divide(
                    nir.add(red.multiply(6))
                    .subtract(blue.multiply(7.5))
                    .add(1)
                )
                .rename("evi")
            )

        recent_ndvi   = _ndvi(recent_s2)
        recent_evi    = _evi(recent_s2)
        baseline_ndvi = _ndvi(baseline_s2)
        delta_ndvi    = recent_ndvi.subtract(baseline_ndvi).rename("delta_ndvi")

        composite = recent_ndvi.addBands([recent_evi, baseline_ndvi, delta_ndvi])

        points = [
            ee.Feature(
                ee.Geometry.Point([h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]]),
                {"h3_id": c},
            )
            for c in h3_cells
        ]
        sampled = composite.sampleRegions(
            collection=ee.FeatureCollection(points),
            scale=10,
            geometries=False,
            tileScale=4,
        )

        result: dict[str, dict] = {}
        for feat in sampled.getInfo().get("features", []):
            props      = feat.get("properties", {})
            h3_id      = props.get("h3_id")
            ndvi_val   = props.get("ndvi")
            if h3_id is None or ndvi_val is None:
                continue

            ndvi_f     = float(ndvi_val)
            evi_f      = float(props.get("evi") or 0)
            baseline_f = float(props.get("ndvi_baseline") or ndvi_f)
            delta_f    = float(props.get("delta_ndvi") or 0)

            # Filter: only include if vegetated or meaningfully changing
            if ndvi_f < _VEG_THRESHOLD and abs(delta_f) < _CHANGE_THRESHOLD:
                continue

            # Coverage class from current NDVI
            if ndvi_f >= 0.6:
                coverage = "dense"
            elif ndvi_f >= 0.4:
                coverage = "moderate"
            elif ndvi_f >= 0.2:
                coverage = "sparse"
            else:
                coverage = "bare"

            # Change category from delta
            if delta_f < -0.15:
                change_cat = "significant_loss"
            elif delta_f < -0.05:
                change_cat = "moderate_loss"
            elif delta_f > 0.05:
                change_cat = "gain"
            else:
                change_cat = "stable"

            # GCCI: negative = loss, positive = gain, scaled −1 to 1
            gcci = round(max(-1.0, min(1.0, delta_f * 4)), 4)

            result[h3_id] = {
                "ndvi":                      round(ndvi_f, 4),
                "evi":                       round(evi_f, 4),
                "ndvi_baseline":             round(baseline_f, 4),
                "ndvi_change":               round(delta_f, 4),
                "change_category":           change_cat,
                "coverage_class":            coverage,
                "green_cover_change_index":  gcci,
            }

        logger.info("Green cover: %d vegetated cells, %d with change",
                    len(result),
                    sum(1 for v in result.values() if v["change_category"] != "stable"))
        return result

    except Exception as exc:
        logger.warning("Green cover fetch failed: %s", exc)
        return {}
