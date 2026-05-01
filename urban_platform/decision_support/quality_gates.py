from __future__ import annotations

from typing import Any, Dict

import geopandas as gpd
import pandas as pd

from src.data_audit import audit_data_coverage as _legacy_audit


def run_quality_gates(
    *,
    grid_gdf: gpd.GeoDataFrame,
    aq_stations_hourly: pd.DataFrame,
    aq_panel: pd.DataFrame,
    model_dataset: pd.DataFrame,
    h3_resolution: int,
    quality_gates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply data audit + quality gates (provenance-aware).

    Migration note: delegates to legacy audit implementation.
    """
    return _legacy_audit(
        grid_gdf=grid_gdf,
        aq_stations_hourly=aq_stations_hourly,
        aq_panel=aq_panel,
        model_dataset=model_dataset,
        h3_resolution=h3_resolution,
        quality_gates=quality_gates,
    )

