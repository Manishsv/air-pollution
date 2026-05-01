from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
import geopandas as gpd
import numpy as np
from branca.colormap import linear
import re


def _category_color(cat: str) -> list[int]:
    c = (cat or "").lower()
    if c in {"severe"}:
        return [231, 76, 60]
    if c in {"very_poor", "poor"}:
        return [230, 126, 34]
    if c in {"moderate"}:
        return [241, 196, 15]
    return [46, 204, 113]


def _rgb_to_hex(rgb: list[int]) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def _confidence_color(level: str) -> str:
    l = (level or "").strip().lower()
    if l == "high":
        return "#2ecc71"
    if l == "medium":
        return "#f1c40f"
    if l == "low":
        return "#e67e22"
    return "#95a5a6"


def _aq_source_color(aq_source_type: str) -> str:
    t = (aq_source_type or "").strip().lower()
    if t == "real":
        return "#27ae60"
    if t == "interpolated":
        return "#f1c40f"
    if t == "synthetic":
        return "#c0392b"
    return "#95a5a6"


def _sensor_reliability_color(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "healthy":
        return "#27ae60"
    if s == "degraded":
        return "#f39c12"
    if s == "suspect":
        return "#e74c3c"
    if s == "offline":
        return "#2c3e50"
    return "#95a5a6"


def prepare_layer_names(enabled: dict[str, bool]) -> list[str]:
    """
    Lightweight helper for tests: return the ordered layer names that would be created.
    """
    names: list[str] = []
    if enabled.get("areas", True):
        names.append("Areas needing review")
    if enabled.get("selected", True):
        names.append("Selected area")
    if enabled.get("uncertainty", False):
        names.append("Forecast uncertainty")
    if enabled.get("confidence", False):
        names.append("Confidence")
    if enabled.get("aq_sensors", True):
        names.append("AQ sensors")
    if enabled.get("observed_cells", False):
        names.append("Observed PM2.5 cells")
    if enabled.get("interpolated_cells", False):
        names.append("Interpolated PM2.5 cells")
    if enabled.get("synthetic_cells", False):
        names.append("Synthetic/test data cells")
    if enabled.get("road_density", False):
        names.append("Road density")
    if enabled.get("built_up_ratio", False):
        names.append("Built-up ratio")
    if enabled.get("green_area", False):
        names.append("Green area")
    if enabled.get("industrial_commercial", False):
        names.append("Industrial/commercial area")
    if enabled.get("sensor_reliability", False):
        names.append("Sensor reliability")
    if enabled.get("low_confidence_cells", False):
        names.append("Low-confidence cells")
    if enabled.get("high_uncertainty_cells", False):
        names.append("High-uncertainty cells")
    if enabled.get("sensor_siting", False):
        names.append("Suggested new sensor locations")
    return names


def _center_from_packets(packets: list[dict]) -> tuple[float, float]:
    df_cent = pd.DataFrame(
        [
            {
                "lat": (p.get("location") or {}).get("centroid_lat"),
                "lon": (p.get("location") or {}).get("centroid_lon"),
            }
            for p in packets
            if (p.get("location") or {}).get("centroid_lat") is not None
        ]
    )
    if df_cent.empty:
        return (51.5, 0.0)
    return (float(df_cent["lat"].mean()), float(df_cent["lon"].mean()))


def _legend_html(enabled: dict[str, bool]) -> str:
    """
    Compact, layer-aware legend.

    Only shows entries relevant to the active polygon coloring mode and enabled marker layers.
    This avoids the confusing situation where multiple overlays reuse similar colors.
    """
    mode = "areas"
    for k in [
        "confidence",
        "uncertainty",
        "observed_cells",
        "interpolated_cells",
        "synthetic_cells",
        "road_density",
        "built_up_ratio",
        "green_area",
        "industrial_commercial",
        "low_confidence_cells",
        "high_uncertainty_cells",
    ]:
        if enabled.get(k, False):
            mode = k
            break

    def _swatches(items: list[tuple[str, str]]) -> str:
        return "".join(
            [
                "<div style='margin:2px 0; white-space:nowrap;'>"
                f"<span style='display:inline-block;width:10px;height:10px;background:{c};margin-right:6px;"
                "border:1px solid rgba(0,0,0,0.15);'></span>"
                f"{t}</div>"
                for t, c in items
            ]
        )

    def _gradient(label: str, *, left: str, right: str, hint: str) -> str:
        return (
            "<div style='margin:2px 0 6px 0;'>"
            f"<div style='font-weight:600; margin-bottom:4px;'>{label}</div>"
            "<div style='height:10px;border-radius:4px;border:1px solid rgba(0,0,0,0.15);"
            f"background: linear-gradient(90deg, {left}, {right});'></div>"
            f"<div style='font-size:10px; color:#555; margin-top:2px;'>{hint}</div>"
            "</div>"
        )

    sections: list[str] = []

    if mode == "areas":
        cat = [
            ("Good / satisfactory", _rgb_to_hex(_category_color("good"))),
            ("Moderate", _rgb_to_hex(_category_color("moderate"))),
            ("Poor / very poor", _rgb_to_hex(_category_color("poor"))),
            ("Severe", _rgb_to_hex(_category_color("severe"))),
        ]
        sections.append(f"<div style='margin-bottom:6px;'><div style='font-weight:600;'>Forecast category</div>{_swatches(cat)}</div>")
    elif mode == "confidence":
        conf = [("High", _confidence_color("high")), ("Medium", _confidence_color("medium")), ("Low", _confidence_color("low"))]
        sections.append(f"<div style='margin-bottom:6px;'><div style='font-weight:600;'>Confidence</div>{_swatches(conf)}</div>")
    elif mode == "uncertainty":
        sections.append(_gradient("Uncertainty band", left="rgba(41,128,185,0.15)", right="rgba(41,128,185,0.80)", hint="Darker fill = higher uncertainty"))
    elif mode in {"observed_cells", "interpolated_cells", "synthetic_cells"}:
        src = [
            ("Observed (real)", _aq_source_color("real")),
            ("Estimated (interpolated)", _aq_source_color("interpolated")),
            ("Synthetic/test", _aq_source_color("synthetic")),
        ]
        sections.append(f"<div style='margin-bottom:6px;'><div style='font-weight:600;'>AQ data type</div>{_swatches(src)}</div>")
    elif mode in {"road_density", "built_up_ratio", "green_area", "industrial_commercial"}:
        sections.append(_gradient("Feature intensity", left="#ffffcc", right="#800026", hint="Light = lower value, dark = higher value"))
    elif mode == "low_confidence_cells":
        sections.append(f"<div style='margin-bottom:6px;'><div style='font-weight:600;'>Low-confidence cells</div>{_swatches([('Confidence score < 0.4', '#8e44ad')])}</div>")
    elif mode == "high_uncertainty_cells":
        sections.append(f"<div style='margin-bottom:6px;'><div style='font-weight:600;'>High-uncertainty cells</div>{_swatches([('Band above threshold', '#2980b9')])}</div>")

    if enabled.get("aq_sensors", True) and enabled.get("sensor_reliability", False):
        rel = [
            ("Healthy", _sensor_reliability_color("healthy")),
            ("Degraded", _sensor_reliability_color("degraded")),
            ("Suspect", _sensor_reliability_color("suspect")),
            ("Offline", _sensor_reliability_color("offline")),
        ]
        sections.append(f"<div><div style='font-weight:600;'>Sensor reliability (markers)</div>{_swatches(rel)}</div>")

    body = "".join(sections) if sections else "<div style='font-size:11px;color:#555;'>Enable a layer to see its legend.</div>"

    return f"""
    <div style="
        position: fixed; bottom: 18px; left: 18px; z-index: 9999;
        background: rgba(255,255,255,0.90); padding: 6px 8px; border: 1px solid #d0d0d0;
        border-radius: 6px; font-size: 11px; max-width: 200px; max-height: 180px; overflow: auto;">
      <details style="cursor: pointer;" open>
        <summary style="font-weight:600;">Legend</summary>
        <div style="margin-top:6px;">{body}</div>
        <div style="font-size:10px; color:#666; margin-top:6px;">
          Tip: use one polygon coloring mode at a time.
        </div>
      </details>
    </div>
    """


def _packet_geometry(packet: dict) -> dict | None:
    geom = ((packet.get("location") or {}).get("geometry_geojson")) or None
    if isinstance(geom, dict) and geom.get("type"):
        return geom
    return None


def _feature_pivot(features_df: pd.DataFrame) -> pd.DataFrame:
    """
    feature_store is long-form; pivot into a wide per-grid table for static features.
    """
    if features_df is None or features_df.empty:
        return pd.DataFrame()
    df = features_df.copy()
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df[ts.isna()].copy()  # static features
    if not {"grid_id", "feature_name", "value"}.issubset(df.columns):
        return pd.DataFrame()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    wide = df.pivot_table(index="grid_id", columns="feature_name", values="value", aggfunc="first")
    wide = wide.reset_index()
    return wide


def _add_packet_polygons(
    fg: folium.FeatureGroup,
    packets: list[dict],
    *,
    style_fn,
    popup_fn,
    tooltip_fn=None,
) -> None:
    for p in packets:
        geom = _packet_geometry(p)
        if not geom:
            continue
        folium.GeoJson(
            {"type": "Feature", "geometry": geom, "properties": {}},
            style_function=lambda *_a, pkt=p: style_fn(pkt),
            tooltip=folium.Tooltip(tooltip_fn(p) if tooltip_fn else ""),
            popup=folium.Popup(popup_fn(p), max_width=450),
        ).add_to(fg)


def render_layered_map(
    packets,
    selected_packet,
    features_df=None,
    sensor_siting_gdf=None,
):
    """
    Layered evidence map using Folium FeatureGroups + LayerControl.
    """
    if not packets:
        st.info("No areas to display.")
        return

    enabled: dict[str, bool] = st.session_state.get(
        "map_layers",
        {
            "areas": True,
            "selected": True,
            "aq_sensors": True,
        },
    )
    max_cells_for_map = int(st.session_state.get("max_cells_for_map", 400))
    high_uncertainty_threshold = float(st.session_state.get("high_uncertainty_threshold", 50.0))

    center = _center_from_packets(packets)
    m = folium.Map(location=center, zoom_start=12, control_scale=True, tiles=None)

    # Base layers
    folium.TileLayer("CartoDB positron", name="Light basemap", control=True).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)

    # Legend (compact + layer-aware)
    m.get_root().html.add_child(folium.Element(_legend_html(enabled)))

    packets_for_heavy = packets
    if len(packets) > max_cells_for_map and any(enabled.get(k, False) for k in ["road_density", "built_up_ratio", "green_area", "industrial_commercial"]):
        st.warning("Too many cells to render. Narrow filters or use bbox mode.")
        packets_for_heavy = [selected_packet] if selected_packet else packets[:max_cells_for_map]

    # Decision-support layers
    if enabled.get("areas", True):
        fg = folium.FeatureGroup(name="Areas needing review", show=True)

        def style(pkt):
            cat = str(((pkt.get("prediction") or {}).get("pm25_category_india")) or "unknown")
            fill = _rgb_to_hex(_category_color(cat))
            return {"fillColor": fill, "color": "#2c3e50", "weight": 1, "fillOpacity": 0.55}

        def popup(pkt):
            idx = packets.index(pkt) if pkt in packets else 0
            area_label = f"Area {idx + 1}"
            pred = pkt.get("prediction") or {}
            conf = pkt.get("confidence") or {}
            return (
                f"<b>{area_label}</b><br>"
                f"<b>Technical ID</b>: {pkt.get('packet_id','')}<br>"
                f"<b>Forecast PM2.5</b>: {pred.get('forecast_pm25_mean','—')} µg/m³<br>"
                f"<b>Forecast category</b>: {pred.get('pm25_category_india','—')}<br>"
                f"<b>Confidence</b>: {pkt.get('confidence_level','—')} ({conf.get('confidence_score','—')})<br>"
                f"<b>Suggested handling</b>: {pkt.get('actionability_level','—')}"
            )

        _add_packet_polygons(fg, packets, style_fn=style, popup_fn=popup, tooltip_fn=lambda p: str(p.get("packet_id") or ""))
        fg.add_to(m)

    if enabled.get("selected", True) and selected_packet:
        geom = _packet_geometry(selected_packet)
        if geom:
            fg_sel = folium.FeatureGroup(name="Selected area", show=True)
            folium.GeoJson(
                {"type": "Feature", "geometry": geom, "properties": {}},
                style_function=lambda *_a: {"fillColor": "#00000000", "color": "#000000", "weight": 4, "fillOpacity": 0.0},
            ).add_to(fg_sel)
            fg_sel.add_to(m)

    if enabled.get("uncertainty", False):
        fg_u = folium.FeatureGroup(name="Forecast uncertainty", show=False)

        def style_u(pkt):
            band = float(((pkt.get("prediction") or {}).get("uncertainty_band")) or 0.0)
            op = float(min(0.80, max(0.10, band / 100.0)))
            return {"fillColor": "#2980b9", "color": "#34495e", "weight": 1, "fillOpacity": op}

        _add_packet_polygons(fg_u, packets, style_fn=style_u, popup_fn=lambda p: "Uncertainty layer")
        fg_u.add_to(m)

    if enabled.get("confidence", False):
        fg_c = folium.FeatureGroup(name="Confidence", show=False)

        def style_c(pkt):
            col = _confidence_color(str(pkt.get("confidence_level") or "unknown"))
            return {"fillColor": col, "color": "#34495e", "weight": 1, "fillOpacity": 0.55}

        _add_packet_polygons(fg_c, packets, style_fn=style_c, popup_fn=lambda p: "Confidence layer")
        fg_c.add_to(m)

    # Observation layers (cell provenance)
    def _source_layer(name: str, source_type: str, *, show: bool):
        fg_s = folium.FeatureGroup(name=name, show=show)

        def style_s(pkt):
            aqst = str(((pkt.get("provenance") or {}).get("aq_source_type")) or "").lower()
            if aqst != source_type:
                return {"fillOpacity": 0.0, "opacity": 0.0}
            return {"fillColor": _aq_source_color(source_type), "color": "#2c3e50", "weight": 1, "fillOpacity": 0.6}

        def popup_s(pkt):
            if source_type == "synthetic":
                return "<b>WARNING</b>: Synthetic/test data used for this cell. Do not use for decisions."
            return f"AQ data type: {source_type}"

        _add_packet_polygons(fg_s, packets, style_fn=style_s, popup_fn=popup_s)
        fg_s.add_to(m)

    if enabled.get("observed_cells", False):
        _source_layer("Observed PM2.5 cells", "real", show=False)
    if enabled.get("interpolated_cells", False):
        _source_layer("Interpolated PM2.5 cells", "interpolated", show=False)
    if enabled.get("synthetic_cells", False):
        _source_layer("Synthetic/test data cells", "synthetic", show=False)

    # Sensors (from selected packet nearby_station_records)
    if enabled.get("aq_sensors", True):
        fg_st = folium.FeatureGroup(name="AQ sensors", show=True)
        stations = []
        if selected_packet:
            stations = ((selected_packet.get("evidence") or {}).get("nearby_station_records")) or []
        for s in stations:
            lat = s.get("point_lat")
            lon = s.get("point_lon")
            if lat is None or lon is None:
                continue
            try:
                lat = float(lat)
                lon = float(lon)
            except Exception:
                continue
            rel_status = str(s.get("source_reliability_status") or "unknown")
            popup = (
                f"<b>Sensor</b>: {s.get('entity_id','')}<br>"
                f"<b>Latest PM2.5</b>: {s.get('latest_pm25_value','')}<br>"
                f"<b>Reliability</b>: {rel_status}<br>"
                f"<b>Distance to selected area</b>: {s.get('distance_km','')} km"
            )
            folium.CircleMarker(
                location=(lat, lon),
                radius=6,
                color=_sensor_reliability_color(rel_status) if enabled.get("sensor_reliability", False) else "#3498db",
                fill=True,
                fill_opacity=0.9,
                popup=folium.Popup(popup, max_width=350),
            ).add_to(fg_st)
        fg_st.add_to(m)

    # Feature layers: choropleths by packet geometry
    wide = _feature_pivot(features_df) if features_df is not None else pd.DataFrame()
    if not wide.empty:
        wide = wide.rename(columns={"grid_id": "h3_id"})
        wide["h3_id"] = wide["h3_id"].astype(str)

    def _feature_layer(layer_name: str, col_name: str, *, show: bool):
        if wide.empty or col_name not in wide.columns:
            return
        vals = wide[col_name].dropna()
        if vals.empty:
            return
        cmap = linear.YlOrRd_09.scale(float(vals.min()), float(vals.max()))
        fg_f = folium.FeatureGroup(name=layer_name, show=show)

        def style_f(pkt):
            hid = str(pkt.get("h3_id") or "")
            row = wide[wide["h3_id"] == hid]
            if row.empty:
                return {"fillOpacity": 0.0, "opacity": 0.0}
            v = row.iloc[0][col_name]
            if v is None or (isinstance(v, float) and not np.isfinite(float(v))):
                return {"fillOpacity": 0.0, "opacity": 0.0}
            return {"fillColor": cmap(float(v)), "color": "#34495e", "weight": 1, "fillOpacity": 0.65}

        _add_packet_polygons(fg_f, packets_for_heavy, style_fn=style_f, popup_fn=lambda p: layer_name)
        fg_f.add_to(m)

    if enabled.get("road_density", False):
        _feature_layer("Road density", "road_density_km_per_sqkm", show=False)
    if enabled.get("built_up_ratio", False):
        _feature_layer("Built-up ratio", "built_up_ratio", show=False)
    if enabled.get("green_area", False):
        _feature_layer("Green area", "green_area_sqm", show=False)
    if enabled.get("industrial_commercial", False):
        if not wide.empty:
            wide["industrial_commercial"] = pd.to_numeric(wide.get("industrial_landuse_area_sqm"), errors="coerce").fillna(0.0) + pd.to_numeric(
                wide.get("commercial_landuse_area_sqm"), errors="coerce"
            ).fillna(0.0)
        _feature_layer("Industrial/commercial area", "industrial_commercial", show=False)

    # Reliability layers
    if enabled.get("low_confidence_cells", False):
        fg_lc = folium.FeatureGroup(name="Low-confidence cells", show=False)

        def style_lc(pkt):
            cs = ((pkt.get("confidence") or {}).get("confidence_score")) or 0.0
            try:
                cs = float(cs)
            except Exception:
                cs = 0.0
            if cs >= 0.4:
                return {"fillOpacity": 0.0, "opacity": 0.0}
            return {"fillColor": "#8e44ad", "color": "#2c3e50", "weight": 1, "fillOpacity": 0.65}

        _add_packet_polygons(fg_lc, packets, style_fn=style_lc, popup_fn=lambda p: "Low confidence (<0.4)")
        fg_lc.add_to(m)

    if enabled.get("high_uncertainty_cells", False):
        fg_hu = folium.FeatureGroup(name="High-uncertainty cells", show=False)

        def style_hu(pkt):
            band = float(((pkt.get("prediction") or {}).get("uncertainty_band")) or 0.0)
            if band <= high_uncertainty_threshold:
                return {"fillOpacity": 0.0, "opacity": 0.0}
            return {"fillColor": "#2980b9", "color": "#2c3e50", "weight": 1, "fillOpacity": 0.70}

        _add_packet_polygons(fg_hu, packets, style_fn=style_hu, popup_fn=lambda p: f"High uncertainty (>{high_uncertainty_threshold})")
        fg_hu.add_to(m)

    if enabled.get("sensor_siting", False):
        # If not provided, try to load from default outputs path (read-only)
        if sensor_siting_gdf is None:
            path = Path("data/outputs/sensor_siting_candidates.geojson")
            if path.exists():
                try:
                    sensor_siting_gdf = gpd.read_file(path)
                except Exception:
                    sensor_siting_gdf = None
        if sensor_siting_gdf is not None and not sensor_siting_gdf.empty:
            fg_ss = folium.FeatureGroup(name="Suggested new sensor locations", show=False)
            g = sensor_siting_gdf.to_crs("EPSG:4326").copy()
            for _, r in g.iterrows():
                ctr = r.geometry.centroid
                popup = (
                    f"<b>Rank</b>: {r.get('rank','')}<br>"
                    f"<b>Score</b>: {r.get('siting_score','')}<br>"
                    f"<b>Rationale</b>: {r.get('rationale','')}<br>"
                    f"<b>Planning confidence</b>: {r.get('planning_confidence','')}"
                )
                folium.CircleMarker(
                    location=(float(ctr.y), float(ctr.x)),
                    radius=6,
                    color="#16a085",
                    fill=True,
                    fill_opacity=0.9,
                    popup=folium.Popup(popup, max_width=350),
                ).add_to(fg_ss)
            fg_ss.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Prefer interactive Folium embed (enables click -> selected area)
    try:
        from streamlit_folium import st_folium  # type: ignore

        res = st_folium(m, height=600, width="100%")
        if isinstance(res, dict):
            # Robustly extract packet_id from known click fields and any returned values.
            candidates = []
            for k in [
                "last_object_clicked_popup",
                "last_object_clicked_tooltip",
                "last_object_clicked",
                "last_active_drawing",
                "last_clicked",
            ]:
                if k in res and res.get(k) is not None:
                    candidates.append(str(res.get(k)))
            candidates.extend([str(v) for v in res.values() if v is not None])
            blob = " ".join(candidates)
            m_id = re.search(r"(pkt_[0-9a-f]{16})", blob, flags=re.IGNORECASE)
            if m_id:
                new_id = m_id.group(1)
                old_id = st.session_state.get("selected_packet_id")
                if new_id and new_id != old_id:
                    st.session_state["selected_packet_id"] = new_id
    except Exception:
        st.caption("Tip: install `streamlit-folium` to enable selecting an area by clicking on the map.")
        # Fallback: static HTML (no click selection)
        components.html(m.get_root().render(), height=600)


def render_map(packets: list[dict], selected: dict | None, **kwargs: Any):
    # Backwards-compatible entrypoint used by the dashboard; now renders a layered Folium evidence map.
    return render_layered_map(packets, selected, **kwargs)

