"""Sentinel-2 + Sentinel-5P construction activity connector via Google Earth Engine.

Computes per-H3-cell construction activity indices:

  BSI    Bare Soil Index         ((SWIR1+Red) − (NIR+Blue)) / ((SWIR1+Red) + (NIR+Blue))
         > 0.05 → bare/disturbed soil; > 0.15 → active construction zone
  NDVI   Vegetation cover        distinguishes waste dumps (stable low) from active cuts
  NO2    Tropospheric column     Sentinel-5P TROPOMI mol/m² — machinery exhaust proxy
         > 8e-5 mol/m² → elevated; > 1.5e-4 → heavy construction/traffic

CRI (Construction Risk Index) = weighted combination of BSI + NO2 signals, 0-1.
Only cells with BSI > _BSI_THRESHOLD are flagged as construction candidates.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BSI_THRESHOLD    = 0.05     # minimum BSI to treat as bare/disturbed soil
_CLOUD_THRESHOLD  = 30       # % cloud cover for Sentinel-2 filter
_NO2_BACKGROUND   = 3.5e-5  # mol/m² — typical South Asian urban background
_NO2_MODERATE     = 8.0e-5  # mol/m² — elevated (construction + traffic)
_NO2_HIGH         = 1.5e-4  # mol/m² — heavily trafficked / dense construction


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


def fetch_construction_signals(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,
    lookback_days: int = 20,
) -> dict[str, dict]:
    """Return {h3_id: construction_signal_dict} for cells with BSI > _BSI_THRESHOLD.

    Signal dict keys:
      bsi, ndvi, no2_mol_m2, bsi_score, no2_score, construction_risk_index (0-1)
    """
    if not h3_cells:
        return {}

    project = project or os.environ.get("GEE_PROJECT", "").strip() or None
    if not project:
        logger.debug("GEE_PROJECT not set — skipping construction signals fetch")
        return {}

    try:
        import ee
        import h3

        _gee_init(project)

        end_dt   = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=lookback_days)
        region   = ee.Geometry.Rectangle([lon_min, lat_min, lon_max, lat_max])

        # ── Sentinel-2 SR — BSI + NDVI ────────────────────────────────────
        s2 = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterDate(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            .filterBounds(region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _CLOUD_THRESHOLD))
            .select(["B2", "B4", "B8", "B11"])   # Blue, Red, NIR, SWIR1
            .median()
            .divide(10000)                         # scale to 0-1 reflectance
        )

        # BSI = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))
        swir1_plus_red  = s2.select("B11").add(s2.select("B4"))
        nir_plus_blue   = s2.select("B8").add(s2.select("B2"))
        bsi = swir1_plus_red.subtract(nir_plus_blue).divide(
            swir1_plus_red.add(nir_plus_blue)
        ).rename("bsi")

        # NDVI = (NIR - Red) / (NIR + Red)
        ndvi = s2.normalizedDifference(["B8", "B4"]).rename("ndvi")

        s2_composite = bsi.addBands(ndvi)

        # ── Sentinel-5P TROPOMI NO2 ────────────────────────────────────────
        s5p_no2 = (
            ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_NO2")
            .filterDate(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            .filterBounds(region)
            .select(["NO2_column_number_density"])
            .median()
            .rename("no2")
        )

        # ── Sample at H3 centroids ─────────────────────────────────────────
        points = [
            ee.Feature(
                ee.Geometry.Point([h3.cell_to_latlng(c)[1], h3.cell_to_latlng(c)[0]]),
                {"h3_id": c},
            )
            for c in h3_cells
        ]
        fc = ee.FeatureCollection(points)

        s2_sampled = s2_composite.sampleRegions(
            collection=fc, scale=10, geometries=False, tileScale=4,
        )
        no2_sampled = s5p_no2.sampleRegions(
            collection=fc, scale=7000, geometries=False, tileScale=2,
        )

        # Build NO2 lookup by h3_id
        no2_by_cell: dict[str, float] = {}
        for feat in no2_sampled.getInfo().get("features", []):
            props  = feat.get("properties", {})
            h3_id  = props.get("h3_id")
            no2_v  = props.get("no2")
            if h3_id and no2_v is not None:
                no2_by_cell[h3_id] = float(no2_v)

        result: dict[str, dict] = {}
        for feat in s2_sampled.getInfo().get("features", []):
            props   = feat.get("properties", {})
            h3_id   = props.get("h3_id")
            bsi_val = props.get("bsi")

            if h3_id is None or bsi_val is None:
                continue
            bsi_f = float(bsi_val)
            if bsi_f <= _BSI_THRESHOLD:
                continue  # not a bare-soil / construction cell

            ndvi_f = float(props.get("ndvi") or 0)
            no2_f  = no2_by_cell.get(h3_id, _NO2_BACKGROUND)

            # Normalise scores 0-1
            # BSI: _BSI_THRESHOLD (0) → 0.5 (1)
            bsi_score = min(1.0, max(0.0, (bsi_f - _BSI_THRESHOLD) / (0.5 - _BSI_THRESHOLD)))

            # NO2: background (0) → _NO2_HIGH (1)
            no2_score = min(1.0, max(0.0,
                (no2_f - _NO2_BACKGROUND) / (_NO2_HIGH - _NO2_BACKGROUND)
            ))

            # CRI: weighted; NDVI suppresses score if vegetation still present
            # Low NDVI → multiplier near 1; high NDVI → dampens (likely trees, not construction)
            ndvi_factor = max(0.3, 1.0 - max(0.0, ndvi_f))
            cri = min(1.0, (bsi_score * 0.6 + no2_score * 0.4) * ndvi_factor)
            cri = round(cri, 4)

            result[h3_id] = {
                "bsi":                    round(bsi_f, 4),
                "ndvi":                   round(ndvi_f, 4),
                "no2_mol_m2":             round(no2_f, 8),
                "bsi_score":              round(bsi_score, 3),
                "no2_score":              round(no2_score, 3),
                "ndvi_factor":            round(ndvi_factor, 3),
                "construction_risk_index": cri,
            }

        logger.info("Construction signals: %d active cells detected", len(result))
        return result

    except Exception as exc:
        logger.warning("Construction signals fetch failed: %s", exc)
        return {}
