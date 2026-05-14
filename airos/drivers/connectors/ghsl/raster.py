"""GHSL raster connector — windowed reads of JRC R2023A 100m tiles.

Two products are exposed:

* `BUILT_V` — built-up volume per pixel (m³), GHS_BUILT_V_E2020 R2023A
* `BUILT_S` — built-up surface per pixel (m²), GHS_BUILT_S_E2020 R2023A
* `POP`     — residential population per pixel (people), GHS_POP_E2020 R2023A

The global product is sharded into 10°×10° (Mollweide) tiles served as
zipped GeoTIFFs by JRC.  We open them remotely via /vsizip//vsicurl/
and pull only the pixels covering the requested bbox.

The connector returns per-pixel (lat, lon, value) sample lists.  The
ingestor bins these into H3 cells the same way the SRTM connector does
for elevation — no new aggregation primitive needed.

License: CC-BY 4.0 (Joint Research Centre, European Commission).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Tile bounds in WGS84 (probed once and pinned — see docs/INTELLIGENCE_METHODOLOGY.md
#    §D.13/§D.21 for the verification trace). Covers the six AirOS cities and most of India.
#    Add new rows here if we onboard a city outside these bounds.
_TILE_BOUNDS_WGS84: dict[tuple[int, int], tuple[float, float, float, float]] = {
    # (row, col): (lon_min, lat_min, lon_max, lat_max)
    (6, 26): (73.62685947, 24.55255376, 88.60144314, 33.06103686),  # north India (Delhi)
    (7, 25): (66.03570238, 20.38459096, 73.62685947, 24.55255376),  # west India (Gujarat)
    (7, 26): (71.20780024, 16.25916877, 84.20695136, 24.55255376),  # central India (Mumbai/Pune/Hyderabad)
    (7, 27): (81.44027621, 16.25916877, 94.78704325, 24.55255376),  # east India
    (8, 26): (70.86998062, 8.09801526,  81.44027621, 16.25916877),  # south India (Bangalore/Chennai)
}

# ── URL templates ───────────────────────────────────────────────────────────
_BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL"
_PRODUCT_META = {
    "BUILT_V": {
        "base_path": "GHS_BUILT_V_GLOBE_R2023A/GHS_BUILT_V_E2020_GLOBE_R2023A_54009_100/V1-0",
        "tile_stem": "GHS_BUILT_V_E2020_GLOBE_R2023A_54009_100_V1_0",
        "unit":      "m3",
    },
    "BUILT_S": {
        "base_path": "GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100/V1-0",
        "tile_stem": "GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100_V1_0",
        "unit":      "m2",
    },
    "POP": {
        "base_path": "GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0",
        "tile_stem": "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0",
        "unit":      "people",
    },
}


def _bbox_intersects(bbox: tuple[float, float, float, float],
                     tile_bbox: tuple[float, float, float, float]) -> bool:
    return not (
        bbox[2] < tile_bbox[0] or bbox[0] > tile_bbox[2]
        or bbox[3] < tile_bbox[1] or bbox[1] > tile_bbox[3]
    )


def _tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    return [rc for rc, tb in _TILE_BOUNDS_WGS84.items() if _bbox_intersects(bbox, tb)]


def _tile_url(product: str, row: int, col: int) -> str:
    meta = _PRODUCT_META[product]
    stem = f"{meta['tile_stem']}_R{row}_C{col}"
    return (
        f"/vsizip//vsicurl/{_BASE}/{meta['base_path']}/tiles/{stem}.zip/{stem}.tif"
    )


def _set_gdal_env() -> None:
    """Idempotently configure GDAL for /vsicurl reads — once per process."""
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("VSI_CACHE", "TRUE")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.zip")


def read_ghsl_samples(
    product: str,
    bbox_wgs84: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Read a GHSL product over `bbox_wgs84` and return per-pixel samples.

    Returns one dict per non-nodata pixel: {"lat", "lon", "value"}.
    The ingestor aggregates these into H3 cells.  Empty list on failure or
    if no GHSL tiles cover the bbox.
    """
    if product not in _PRODUCT_META:
        raise ValueError(f"Unknown GHSL product: {product}")

    _set_gdal_env()
    try:
        import rasterio
        from rasterio.windows import from_bounds
        from rasterio.warp import transform_bounds
        import numpy as np
        import pyproj
    except ImportError as e:  # pragma: no cover — rasterio is a hard dep
        logger.warning("GHSL connector: missing geo deps (%s) — returning []", e)
        return []

    tiles = _tiles_for_bbox(bbox_wgs84)
    if not tiles:
        logger.warning(
            "GHSL connector: bbox %s falls outside known tile index — "
            "extend _TILE_BOUNDS_WGS84 to support this region.", bbox_wgs84,
        )
        return []

    samples: list[dict[str, Any]] = []
    for (row, col) in tiles:
        url = _tile_url(product, row, col)
        logger.info("[ghsl/%s] Reading tile R%d_C%d window for %s",
                    product, row, col, bbox_wgs84)
        try:
            with rasterio.open(url) as src:
                l, b, r, t = transform_bounds(
                    "EPSG:4326", src.crs, *bbox_wgs84, densify_pts=21,
                )
                win = from_bounds(l, b, r, t, transform=src.transform)
                win = win.round_offsets().round_lengths()
                if win.width <= 0 or win.height <= 0:
                    continue
                data = src.read(1, window=win).astype("float64")
                win_transform = src.window_transform(win)
                nodata = src.nodata
                src_crs = src.crs

            # Build pixel-center coords in source CRS (vectorised)
            rows = np.arange(data.shape[0]) + 0.5
            cols = np.arange(data.shape[1]) + 0.5
            cc, rr = np.meshgrid(cols, rows)
            a, b_, c, d, e, f = (
                win_transform.a, win_transform.b, win_transform.c,
                win_transform.d, win_transform.e, win_transform.f,
            )
            xs = a * cc + b_ * rr + c
            ys = d * cc + e * rr + f

            # Mask nodata + non-positive pixels (we only care about populated)
            valid = data > 0
            if nodata is not None:
                valid &= data != nodata
            if not valid.any():
                continue

            xs_v, ys_v, vs_v = xs[valid], ys[valid], data[valid]

            # Mollweide → WGS84
            proj = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
            lon, lat = proj.transform(xs_v, ys_v)
            samples.extend(
                {"lat": float(la), "lon": float(lo), "value": float(v)}
                for la, lo, v in zip(lat, lon, vs_v)
            )
        except Exception as exc:
            logger.warning("[ghsl/%s] R%d_C%d read failed: %s",
                           product, row, col, exc)
            continue

    logger.info("[ghsl/%s] %d samples returned for bbox %s",
                product, len(samples), bbox_wgs84)
    return samples


def provenance(product: str) -> dict[str, str]:
    return {
        "source_id":   f"ghsl_{product.lower()}_e2020_r2023a",
        "source_type": "raster_100m_sampled",
        "license":     "CC-BY 4.0 (JRC, European Commission)",
        "url":         f"{_BASE}/{_PRODUCT_META[product]['base_path']}/",
    }
