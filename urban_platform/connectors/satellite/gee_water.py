"""Sentinel-2 water quality connector via Google Earth Engine.

Computes per-H3-cell water quality indices from Sentinel-2 SR:

  MNDWI  Modified NDWI          water body presence (> 0 = water)
  NDTI   Normalised Diff Turb.  suspended sediment / turbidity
  CI     Chlorophyll Index       algal bloom intensity (Red-Edge / Red)
  FAI    Floating Algae Index    surface scum / foam

Only cells where MNDWI > _WATER_THRESHOLD are considered water bodies.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_WATER_THRESHOLD = 0.0      # MNDWI above this → water pixel
_CLOUD_THRESHOLD = 30       # % cloud cover filter


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


def fetch_water_quality(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 10,
) -> dict[str, dict]:
    """Return {h3_id: water_quality_dict} for cells containing water bodies.

    Only h3_cells where the median MNDWI > _WATER_THRESHOLD are returned.
    Quality dict keys: mndwi, ndti, ci, fai, water_quality_index (0-1, higher=worse).
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping water quality fetch")
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
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _CLOUD_THRESHOLD))
            .select(["B3", "B4", "B5", "B8", "B11"])
            .median()
        )

        # Scale reflectance: Sentinel-2 SR values are 0-10000
        s2_scaled = s2.divide(10000)

        # ── Indices ───────────────────────────────────────────────────────
        # MNDWI = (Green - SWIR1) / (Green + SWIR1)
        mndwi = s2_scaled.normalizedDifference(["B3", "B11"]).rename("mndwi")

        # NDTI = (Red - Green) / (Red + Green)  — turbidity proxy
        ndti = s2_scaled.normalizedDifference(["B4", "B3"]).rename("ndti")

        # CI = Red-Edge / Red — chlorophyll proxy (algal bloom)
        ci = s2_scaled.select("B5").divide(s2_scaled.select("B4")).rename("ci")

        # FAI = B8 - [B4 + (B11-B4)*((833-665)/(1610-665))]
        slope = (833 - 665) / (1610 - 665)
        fai = (
            s2_scaled.select("B8")
            .subtract(
                s2_scaled.select("B4").add(
                    s2_scaled.select("B11")
                    .subtract(s2_scaled.select("B4"))
                    .multiply(slope)
                )
            )
            .rename("fai")
        )

        composite = mndwi.addBands([ndti, ci, fai])

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
            props = feat.get("properties", {})
            h3_id = props.get("h3_id")
            mndwi_val = props.get("mndwi")

            if h3_id is None or mndwi_val is None:
                continue
            if float(mndwi_val) <= _WATER_THRESHOLD:
                continue  # not a water cell

            ndti_val = float(props.get("ndti") or 0)
            ci_val   = float(props.get("ci")   or 1)
            fai_val  = float(props.get("fai")  or 0)

            # Water Quality Index: 0 = clean, 1 = severely polluted
            # Normalise each signal into 0-1 then take weighted max
            turb_score = min(1.0, max(0.0, (ndti_val + 0.2) / 0.6))   # NDTI: -0.2 (clear) to 0.4 (very turbid)
            algal_score = min(1.0, max(0.0, (ci_val - 1.0) / 2.0))    # CI: 1=normal, 3=bloom
            foam_score  = min(1.0, max(0.0, fai_val / 0.05))          # FAI: 0=none, 0.05=scum

            wqi = max(turb_score * 0.4 + algal_score * 0.4 + foam_score * 0.2,
                      turb_score, algal_score, foam_score * 0.8)
            wqi = round(min(1.0, wqi), 4)

            result[h3_id] = {
                "mndwi":               round(float(mndwi_val), 4),
                "ndti":                round(ndti_val, 4),
                "ci":                  round(ci_val, 4),
                "fai":                 round(fai_val, 6),
                "water_quality_index": wqi,
                "turbidity_score":     round(turb_score, 3),
                "algal_score":         round(algal_score, 3),
                "foam_score":          round(foam_score, 3),
            }

        logger.info("Sentinel-2 water quality: %d water cells found", len(result))
        return result

    except Exception as exc:
        logger.warning("Water quality fetch failed: %s", exc)
        return {}
