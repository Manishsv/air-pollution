from __future__ import annotations

import pandas as pd


def register_h3_grid(grid_gdf) -> pd.DataFrame:
    """
    Minimal H3 spatial unit registry.
    """
    if grid_gdf is None or len(grid_gdf) == 0:
        return pd.DataFrame(columns=["spatial_unit_id", "spatial_unit_type"])
    df = grid_gdf[["h3_id"]].copy()
    df = df.rename(columns={"h3_id": "spatial_unit_id"})
    df["spatial_unit_type"] = "h3"
    return df

