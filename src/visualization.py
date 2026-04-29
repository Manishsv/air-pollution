from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

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

def _warning_panel_html(audit: Optional[Dict]) -> str:
    if not audit:
        return ""
    synth_pct = float(audit.get("percent_cells_synthetic", 0.0) or 0.0)
    interp_pct = float(audit.get("percent_cells_interpolated", 0.0) or 0.0)
    real_st = int(audit.get("number_of_real_aq_stations", 0) or 0)
    allowed = bool(audit.get("recommendation_allowed", True))
    block_reason = str(audit.get("recommendation_block_reason", "") or "")

    lines = []
    if synth_pct > 0:
        lines.append("<b style='font-size:16px;color:#c0392b'>WARNING: Synthetic AQ data used.</b><br>")
        lines.append("This map is for pipeline testing only. Do not use for decisions.<br>")
    elif interp_pct >= 70:
        lines.append("<b style='font-size:15px;color:#d35400'>CAUTION: Most PM2.5 values are interpolated.</b><br>")
        lines.append("Interpret as indicative only under sparse station coverage.<br>")
    if real_st < 3:
        lines.append("<b style='font-size:15px;color:#7f8c8d'>LOW CONFIDENCE: insufficient real AQ stations.</b><br>")
    if not allowed:
        lines.append(f"<b>Recommendations blocked:</b> {block_reason}<br>")

    if not lines:
        return ""

    return (
        "<div style=\"position: fixed; top: 10px; left: 10px; z-index: 9999; "
        "background: rgba(255,255,255,0.95); padding: 10px 12px; border: 2px solid #2c3e50; "
        "border-radius: 6px; max-width: 420px; font-size: 12px;\">"
        + "".join(lines)
        + "</div>"
    )


def _legend_html() -> str:
    return (
        "<div style=\"position: fixed; bottom: 20px; left: 10px; z-index: 9999; "
        "background: rgba(255,255,255,0.95); padding: 10px 12px; border: 2px solid #2c3e50; "
        "border-radius: 6px; max-width: 320px; font-size: 12px;\">"
        "<b>Legend</b><br>"
        "<span style='display:inline-block;width:10px;height:10px;background:#27ae60;margin-right:6px;'></span>Real AQ<br>"
        "<span style='display:inline-block;width:10px;height:10px;background:#f1c40f;margin-right:6px;'></span>Interpolated AQ<br>"
        "<span style='display:inline-block;width:10px;height:10px;background:#c0392b;margin-right:6px;'></span>Synthetic AQ<br>"
        "<span style='display:inline-block;width:10px;height:10px;border:2px dashed #7f8c8d;margin-right:6px;'></span>Low confidence cell<br>"
        "</div>"
    )


def save_pm25_map(
    *,
    grid_geo: gpd.GeoDataFrame,
    data_df: pd.DataFrame,
    value_col: str,
    out_html: Path,
    title: str,
    audit: Optional[Dict] = None,
) -> None:
    g = grid_geo.to_crs("EPSG:4326").copy()
    desired = ["h3_id", value_col, "aq_source_type", "weather_source_type", "fire_source_type", "nearest_station_distance_km", "data_quality_score", "warning_flags"]
    keep = [c for c in desired if c in data_df.columns]
    df = data_df[keep].copy()
    g = g.merge(df, on="h3_id", how="left")

    center = [float(g["centroid_lat"].mean()), float(g["centroid_lon"].mean())]
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
    folium.LayerControl().add_to(m)

    # Warning + legend panels
    wp = _warning_panel_html(audit)
    if wp:
        m.get_root().html.add_child(folium.Element(wp))
    m.get_root().html.add_child(folium.Element(_legend_html()))

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
        popup_html = (
            f"<b>{title}</b><br>"
            f"<b>h3_id</b>: {row['h3_id']}<br>"
            f"<b>{value_col}</b>: {v:.1f}<br>"
            f"<b>aq_source_type</b>: {row.get('aq_source_type')}<br>"
            f"<b>weather_source_type</b>: {row.get('weather_source_type')}<br>"
            f"<b>fire_source_type</b>: {row.get('fire_source_type')}<br>"
            f"<b>nearest_station_distance_km</b>: {float(row.get('nearest_station_distance_km') or 0):.2f}<br>"
            f"<b>data_quality_score</b>: {float(row.get('data_quality_score') or 0):.2f}<br>"
            f"<b>warning_flags</b>: {row.get('warning_flags')}"
        )
        popup = folium.Popup(popup_html, max_width=450)

        aqst = str(row.get("aq_source_type") or "").lower()
        if aqst == "real":
            fill = "#27ae60"
        elif aqst == "synthetic":
            fill = "#c0392b"
        else:
            fill = "#f1c40f"
        low_conf = float(row.get("data_quality_score") or 0) < 0.5
        style = {"fillColor": fill, "color": "#7f8c8d" if low_conf else "#34495e", "weight": 2 if low_conf else 1, "fillOpacity": 0.55}
        folium.GeoJson(
            poly.__geo_interface__,
            style_function=lambda *_args, s=style: s,
            popup=popup,
        ).add_to(m)

    out_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_html))


def save_hotspot_recommendations_map(
    *,
    grid_geo: gpd.GeoDataFrame,
    recs_df: pd.DataFrame,
    out_html: Path,
    audit: Optional[Dict] = None,
) -> None:
    g = grid_geo.to_crs("EPSG:4326").copy()
    desired = [
        "h3_id",
        "current_pm25",
        "aq_source_type",
        "forecast_pm25_mean",
        "forecast_pm25_p10",
        "forecast_pm25_p50",
        "forecast_pm25_p90",
        "forecast_pm25_std",
        "pm25_category_india",
        "uncertainty_band",
        "data_quality_score",
        "recommendation_allowed",
        "recommendation_block_reason",
        "likely_contributing_factors",
        "driver_confidence",
        "driver_method",
        "recommended_action",
        "warning_flags",
        "nearest_station_distance_km",
        "interpolation_method",
        "station_count_used",
        "weather_source_type",
        "fire_source_type",
    ]
    keep = [c for c in desired if c in recs_df.columns]
    df = recs_df[keep].copy()
    g = g.merge(df, on="h3_id", how="left")

    center = [float(g["centroid_lat"].mean()), float(g["centroid_lon"].mean())]
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
    wp = _warning_panel_html(audit)
    if wp:
        m.get_root().html.add_child(folium.Element(wp))
    m.get_root().html.add_child(folium.Element(_legend_html()))

    for _, row in g.iterrows():
        lvl = str(row.get("pm25_category_india") or "unknown")
        # reuse style mapping; unknown gets gray
        style = _style_by_level("severe" if lvl == "severe" else "high" if lvl in {"very_poor", "poor"} else "moderate" if lvl in {"moderate"} else "low")
        popup_html = (
            f"<b>H3</b>: {row['h3_id']}<br>"
            f"<b>Current PM2.5</b>: {float(row.get('current_pm25') or 0):.1f}<br>"
            f"<b>AQ source</b>: {row.get('aq_source_type')}<br>"
            f"<b>Forecast mean</b>: {float(row.get('forecast_pm25_mean') or 0):.1f}<br>"
            f"<b>P10/P50/P90</b>: {float(row.get('forecast_pm25_p10') or 0):.1f} / {float(row.get('forecast_pm25_p50') or 0):.1f} / {float(row.get('forecast_pm25_p90') or 0):.1f}<br>"
            f"<b>Std</b>: {float(row.get('forecast_pm25_std') or 0):.1f} | <b>Band</b>: {float(row.get('uncertainty_band') or 0):.1f}<br>"
            f"<b>PM2.5 category (India)</b>: {lvl}<br>"
            f"<b>Data quality</b>: {float(row.get('data_quality_score') or 0):.2f}<br>"
            f"<b>Likely contributing factors</b>: {row.get('likely_contributing_factors')}<br>"
            f"<b>Driver confidence/method</b>: {row.get('driver_confidence')} / {row.get('driver_method')}<br>"
            f"<b>Recommendation allowed</b>: {row.get('recommendation_allowed')}<br>"
            f"<b>Block reason</b>: {row.get('recommendation_block_reason')}<br>"
            f"<b>Recommended action</b>: {row.get('recommended_action')}<br>"
            f"<b>nearest_station_distance_km</b>: {float(row.get('nearest_station_distance_km') or 0):.2f}<br>"
            f"<b>station_count_used</b>: {row.get('station_count_used')}<br>"
            f"<b>interpolation_method</b>: {row.get('interpolation_method')}<br>"
            f"<b>warning_flags</b>: {row.get('warning_flags')}"
        )
        popup = folium.Popup(popup_html, max_width=450)
        folium.GeoJson(row.geometry.__geo_interface__, style_function=lambda *_a, s=style: s, popup=popup).add_to(m)

    out_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_html))

