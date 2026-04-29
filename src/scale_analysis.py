from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def analyze_h3_resolution(grid_gdf, aq_stations_df) -> Dict[str, Any]:
    """
    Lightweight scale diagnostic for honest messaging:
    compares station density vs grid density for the chosen H3 resolution.
    """
    number_of_cells = int(getattr(grid_gdf, "shape", [0])[0])
    avg_cell_area_sqkm = float(pd.to_numeric(grid_gdf.get("area_sqkm"), errors="coerce").mean()) if number_of_cells else float("nan")

    st = aq_stations_df.copy()
    if "data_source" in st.columns:
        st["aq_station_source_type"] = np.where(st["data_source"].astype(str).str.contains("synthetic"), "synthetic", "real")
    else:
        st["aq_station_source_type"] = "unavailable"
    number_of_real_stations = int(st[st["aq_station_source_type"] == "real"]["station_id"].nunique()) if "station_id" in st.columns else 0

    total_area_sqkm = float(avg_cell_area_sqkm * number_of_cells) if np.isfinite(avg_cell_area_sqkm) else float("nan")
    station_density_per_100_sqkm = float((number_of_real_stations / total_area_sqkm) * 100.0) if total_area_sqkm and number_of_real_stations else 0.0
    avg_cells_per_station = float(number_of_cells / number_of_real_stations) if number_of_real_stations else float("inf")

    resolution_warning = ""
    if number_of_real_stations < 3:
        resolution_warning = "Station coverage extremely sparse for this grid; consider coarser H3 resolution or larger bbox."
    elif avg_cells_per_station > 50:
        resolution_warning = "Many grid cells per station; interpolation dominates. Consider coarser H3 resolution."

    return {
        "h3_resolution": int(getattr(grid_gdf, "h3_resolution", None) or -1),
        "avg_cell_area_sqkm": avg_cell_area_sqkm,
        "number_of_cells": number_of_cells,
        "number_of_real_stations": number_of_real_stations,
        "station_density_per_100_sqkm": station_density_per_100_sqkm,
        "avg_cells_per_station": avg_cells_per_station,
        "resolution_warning": resolution_warning,
    }

