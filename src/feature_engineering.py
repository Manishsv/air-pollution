from __future__ import annotations

import logging
from typing import Dict, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


def _ensure_local_crs(gdf: gpd.GeoDataFrame, local_crs: str) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=local_crs)
    if gdf.crs is None:
        raise ValueError("GeoDataFrame is missing CRS.")
    return gdf.to_crs(local_crs)


def build_static_features(
    h3_grid_wgs84: gpd.GeoDataFrame,
    boundary_projected: gpd.GeoDataFrame,
    osm: Dict[str, gpd.GeoDataFrame],
    local_crs: str,
) -> gpd.GeoDataFrame:
    """
    Returns projected GeoDataFrame (local_crs) with per-cell static features.
    """
    cells = h3_grid_wgs84.to_crs(local_crs).copy()
    cells["cell_area_sqm"] = cells.geometry.area.astype(float)

    roads = _ensure_local_crs(osm.get("roads", gpd.GeoDataFrame()), local_crs)
    buildings = _ensure_local_crs(osm.get("buildings", gpd.GeoDataFrame()), local_crs)
    landuse = _ensure_local_crs(osm.get("landuse", gpd.GeoDataFrame()), local_crs)
    pois = _ensure_local_crs(osm.get("pois", gpd.GeoDataFrame()), local_crs)

    # Roads: total length and primary/secondary length within each cell
    cells["road_length_total_m"] = 0.0
    cells["primary_secondary_road_length_m"] = 0.0
    if not roads.empty:
        roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
        sj = gpd.sjoin(roads[["geometry", "highway_class"]], cells[["h3_id", "geometry"]], how="inner", predicate="intersects")
        if not sj.empty:
            sj = sj.rename(columns={"index_right": "cell_idx"}).reset_index(drop=True)
            # Clip and measure length
            clipped = []
            for _, row in sj.iterrows():
                cell_geom = cells.loc[row["cell_idx"], "geometry"]
                inter = row["geometry"].intersection(cell_geom)
                if inter.is_empty:
                    continue
                clipped.append((row["h3_id"], row.get("highway_class"), inter.length))
            if clipped:
                df = pd.DataFrame(clipped, columns=["h3_id", "highway_class", "len_m"])
                total = df.groupby("h3_id")["len_m"].sum()
                cells = cells.merge(total.rename("road_length_total_m"), on="h3_id", how="left", suffixes=("", "_y"))
                cells["road_length_total_m"] = cells["road_length_total_m_y"].fillna(0.0)
                cells = cells.drop(columns=["road_length_total_m_y"])

                pri_sec = df[df["highway_class"].isin({"primary", "secondary"})].groupby("h3_id")["len_m"].sum()
                cells = cells.merge(pri_sec.rename("primary_secondary_road_length_m"), on="h3_id", how="left", suffixes=("", "_y"))
                cells["primary_secondary_road_length_m"] = cells["primary_secondary_road_length_m_y"].fillna(0.0)
                cells = cells.drop(columns=["primary_secondary_road_length_m_y"])

    cells["road_density_km_per_sqkm"] = np.where(
        cells["cell_area_sqm"] > 0,
        (cells["road_length_total_m"] / 1000.0) / (cells["cell_area_sqm"] / 1e6),
        0.0,
    )

    # Buildings: count + total area within cell
    cells["building_count"] = 0
    cells["building_area_total_sqm"] = 0.0
    if not buildings.empty:
        b = buildings[buildings.geometry.notna() & ~buildings.geometry.is_empty].copy()
        # Ensure polygons; some buildings might be points
        b = b[b.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if not b.empty:
            b["b_area"] = b.geometry.area.astype(float)
            sj = gpd.sjoin(b[["geometry", "b_area"]], cells[["h3_id", "geometry"]], how="inner", predicate="intersects")
            if not sj.empty:
                # Clip to cell for more accurate built-up ratio
                clipped_area = []
                for idx, row in sj.iterrows():
                    cell_geom = cells.loc[row["index_right"], "geometry"]
                    inter = row["geometry"].intersection(cell_geom)
                    if inter.is_empty:
                        continue
                    clipped_area.append((row["h3_id"], inter.area))
                if clipped_area:
                    df = pd.DataFrame(clipped_area, columns=["h3_id", "area_sqm"])
                    area_sum = df.groupby("h3_id")["area_sqm"].sum()
                    count = df.groupby("h3_id").size()
                    cells = cells.merge(area_sum.rename("building_area_total_sqm"), on="h3_id", how="left", suffixes=("", "_y"))
                    cells["building_area_total_sqm"] = cells["building_area_total_sqm_y"].fillna(0.0)
                    cells = cells.drop(columns=["building_area_total_sqm_y"])
                    cells = cells.merge(count.rename("building_count"), on="h3_id", how="left", suffixes=("", "_y"))
                    cells["building_count"] = cells["building_count_y"].fillna(0).astype(int)
                    cells = cells.drop(columns=["building_count_y"])

    cells["built_up_ratio"] = np.where(
        cells["cell_area_sqm"] > 0,
        cells["building_area_total_sqm"] / cells["cell_area_sqm"],
        0.0,
    )

    # Landuse: area by category within each cell
    for col in [
        "industrial_landuse_area_sqm",
        "commercial_landuse_area_sqm",
        "residential_landuse_area_sqm",
        "green_area_sqm",
    ]:
        cells[col] = 0.0

    if not landuse.empty and "landuse" in landuse.columns:
        lu = landuse[landuse.geometry.notna() & ~landuse.geometry.is_empty].copy()
        lu = lu[lu.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if not lu.empty:
            sj = gpd.sjoin(lu[["geometry", "landuse"]], cells[["h3_id", "geometry"]], how="inner", predicate="intersects")
            if not sj.empty:
                clipped = []
                for _, row in sj.iterrows():
                    cell_geom = cells.loc[row["index_right"], "geometry"]
                    inter = row["geometry"].intersection(cell_geom)
                    if inter.is_empty:
                        continue
                    clipped.append((row["h3_id"], str(row["landuse"]), inter.area))
                if clipped:
                    df = pd.DataFrame(clipped, columns=["h3_id", "landuse", "area_sqm"])
                    cat = df.pivot_table(index="h3_id", columns="landuse", values="area_sqm", aggfunc="sum", fill_value=0.0)
                    if "industrial" in cat.columns:
                        s = cat["industrial"]
                        cells["industrial_landuse_area_sqm"] = cells["h3_id"].map(s).fillna(cells["industrial_landuse_area_sqm"])
                    if "commercial" in cat.columns:
                        s = cat["commercial"]
                        cells["commercial_landuse_area_sqm"] = cells["h3_id"].map(s).fillna(cells["commercial_landuse_area_sqm"])
                    if "residential" in cat.columns:
                        s = cat["residential"]
                        cells["residential_landuse_area_sqm"] = cells["h3_id"].map(s).fillna(cells["residential_landuse_area_sqm"])

                    green_cols = [c for c in ["forest", "grass", "recreation_ground", "cemetery"] if c in cat.columns]
                    if green_cols:
                        green = cat[green_cols].sum(axis=1)
                        cells["green_area_sqm"] = cells["h3_id"].map(green).fillna(cells["green_area_sqm"])

    for col in [
        "industrial_landuse_area_sqm",
        "commercial_landuse_area_sqm",
        "residential_landuse_area_sqm",
        "green_area_sqm",
    ]:
        cells[col] = cells[col].fillna(0.0).astype(float)

    # POIs: count within each cell
    cells["poi_count"] = 0
    if not pois.empty:
        p = pois[pois.geometry.notna() & ~pois.geometry.is_empty].copy()
        # Convert polygons/lines to centroids for counting
        p["geom_pt"] = p.geometry.centroid
        p2 = gpd.GeoDataFrame(p.drop(columns=["geometry"]), geometry=p["geom_pt"], crs=local_crs)
        sj = gpd.sjoin(p2[["geometry"]], cells[["h3_id", "geometry"]], how="inner", predicate="within")
        if not sj.empty:
            counts = sj.groupby("h3_id").size()
            cells = cells.merge(counts.rename("poi_count"), on="h3_id", how="left", suffixes=("", "_y"))
            cells["poi_count"] = cells["poi_count_y"].fillna(0).astype(int)
            cells = cells.drop(columns=["poi_count_y"])

    # Keep geometry in WGS84 for downstream folium (but return both via columns)
    cells_wgs84 = cells.to_crs("EPSG:4326")
    cells_wgs84["geometry_projected_wkt"] = cells.geometry.to_wkt()
    return cells_wgs84


def build_panel_dataset(
    *,
    h3_grid_wgs84: gpd.GeoDataFrame,
    static_features_wgs84: gpd.GeoDataFrame,
    aq_panel: pd.DataFrame,  # h3_id,timestamp,current_pm25, flags
    weather_hourly: pd.DataFrame,  # timestamp + met vars
    fire_panel: pd.DataFrame,  # h3_id,timestamp, fire vars
    forecast_horizon_hours: int,
) -> pd.DataFrame:
    """
    Output columns include dynamic lags and target pm25_t_plus_{h}.
    """
    df = aq_panel.merge(weather_hourly, on="timestamp", how="left")
    if fire_panel is not None and not fire_panel.empty:
        df = df.merge(fire_panel, on=["h3_id", "timestamp"], how="left")
    else:
        df["fire_count_nearby"] = 0
        df["distance_to_nearest_fire_km"] = np.nan

    static_cols = [
        "h3_id",
        "road_density_km_per_sqkm",
        "primary_secondary_road_length_m",
        "building_count",
        "built_up_ratio",
        "industrial_landuse_area_sqm",
        "commercial_landuse_area_sqm",
        "residential_landuse_area_sqm",
        "green_area_sqm",
        "poi_count",
        "area_sqkm",
        "centroid_lat",
        "centroid_lon",
    ]
    static_df = static_features_wgs84[static_cols].copy()
    df = df.merge(static_df, on="h3_id", how="left")

    df = df.sort_values(["h3_id", "timestamp"]).reset_index(drop=True)

    # Lags per cell
    for lag_h in [1, 3, 24]:
        df[f"pm25_lag_{lag_h}h"] = df.groupby("h3_id")["current_pm25"].shift(lag_h)

    # Time features
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["hour"] = ts.dt.hour.astype(int)
    df["day_of_week"] = ts.dt.dayofweek.astype(int)
    df["month"] = ts.dt.month.astype(int)

    # Target
    h = int(forecast_horizon_hours)
    df[f"pm25_t_plus_{h}h"] = df.groupby("h3_id")["current_pm25"].shift(-h)

    # Minimal cleanup
    df = df.rename(columns={"current_pm25": "current_pm25"})
    return df

