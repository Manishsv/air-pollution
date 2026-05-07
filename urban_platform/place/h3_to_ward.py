"""Spatial join: assign each H3 cell to a ward via centroid point-in-polygon."""
from __future__ import annotations

import logging
from typing import List

import h3
import pandas as pd
from shapely.geometry import Point, Polygon

from .schema import Ward

logger = logging.getLogger(__name__)


def assign_wards(cells_df: pd.DataFrame, wards: List[Ward]) -> pd.DataFrame:
    """Add a ``ward_id`` and ``ward_name`` column to cells_df.

    Uses the H3 cell centroid and tests which ward polygon contains it.
    Cells that fall outside all wards (edge effects) get ward_id="unassigned".

    Parameters
    ----------
    cells_df : DataFrame with an ``h3_id`` column.
    wards : List of Ward objects with polygon coordinates.

    Returns
    -------
    DataFrame with two new columns: ward_id, ward_name.
    """
    if cells_df.empty or not wards:
        result = cells_df.copy()
        result["ward_id"] = "unassigned"
        result["ward_name"] = "Unassigned"
        return result

    # Build shapely polygons once
    polys = [(w.ward_id, w.name, Polygon(w.coordinates)) for w in wards]

    def _find_ward(h3_id: str) -> tuple[str, str]:
        try:
            lat, lon = h3.cell_to_latlng(h3_id)
            pt = Point(lon, lat)  # shapely uses (x=lon, y=lat)
            for ward_id, ward_name, poly in polys:
                if poly.contains(pt):
                    return ward_id, ward_name
        except Exception:
            pass
        return "unassigned", "Unassigned"

    results = cells_df["h3_id"].apply(_find_ward)
    out = cells_df.copy()
    out["ward_id"] = [r[0] for r in results]
    out["ward_name"] = [r[1] for r in results]
    return out
