"""Sentinel-2 urban green cover connector via Microsoft Planetary Computer.

Drop-in replacement for gee_green.py — same output schema, no GEE dependency.

Data source: Sentinel-2 L2A (surface reflectance) from the Planetary Computer
STAC catalog. Cloud-filtered median composite over two windows:
  recent   : last `recent_days` days   → current NDVI / EVI
  baseline : prior year same window    → reference NDVI for change detection

Indices computed:
  NDVI   (B08 − B04) / (B08 + B04)
  EVI    2.5 × (B08 − B04) / (B08 + 6·B04 − 7.5·B02 + 1)
  ΔNDVI  recent_ndvi − baseline_ndvi

Requires (pip install):
  planetary-computer  pystac-client  stackstac  rioxarray
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np

logger = logging.getLogger(__name__)

_VEG_THRESHOLD    = 0.15   # minimum NDVI to include a cell
_CHANGE_THRESHOLD = 0.05   # minimum |ΔNDVI| to flag a change
_CLOUD_THRESHOLD  = 30     # % cloud cover filter (scene-level)
_PC_CATALOG       = "https://planetarycomputer.microsoft.com/api/stac/v1"
_COLLECTION       = "sentinel-2-l2a"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _date_range(start: datetime, end: datetime) -> tuple[str, str]:
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _search_scenes(catalog, bbox: list[float], start: datetime, end: datetime):
    """Return signed STAC items for the bbox/window, cloud-filtered."""
    import planetary_computer as pc

    start_s, end_s = _date_range(start, end)
    items = catalog.search(
        collections=[_COLLECTION],
        bbox=bbox,
        datetime=f"{start_s}/{end_s}",
        query={"eo:cloud_cover": {"lt": _CLOUD_THRESHOLD}},
    ).item_collection()

    return pc.sign(items)


def _median_composite(items, bbox: list[float], bands: list[str]) -> "xr.DataArray | None":
    """Stack items into an xarray DataArray and return the spatial median."""
    import stackstac

    if not items:
        return None
    try:
        stack = stackstac.stack(
            items,
            assets=bands,
            bounds_latlon=bbox,
            resolution=20,          # 20 m — good balance of detail vs speed
            dtype="float32",
            fill_value=np.nan,
        )
        # Drop scenes where all bands are NaN (no-data tiles)
        stack = stack.where(stack != 0)
        return stack.median(dim="time", skipna=True)
    except Exception as exc:
        logger.warning("stackstac composite failed: %s", exc)
        return None


def _sample_at_centroids(
    composite: "xr.DataArray",
    h3_cells: list[str],
) -> dict[str, dict[str, float]]:
    """Sample the composite at each H3 cell centroid. Returns {h3_id: {band: value}}."""
    import h3

    out: dict[str, dict[str, float]] = {}
    for cell in h3_cells:
        lat, lon = h3.cell_to_latlng(cell)
        try:
            # nearest-pixel lookup — xarray uses (y=lat, x=lon) for geographic CRS
            pt = composite.sel(x=lon, y=lat, method="nearest")
            vals = {str(b): float(pt.sel(band=b).values) for b in composite.coords["band"].values}
            # skip if any band is NaN (cloud / no-data)
            if any(np.isnan(v) for v in vals.values()):
                continue
            out[cell] = vals
        except Exception:
            continue
    return out


def _compute_indices(b02: float, b04: float, b08: float) -> tuple[float, float]:
    """Return (ndvi, evi). Inputs are reflectance [0, 1]."""
    denom_ndvi = b08 + b04
    ndvi = (b08 - b04) / denom_ndvi if denom_ndvi else 0.0

    denom_evi = b08 + 6 * b04 - 7.5 * b02 + 1
    evi = 2.5 * (b08 - b04) / denom_evi if denom_evi else 0.0

    return round(float(np.clip(ndvi, -1, 1)), 4), round(float(np.clip(evi, -1, 1)), 4)


def _coverage_class(ndvi: float) -> str:
    if ndvi >= 0.6:  return "dense"
    if ndvi >= 0.4:  return "moderate"
    if ndvi >= 0.2:  return "sparse"
    return "bare"


def _change_category(delta: float) -> str:
    if delta < -0.15: return "significant_loss"
    if delta < -0.05: return "moderate_loss"
    if delta >  0.05: return "gain"
    return "stable"


# ---------------------------------------------------------------------------
# Public API  (same signature as gee_green.fetch_green_cover)
# ---------------------------------------------------------------------------

def fetch_green_cover(
    h3_cells: list[str],
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    project: str | None = None,   # unused — kept for signature compatibility
    recent_days: int = 30,
    baseline_days: int = 365,
) -> dict[str, dict]:
    """Return {h3_id: green_cover_dict} using Planetary Computer (no GEE required).

    Output dict keys per cell:
      ndvi, evi, ndvi_baseline, ndvi_change, change_category,
      coverage_class, green_cover_change_index
    """
    if not h3_cells:
        return {}

    try:
        import pystac_client
    except ImportError:
        logger.error(
            "pystac-client not installed. Run: "
            "pip install planetary-computer pystac-client stackstac rioxarray"
        )
        return {}

    bbox = [lon_min, lat_min, lon_max, lat_max]
    now  = datetime.now(timezone.utc)

    recent_end   = now
    recent_start = now - timedelta(days=recent_days)
    base_end     = now - timedelta(days=recent_days)
    base_start   = now - timedelta(days=baseline_days)

    bands = ["B02", "B04", "B08"]   # Blue, Red, NIR

    try:
        catalog = pystac_client.Client.open(
            _PC_CATALOG,
            modifier=__import__("planetary_computer").sign_inplace,
        )

        logger.debug("Searching Planetary Computer for recent S2 scenes …")
        recent_items   = _search_scenes(catalog, bbox, recent_start,   recent_end)
        baseline_items = _search_scenes(catalog, bbox, base_start,     base_end)

        logger.debug(
            "Found %d recent, %d baseline scenes",
            len(recent_items), len(baseline_items),
        )

        recent_comp   = _median_composite(recent_items,   bbox, bands)
        baseline_comp = _median_composite(baseline_items, bbox, bands)

        if recent_comp is None:
            logger.warning("Green cover: no usable recent scenes for bbox %s", bbox)
            return {}

        recent_vals   = _sample_at_centroids(recent_comp,   h3_cells)
        baseline_vals = _sample_at_centroids(baseline_comp, h3_cells) if baseline_comp is not None else {}

        result: dict[str, dict] = {}
        for h3_id, rv in recent_vals.items():
            b02 = rv.get("B02", 0) / 10000   # DN → reflectance [0,1]
            b04 = rv.get("B04", 0) / 10000
            b08 = rv.get("B08", 0) / 10000

            ndvi, evi = _compute_indices(b02, b04, b08)

            bv = baseline_vals.get(h3_id, {})
            if bv:
                b04_b = bv.get("B04", 0) / 10000
                b08_b = bv.get("B08", 0) / 10000
                denom = b08_b + b04_b
                ndvi_baseline = float(np.clip((b08_b - b04_b) / denom, -1, 1)) if denom else ndvi
            else:
                ndvi_baseline = ndvi   # no baseline → assume stable

            delta = round(ndvi - ndvi_baseline, 4)

            if ndvi < _VEG_THRESHOLD and abs(delta) < _CHANGE_THRESHOLD:
                continue

            gcci = round(float(np.clip(delta * 4, -1, 1)), 4)

            result[h3_id] = {
                "ndvi":                     ndvi,
                "evi":                      evi,
                "ndvi_baseline":            round(ndvi_baseline, 4),
                "ndvi_change":              delta,
                "change_category":          _change_category(delta),
                "coverage_class":           _coverage_class(ndvi),
                "green_cover_change_index": gcci,
            }

        logger.info(
            "Green cover (PC): %d vegetated cells, %d with change",
            len(result),
            sum(1 for v in result.values() if v["change_category"] != "stable"),
        )
        return result

    except Exception as exc:
        logger.warning("Green cover (Planetary Computer) failed: %s", exc)
        return {}
