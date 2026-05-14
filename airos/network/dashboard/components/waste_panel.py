"""Waste Monitoring dashboard panel.

Combines three satellite signals:
  FIRMS VIIRS     — waste burn classification (FRP 5-30 MW, urban)
  Sentinel-2 NDVI — dump site detection (NDVI < 0.15)
  Sentinel-5P CH4 — landfill gas detection (CH4 > background + 20 ppb)
"""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
from airos.network.dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from airos.apps.waste.waste_pipeline import (
    build_waste_dashboard,
)

from airos.network.dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from airos.os.city_config import CITIES as _CITY_REGISTRY, get_bbox
from airos.network.dashboard.data_cache import (
    load_firms, load_ndvi, load_ch4, h3_grid_for_bbox,
)

_DEFAULT_H3_RES = 8

# ── Signal colour map ──────────────────────────────────────────────────────

_TYPE_COLORS = {
    "none":          [200, 200, 200,  50],
    "waste_burn":    [255, 180,   0, 180],
    "landfill_fire": [220,  80,   0, 210],
    "dump_site":     [139, 100,  20, 180],
    "landfill_gas":  [140,   0, 200, 170],
    "combined":      [140,   0,   0, 230],
}

_TYPE_LABELS = {
    "waste_burn":    "🔥 Waste burn",
    "landfill_fire": "🔥 Landfill fire",
    "dump_site":     "🟤 Dump site",
    "landfill_gas":  "🟣 Landfill gas",
    "combined":      "⚫ Combined",
    "none":          "⚪ None",
}

def _risk_emoji(level: str) -> str:
    return {"none": "⚪", "low": "🟡", "moderate": "🟠", "high": "🔴", "severe": "⚫"}.get(level, "⚪")


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, bool, int]:
    c1, c2, c3 = st.columns([2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="waste_city_selector")
    with c2:
        live = st.toggle("Live data", value=True, key="waste_live_toggle",
                         help="FIRMS requires FIRMS_API_KEY; NDVI/CH4 require GEE_PROJECT")
    with c3:
        day_range = st.selectbox("FIRMS lookback (days)", [3, 7, 14], index=1,
                                 key="waste_day_range",
                                 help="Longer = better persistence detection; 7d recommended")
    city_id = city_options[city_label]
    return city_id, get_bbox(city_id), live, int(day_range)


# ── Data loading — all API calls go through airos.network.dashboard.data_cache ────


def _synthetic_waste(bbox: dict) -> tuple[pd.DataFrame, dict, dict]:
    """Demo data covering all three waste signals."""
    lat_mid = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_mid = (bbox["lon_min"] + bbox["lon_max"]) / 2

    # Synthetic FIRMS — waste burns (FRP 5-30 MW) + persistent landfill fire
    firms_rows = [
        # Persistent landfill fire (3 days, same location)
        {"latitude": lat_mid+0.04, "longitude": lon_mid+0.05, "frp": 22.0,
         "detection_confidence": 60, "acq_date": "2026-05-06", "satellite": "SNPP", "within_bbox": True},
        {"latitude": lat_mid+0.04, "longitude": lon_mid+0.05, "frp": 18.5,
         "detection_confidence": 60, "acq_date": "2026-05-07", "satellite": "SNPP", "within_bbox": True},
        {"latitude": lat_mid+0.04, "longitude": lon_mid+0.05, "frp": 25.1,
         "detection_confidence": 60, "acq_date": "2026-05-08", "satellite": "SNPP", "within_bbox": True},
        # Single-day waste burn in city
        {"latitude": lat_mid-0.03, "longitude": lon_mid+0.04, "frp": 12.3,
         "detection_confidence": 30, "acq_date": "2026-05-08", "satellite": "SNPP", "within_bbox": True},
        # Peri-urban waste burn
        {"latitude": lat_mid+0.08, "longitude": lon_mid-0.06, "frp":  8.7,
         "detection_confidence": 30, "acq_date": "2026-05-08", "satellite": "SNPP", "within_bbox": False},
    ]
    firms_df = pd.DataFrame(firms_rows)

    # Synthetic NDVI — low values at dump site locations
    try:
        import h3
        dump1 = h3.latlng_to_cell(lat_mid - 0.05, lon_mid - 0.04, 9)
        dump2 = h3.latlng_to_cell(lat_mid + 0.06, lon_mid + 0.03, 9)
        ndvi_map = {dump1: 0.06, dump2: 0.12}
    except Exception:
        ndvi_map = {}

    # Synthetic CH4 — elevated at landfill fire location
    try:
        import h3
        lf = h3.latlng_to_cell(lat_mid + 0.04, lon_mid + 0.05, 9)
        ch4_map = {lf: 1928.0}  # +48 ppb above background
    except Exception:
        ch4_map = {}

    return firms_df, ndvi_map, ch4_map


# ── Map rendering ──────────────────────────────────────────────────────────

def _render_waste_map(
    dashboard: dict,
    firms_df: pd.DataFrame,
    bbox: dict,
    h3_res: int,
) -> None:
    cells = dashboard.get("risk_cells", [])
    layers = []

    # ── Layer 1: H3 waste risk grid ───────────────────────────────────────
    if cells:
        grid_df = pd.DataFrame([
            {
                "h3_id":         c["h3_id"],
                "dominant_type": c["dominant_type"],
                "risk_level":    c["risk_level"],
                "fire_count":    c.get("fire_count", 0),
                "total_frp_mw":  c.get("total_frp_mw", "—"),
                "active_days":   c.get("active_days", 0),
                "ndvi":          f"{c['ndvi']:.3f}" if c.get("ndvi") is not None else "—",
                "ch4_ppb":       f"{c['ch4_ppb']:.0f}" if c.get("ch4_ppb") is not None else "—",
                "ch4_elevation": f"+{c['ch4_elevation']:.0f}" if c.get("ch4_elevation") else "—",
                "color":         _TYPE_COLORS.get(c["dominant_type"], _TYPE_COLORS["none"]),
                # hotspot layer placeholder fields
                "confidence":    "",
                "satellite":     "",
                "acq_date":      "",
                "within_bbox":   "",
            }
            for c in cells
        ])
        grid_layer = pdk.Layer(
            "H3HexagonLayer",
            data=clean_h3_data(grid_df),
            get_hexagon="h3_id",
            get_fill_color="color",
            get_line_color=[60, 40, 20],
            line_width_min_pixels=0,
            pickable=True,
            extruded=False,
            opacity=0.75,
            id="waste_grid",
        )
        layers.append(grid_layer)

    # ── Layer 2: Waste burn / landfill fire hotspots ──────────────────────
    if not firms_df.empty and {"latitude", "longitude", "frp"}.issubset(firms_df.columns):
        waste_pts_data = []
        for _, r in firms_df.iterrows():
            frp = float(r.get("frp", 0))
            if frp < 5.0 or frp > 30.0:
                continue
            waste_pts_data.append({
                "latitude":   float(r["latitude"]),
                "longitude":  float(r["longitude"]),
                "frp":        f"{frp:.1f}",
                "radius":     max(300, min(1200, frp * 40)),
                "color":      [220, 80, 0, 220] if r.get("within_bbox") else [255, 160, 0, 180],
                "confidence": f"{int(r.get('detection_confidence', 0))}%",
                "satellite":  str(r.get("satellite", "VIIRS")),
                "acq_date":   str(r.get("acq_date", "")),
                "within_bbox": "City" if r.get("within_bbox") else "Airshed",
                # grid placeholder fields
                "h3_id":         "",
                "dominant_type": "",
                "risk_level":    "",
                "active_days":   "",
                "ndvi":          "",
                "ch4_ppb":       "",
                "ch4_elevation": "",
                "fire_count":    "",
                "total_frp_mw":  "",
            })
        if waste_pts_data:
            burn_layer = pdk.Layer(
                "ScatterplotLayer",
                data=pd.DataFrame(waste_pts_data),
                get_position=["longitude", "latitude"],
                get_radius="radius",
                radius_min_pixels=5,
                get_fill_color="color",
                get_line_color=[140, 40, 0, 255],
                line_width_min_pixels=2,
                stroked=True, filled=True, pickable=True,
                id="waste_burns",
            )
            layers.append(burn_layer)

    if not layers:
        st.info("No waste signals to display. Enable live data or check API key configuration.")
        return

    center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    center_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    zoom = {7: 9, 8: 10, 9: 11, 10: 12}.get(h3_res, 11)
    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    tooltip = {
        "html": """
            <div style="font-family:sans-serif;font-size:12px;padding:6px 10px;
                        background:rgba(20,10,0,0.92);color:#fff;border-radius:4px;max-width:300px;">
              <b style="color:#ffb347;">♻️ Waste signal</b><br/>
              <b>H3:</b> {h3_id}<br/>
              <b>Type:</b> {dominant_type} &nbsp; <b>Risk:</b> {risk_level}<br/>
              <b>Fires:</b> {fire_count} detections · {active_days} day(s) · {total_frp_mw} MW<br/>
              <b>NDVI:</b> {ndvi} &nbsp; <b>CH4:</b> {ch4_ppb} ppb ({ch4_elevation})<br/>
              <hr style="margin:4px 0;border-color:#555;"/>
              <b>Burn FRP:</b> {frp} MW · <b>Conf:</b> {confidence}<br/>
              <b>Satellite:</b> {satellite} · <b>Date:</b> {acq_date} · <b>Loc:</b> {within_bbox}
            </div>
        """,
        "style": {"color": "white"},
    }

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip=tooltip,
    )

    col_map, col_legend = st.columns([4, 1])

    with col_map:
        st.pydeck_chart(deck, use_container_width=True, height=540)

    with col_legend:
        st.markdown("**Signal type**")
        for key, label in _TYPE_LABELS.items():
            if key == "none":
                continue
            rgba = _TYPE_COLORS[key]
            hex_col = "#{:02x}{:02x}{:02x}".format(*rgba[:3])
            st.markdown(
                f'<div style="font-size:11px;margin-bottom:4px;">'
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'background:{hex_col};opacity:{rgba[3]/255:.2f};'
                f'margin-right:6px;border-radius:2px;"></span>{label}</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")
        rs = dashboard.get("risk_summary", {})
        st.markdown(
            f"**{rs.get('waste_burn_cells', 0)}** burn sites  \n"
            f"**{rs.get('persistent_burn_cells', 0)}** persistent  \n"
            f"**{rs.get('dump_site_cells', 0)}** dump sites  \n"
            f"**{rs.get('landfill_gas_cells', 0)}** gas plumes"
        )
        st.caption("Hover for details.")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_waste_panel() -> None:
    city_id, bbox, live, day_range = _city_selector()
    h3_res = _DEFAULT_H3_RES

    render_domain_header(
        title="Waste Monitoring",
        caption=(
            "Open waste burning, dump site identification, and landfill gas detection "
            "using NASA FIRMS VIIRS, Sentinel-2 NDVI, and Sentinel-5P CH4. Review-support only."
        ),
        primary_alert=(
            "Satellite signals are probabilistic. Field verification required before "
            "any enforcement or site classification action."
        ),
        primary_alert_kind="warning",
        domain="waste",
    )

    # ── Signal availability legend ─────────────────────────────────────────
    with st.expander("Signal sources & requirements", expanded=False):
        st.markdown(
            """
| Signal | Data source | Requires | What it detects |
|---|---|---|---|
| **Waste burn** | NASA FIRMS VIIRS | `FIRMS_API_KEY` | Low-FRP fires (5–30 MW) in urban/peri-urban areas |
| **Landfill fire** | NASA FIRMS VIIRS | `FIRMS_API_KEY` | Persistent hotspot (≥2 days at same location) |
| **Dump site** | Sentinel-2 NDVI | `GEE_PROJECT` | NDVI < 0.15 — bare/debris-covered surface |
| **Landfill gas** | Sentinel-5P CH4 | `GEE_PROJECT` | CH4 > 1900 ppb — methane from decomposition |
            """
        )

    # ── Load data ──────────────────────────────────────────────────────────
    with st.spinner("Loading waste signals…"):
        if live:
            firms_df = load_firms(
                bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                day_range,
            )
            # Stable sorted tuple → cache key never varies for same city/resolution
            all_h3 = h3_grid_for_bbox(
                bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], h3_res
            )
            ndvi_map = load_ndvi(all_h3, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"]) if all_h3 else {}
            ch4_map  = load_ch4(all_h3, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"]) if all_h3 else {}

            all_empty = firms_df.empty and not ndvi_map and not ch4_map
            if all_empty:
                st.warning(
                    "No live data available (FIRMS_API_KEY or GEE_PROJECT not set). "
                    "Showing synthetic demo data."
                )
                firms_df, ndvi_map, ch4_map = _synthetic_waste(bbox)
                data_note = "synthetic demo"
            else:
                parts = []
                if not firms_df.empty:
                    n = int((firms_df["frp"] >= 5).sum()) if "frp" in firms_df.columns else 0
                    parts.append(f"FIRMS ({n} waste detections, {day_range}d)")
                if ndvi_map:
                    parts.append(f"Sentinel-2 NDVI ({len(ndvi_map)} cells)")
                if ch4_map:
                    parts.append(f"Sentinel-5P CH4 ({len(ch4_map)} cells)")
                data_note = " · ".join(parts) or "no signals"
        else:
            firms_df, ndvi_map, ch4_map = _synthetic_waste(bbox)
            data_note = "synthetic demo"

        dashboard = build_waste_dashboard(
            firms_df=firms_df,
            ndvi_map=ndvi_map,
            ch4_map=ch4_map,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )
    # ── Warnings ───────────────────────────────────────────────────────────
    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{w.get('warning_id', '')}** — {w.get('message', '')}"
        (st.error if sev == "error" else st.warning if sev == "warning" else st.info)(msg)

    # ── Context metrics ────────────────────────────────────────────────────
    rs    = dashboard.get("risk_summary", {})
    cells = dashboard.get("risk_cells", [])
    sig   = dashboard.get("signal_availability", {})

    render_context_metrics(
        ("City", city_id),
        ("Overall risk", rs.get("overall_risk_level", "—").upper()),
        ("Waste burn sites", str(rs.get("waste_burn_cells", 0))),
        ("Persistent / landfill fires", str(rs.get("persistent_burn_cells", 0))),
        ("Dump sites (NDVI)", str(rs.get("dump_site_cells", 0))),
        ("Landfill gas plumes (CH4)", str(rs.get("landfill_gas_cells", 0))),
        ("Data source", data_note),
        ("FIRMS", "✓" if sig.get("firms") else "✗ (no API key)"),
        ("GEE (NDVI/CH4)", "✓" if (sig.get("sentinel2_ndvi") or sig.get("sentinel5p_ch4")) else "✗ (no project)"),
    )

    st.divider()

    # ── Tabs ───────────────────────────────────────────────────────────────
    t_map, t_sites, t_burns = st.tabs(
        ["🗺️ Map", "♻️ Waste sites", "🔥 Burn history"]
    )

    with t_map:
        _render_waste_map(dashboard, firms_df, bbox=bbox, h3_res=h3_res)
        st.caption(
            "**H3 cells** coloured by dominant waste signal: "
            "🔥 orange = waste burn · 🔥 dark-orange = persistent landfill fire · "
            "🟤 brown = dump site (low NDVI) · 🟣 purple = landfill gas (elevated CH4) · "
            "⚫ dark red = multiple signals. "
            "Circles are individual FIRMS waste burn detections."
        )

    with t_sites:
        render_section_title("Detected waste sites")
        if not cells:
            st.info("No waste sites detected.")
        else:
            rows = [
                {
                    "Risk": _risk_emoji(c["risk_level"]),
                    "H3 cell": str(c["h3_id"])[:16] + "…",
                    "Type": _TYPE_LABELS.get(c["dominant_type"], c["dominant_type"]),
                    "Risk level": c["risk_level"],
                    "Fire count": c.get("fire_count", 0),
                    "Total FRP MW": c.get("total_frp_mw", "—"),
                    "Active days": c.get("active_days", 0),
                    "NDVI": f"{c['ndvi']:.3f}" if c.get("ndvi") is not None else "—",
                    "CH4 (ppb)": f"{c['ch4_ppb']:.0f}" if c.get("ch4_ppb") is not None else "—",
                    "CH4 elev.": f"+{c['ch4_elevation']:.0f} ppb" if c.get("ch4_elevation") else "—",
                    "In city": "Yes" if c.get("within_city") else "No/Airshed",
                }
                for c in cells
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # Signal breakdown charts
        if cells:
            col1, col2, col3 = st.columns(3)
            with col1:
                render_section_title("Risk level distribution")
                level_counts = pd.DataFrame(
                    [{"Level": c["risk_level"]} for c in cells]
                )["Level"].value_counts().reset_index()
                level_counts.columns = ["Risk Level", "Count"]
                st.bar_chart(level_counts.set_index("Risk Level"), height=180)
            with col2:
                render_section_title("Signal type distribution")
                type_counts = pd.DataFrame(
                    [{"Type": c["dominant_type"]} for c in cells]
                )["Type"].value_counts().reset_index()
                type_counts.columns = ["Type", "Count"]
                st.bar_chart(type_counts.set_index("Type"), height=180)
            with col3:
                render_section_title("City vs airshed")
                loc_counts = pd.DataFrame([
                    {"Location": "City" if c.get("within_city") else "Airshed"}
                    for c in cells
                ])["Location"].value_counts().reset_index()
                loc_counts.columns = ["Location", "Count"]
                st.bar_chart(loc_counts.set_index("Location"), height=180)

    with t_burns:
        render_section_title("Waste burn / fire history")
        if firms_df.empty:
            st.info("No FIRMS data loaded. Set FIRMS_API_KEY to enable.")
        else:
            waste = firms_df[
                (firms_df.get("frp", pd.Series(dtype=float)) >= 5) &
                (firms_df.get("frp", pd.Series(dtype=float)) <= 30)
            ].copy() if "frp" in firms_df.columns else firms_df.copy()

            if waste.empty:
                st.info("No waste-scale fire detections (FRP 5–30 MW) in this period.")
            else:
                show_cols = [c for c in ["acq_date", "latitude", "longitude", "frp",
                                          "detection_confidence", "satellite", "within_bbox"]
                             if c in waste.columns]
                waste_display = waste[show_cols].sort_values("frp", ascending=False).rename(columns={
                    "acq_date": "Date", "frp": "FRP (MW)",
                    "detection_confidence": "Confidence %",
                    "satellite": "Satellite", "within_bbox": "In city",
                })
                st.dataframe(waste_display, hide_index=True, use_container_width=True)

            # Trend by date
            if "acq_date" in firms_df.columns and "frp" in firms_df.columns:
                render_section_title("Daily waste burn detections")
                trend = (
                    firms_df[firms_df["frp"].between(5, 30)]
                    .groupby("acq_date")["frp"]
                    .agg(count="count", total_frp="sum")
                    .reset_index()
                    .rename(columns={"acq_date": "Date"})
                    .sort_values("Date")
                )
                if not trend.empty:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption("Detection count")
                        st.bar_chart(trend.set_index("Date")["count"], height=180)
                    with c2:
                        st.caption("Total FRP (MW)")
                        st.bar_chart(trend.set_index("Date")["total_frp"], height=180)
                    st.caption(
                        "Fires active on the **same H3 cell for ≥ 2 days** are classified as "
                        "landfill fires (persistent burn sites). Single-day events are classified "
                        "as waste burns."
                    )

    render_technical_json_expander(
        title="Technical: Raw waste payloads",
        payload={"waste_dashboard": dashboard},
    )
