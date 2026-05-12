"""Shared helpers for CDSE Sentinel Hub Process API connectors.

All CDSE connectors share the same three-step pattern:
  1. get_token()        — OAuth2 client_credentials
  2. fetch_tiff()       — POST to Process API → GeoTIFF bytes in memory
  3. sample_tiff()      — rasterio point sampling at H3 cell centroids

Each connector provides only the evalscript and data_config specific to its domain.
"""
from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

_TOKEN_URL   = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"


def get_credentials() -> tuple[str, str] | None:
    """Return (client_id, client_secret) from env, or None if not configured."""
    cid = os.environ.get("CDSE_CLIENT_ID",     "").strip()
    sec = os.environ.get("CDSE_CLIENT_SECRET", "").strip()
    if cid and sec:
        return cid, sec
    return None


def get_token(client_id: str, client_secret: str) -> str:
    """Obtain a short-lived Bearer token via OAuth2 client_credentials."""
    import requests

    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_tiff(
    token: str,
    bbox: list[float],
    data_config: dict,
    evalscript: str,
    px: int = 512,
) -> bytes | None:
    """POST to the Sentinel Hub Process API and return raw GeoTIFF bytes.

    Parameters
    ----------
    token       : Bearer token from get_token()
    bbox        : [lon_min, lat_min, lon_max, lat_max]
    data_config : dict with keys "type" and "dataFilter" for input.data[0]
    evalscript  : JavaScript evalscript string
    px          : output image size (square); use smaller values for coarse data (e.g. S5P)
    """
    import requests

    body = {
        "input": {
            "bounds": {
                "bbox":       bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [data_config],
        },
        "output": {
            "width":  px,
            "height": px,
            "responses": [{
                "identifier": "default",
                "format":     {"type": "image/tiff"},
            }],
        },
        "evalscript": evalscript,
    }

    resp = requests.post(
        _PROCESS_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "Accept":        "image/tiff",
        },
        timeout=120,
    )

    if resp.status_code == 204:
        logger.debug("CDSE: 204 No Content for bbox %s", bbox)
        return None
    resp.raise_for_status()
    return resp.content


def sample_tiff(tiff_bytes: bytes, h3_cells: list[str]) -> dict[str, list[float]]:
    """Sample a GeoTIFF at H3 cell centroids.

    Returns {h3_id: [band1, band2, ...]} — cells where any band is NaN are dropped.
    """
    import h3 as _h3
    import rasterio
    from rasterio.io import MemoryFile

    coords = [(_h3.cell_to_latlng(c)[1], _h3.cell_to_latlng(c)[0]) for c in h3_cells]

    with MemoryFile(tiff_bytes) as mf, mf.open() as ds:
        sampled = list(ds.sample(coords))

    out: dict[str, list[float]] = {}
    for cell, vals in zip(h3_cells, sampled):
        fvals = [float(v) for v in vals]
        if any(np.isnan(v) for v in fvals):
            continue
        out[cell] = fvals
    return out
