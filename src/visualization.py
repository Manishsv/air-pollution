from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import folium
import geopandas as gpd
import pandas as pd


logger = logging.getLogger(__name__)


def _style_by_level(level: str) -> dict:
    colors = {
        "low": "#2ECC71",
        "moderate": "#F1C40F",
        "high": "#E67E22",
        "severe": "#E74C3C",
    }
    return {
        "fillColor": colors.get(level, "#95A5A6"),
        "color": "#2c3e50",
        "weight": 1,
        "fillOpacity": 0.55,
    }


def save_pm25_map(
    *,
    grid_geo: gpd.GeoDataFrame,
    data_df: pd.DataFrame,
    value_col: str,
    out_html: Path,
    title: str,
) -> None:
    g = grid_geo.to_crs("EPSG:4326").copy()
    df = data_df[["h3_id", value_col]].copy()
    g = g.merge(df, on="h3_id", how="left")

    center = [float(g["centroid_lat"].mean()), float(g["centroid_lon"].mean())]
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
    folium.LayerControl().add_to(m)

    vals = g[value_col].fillna(0).astype(float)
    vmin, vmax = float(vals.min()), float(vals.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    def color(v: float) -> str:
        # simple ramp green->red
        x = (v - vmin) / (vmax - vmin)
        x = max(0.0, min(1.0, x))
        # interpolate between green and red
        r = int(46 + x * (231 - 46))
        g_ = int(204 + x * (76 - 204))
        b = int(113 + x * (60 - 113))
        return f"#{r:02x}{g_:02x}{b:02x}"

    for _, row in g.iterrows():
        v = float(row.get(value_col) or 0.0)
        poly = row.geometry
        popup = folium.Popup(f"<b>{title}</b><br>h3_id: {row['h3_id']}<br>{value_col}: {v:.1f}", max_width=350)
        folium.GeoJson(
            poly.__geo_interface__,
            style_function=lambda *_args, c=color(v): {"fillColor": c, "color": "#34495e", "weight": 1, "fillOpacity": 0.55},
            popup=popup,
        ).add_to(m)

    out_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_html))


def save_hotspot_recommendations_map(
    *,
    grid_geo: gpd.GeoDataFrame,
    recs_df: pd.DataFrame,
    out_html: Path,
) -> None:
    g = grid_geo.to_crs("EPSG:4326").copy()
    keep = [
        "h3_id",
        "current_pm25",
        "forecast_pm25",
        "hotspot_level",
        "dominant_driver",
        "recommended_action",
    ]
    df = recs_df[keep].copy()
    g = g.merge(df, on="h3_id", how="left")

    center = [float(g["centroid_lat"].mean()), float(g["centroid_lon"].mean())]
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")

    for _, row in g.iterrows():
        lvl = str(row.get("hotspot_level") or "unknown")
        style = _style_by_level(lvl)
        popup_html = (
            f"<b>H3</b>: {row['h3_id']}<br>"
            f"<b>Current PM2.5</b>: {float(row.get('current_pm25') or 0):.1f}<br>"
            f"<b>Forecast PM2.5</b>: {float(row.get('forecast_pm25') or 0):.1f}<br>"
            f"<b>Hotspot</b>: {lvl}<br>"
            f"<b>Driver</b>: {row.get('dominant_driver')}<br>"
            f"<b>Action</b>: {row.get('recommended_action')}"
        )
        popup = folium.Popup(popup_html, max_width=450)
        folium.GeoJson(row.geometry.__geo_interface__, style_function=lambda *_a, s=style: s, popup=popup).add_to(m)

    out_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_html))

