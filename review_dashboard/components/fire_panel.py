"""Fire Monitoring dashboard panel — VIIRS active fire detection."""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
from review_dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from urban_platform.applications.fire.fire_pipeline import (
    build_fire_dashboard,
)

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from urban_platform.city_config import CITIES as _CITY_REGISTRY, get_bbox
from review_dashboard.data_cache import load_firms as _load_firms_shared

_DEFAULT_H3_RES = 8

# ── Risk colour map ────────────────────────────────────────────────────────

_RISK_COLORS = {
    "none":     [200, 200, 200, 60],
    "low":      [255, 220, 80, 140],
    "moderate": [255, 140, 0, 180],
    "high":     [220, 60, 0, 210],
    "severe":   [140, 0, 0, 240],
}

def _risk_emoji(level: str) -> str:
    return {"none": "⚪", "low": "🟡", "moderate": "🟠", "high": "🔴", "severe": "⚫"}.get(level, "⚪")


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, bool, int]:
    c1, c2, c3 = st.columns([2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="fire_city_selector")
    with c2:
        live = st.toggle("Live data (FIRMS)", value=True, key="fire_live_toggle",
                         help="Fetches NASA FIRMS VIIRS SNPP (requires FIRMS_API_KEY)")
    with c3:
        day_range = st.selectbox("Lookback (days)", [1, 2, 3, 7], index=0, key="fire_day_range",
                                 help="How many days of FIRMS data to fetch")
    city_id = city_options[city_label]
    bbox    = get_bbox(city_id)
    return city_id, bbox, live, int(day_range)


# ── Data loading ───────────────────────────────────────────────────────────

def _load_firms(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                day_range: int) -> pd.DataFrame:
    return _load_firms_shared(lat_min, lon_min, lat_max, lon_max, day_range)


def _synthetic_fires(bbox: dict) -> pd.DataFrame:
    """Demo fire hotspots for when FIRMS_API_KEY is absent."""
    lat_mid = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_mid = (bbox["lon_min"] + bbox["lon_max"]) / 2
    rows = [
        # Two clusters inside city
        {"latitude": lat_mid + 0.04, "longitude": lon_mid + 0.05,
         "frp": 85.3, "detection_confidence": 90, "acq_date": "2026-05-08",
         "satellite": "SNPP", "within_bbox": True},
        {"latitude": lat_mid + 0.05, "longitude": lon_mid + 0.06,
         "frp": 42.1, "detection_confidence": 90, "acq_date": "2026-05-08",
         "satellite": "SNPP", "within_bbox": True},
        {"latitude": lat_mid + 0.02, "longitude": lon_mid + 0.03,
         "frp": 18.7, "detection_confidence": 60, "acq_date": "2026-05-08",
         "satellite": "SNPP", "within_bbox": True},
        # Airshed fires
        {"latitude": lat_mid + 0.12, "longitude": lon_mid - 0.15,
         "frp": 220.0, "detection_confidence": 90, "acq_date": "2026-05-08",
         "satellite": "SNPP", "within_bbox": False},
        {"latitude": lat_mid - 0.18, "longitude": lon_mid + 0.20,
         "frp": 55.4, "detection_confidence": 60, "acq_date": "2026-05-07",
         "satellite": "SNPP", "within_bbox": False},
        {"latitude": lat_mid - 0.25, "longitude": lon_mid - 0.22,
         "frp": 12.0, "detection_confidence": 30, "acq_date": "2026-05-07",
         "satellite": "SNPP", "within_bbox": False},
    ]
    return pd.DataFrame(rows)


# ── Map ────────────────────────────────────────────────────────────────────

def _render_fire_map(
    dashboard: dict,
    fire_df: pd.DataFrame,
    bbox: dict,
    h3_res: int,
    min_confidence: int,
) -> None:
    cells = dashboard.get("risk_cells", [])

    layers = []

    # ── Layer 1: H3 fire intensity grid ──────────────────────────────────
    if cells:
        grid_df = pd.DataFrame([
            {
                "h3_id":        c["h3_id"],
                "risk_level":   c["risk_level"],
                "fire_count":   c["fire_count"],
                "total_frp_mw": c["total_frp_mw"],
                "max_frp_mw":   c["max_frp_mw"],
                "within_city":  "Yes" if c["within_city"] else "No",
                "color":        _RISK_COLORS[c["risk_level"]],
                # placeholder fields so tooltip resolves on all layers
                "latitude":     "",
                "frp":          "",
                "confidence":   "",
                "satellite":    "",
                "acq_date":     "",
                "location":     "",
            }
            for c in cells
        ])
        grid_layer = pdk.Layer(
            "H3HexagonLayer",
            data=clean_h3_data(grid_df),
            get_hexagon="h3_id",
            get_fill_color="color",
            get_line_color=[80, 80, 80],
            line_width_min_pixels=0,
            pickable=True,
            extruded=False,
            opacity=0.7,
            id="fire_grid",
        )
        layers.append(grid_layer)

    # ── Layer 2: Individual fire hotspots ─────────────────────────────────
    if not fire_df.empty and {"latitude", "longitude", "frp"}.issubset(fire_df.columns):
        pts = fire_df[fire_df["frp"] >= 5.0].copy()
        if min_confidence > 0 and "detection_confidence" in pts.columns:
            pts = pts[pts["detection_confidence"] >= min_confidence]

        if not pts.empty:
            fire_pts = pd.DataFrame([
                {
                    "latitude":   float(r["latitude"]),
                    "longitude":  float(r["longitude"]),
                    "frp":        f"{float(r.get('frp', 0)):.1f}",
                    "radius":     max(400, min(2500, float(r.get("frp", 5)) * 50)),
                    "color":      [255, 60, 0, 230] if r.get("within_bbox") else [255, 150, 0, 190],
                    "confidence": f"{int(r.get('detection_confidence', 0))}%",
                    "satellite":  str(r.get("satellite", "VIIRS")),
                    "acq_date":   str(r.get("acq_date", "")),
                    "location":   "City" if r.get("within_bbox") else "Airshed",
                    # grid placeholder fields
                    "h3_id":        "",
                    "risk_level":   "",
                    "fire_count":   "",
                    "total_frp_mw": "",
                    "max_frp_mw":   "",
                    "within_city":  "",
                }
                for _, r in pts.iterrows()
            ])
            hotspot_layer = pdk.Layer(
                "ScatterplotLayer",
                data=clean_h3_data(fire_pts),
                get_position=["longitude", "latitude"],
                get_radius="radius",
                radius_min_pixels=5,
                get_fill_color="color",
                get_line_color=[160, 30, 0, 255],
                line_width_min_pixels=2,
                stroked=True, filled=True, pickable=True,
                id="fire_hotspots",
            )
            layers.append(hotspot_layer)

    if not layers:
        st.info("No fire detections to display for the selected filters.")
        return

    center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    center_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    zoom = {7: 9, 8: 10, 9: 11, 10: 12}.get(h3_res, 10)
    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    tooltip = {
        "html": """
            <div style="font-family:sans-serif;font-size:12px;padding:6px 10px;
                        background:rgba(20,10,0,0.92);color:#fff;border-radius:4px;max-width:280px;">
              <b style="color:#ff8040;">🔥 Fire detection</b><br/>
              <b>Location:</b> {location}<br/>
              <b>FRP:</b> {frp} MW &nbsp; <b>Confidence:</b> {confidence}<br/>
              <b>Satellite:</b> {satellite} &nbsp; <b>Date:</b> {acq_date}<br/>
              <hr style="margin:4px 0;border-color:#555;"/>
              <b>H3 cell:</b> {h3_id}<br/>
              <b>Risk level:</b> {risk_level} &nbsp; <b>Hotspots:</b> {fire_count}<br/>
              <b>Total FRP:</b> {total_frp_mw} MW &nbsp; <b>Peak:</b> {max_frp_mw} MW
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
        st.markdown("**H3 Cell Risk**")
        st.markdown(
            """
            <div style="font-size:11px;line-height:1.9;">
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,220,80,0.6);
                         margin-right:6px;border-radius:2px;"></span>Low (&lt;10 MW)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,140,0,0.75);
                         margin-right:6px;border-radius:2px;"></span>Moderate (&lt;30 MW)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(220,60,0,0.85);
                         margin-right:6px;border-radius:2px;"></span>High (&lt;100 MW)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(140,0,0,0.95);
                         margin-right:6px;border-radius:2px;"></span>Severe (≥100 MW)<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("**Hotspots**")
        st.markdown(
            """
            <div style="font-size:11px;line-height:1.9;">
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,60,0,0.9);
                         border:2px solid #a01e00;margin-right:6px;border-radius:50%;"></span>City<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,150,0,0.75);
                         border:2px solid #a06000;margin-right:6px;border-radius:50%;"></span>Airshed<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Circle size ∝ FRP (MW). Hover for details.")

        rs = dashboard.get("risk_summary", {})
        n_city = rs.get("hotspots_in_city", 0)
        n_all  = rs.get("total_hotspots", 0)
        st.markdown(
            f"**{n_city}** city  \n"
            f"**{n_all - n_city}** airshed  \n"
            f"**{rs.get('max_frp_mw', 0):.0f} MW** peak FRP"
        )


# ── Time series ────────────────────────────────────────────────────────────

def _render_trend(fire_df: pd.DataFrame) -> None:
    if fire_df.empty or "acq_date" not in fire_df.columns:
        st.info("No time series data available.")
        return

    sig = fire_df[fire_df["frp"] >= 5.0] if "frp" in fire_df.columns else fire_df
    by_date = (
        sig.groupby("acq_date")
        .agg(hotspot_count=("frp", "count"), total_frp_mw=("frp", "sum"))
        .reset_index()
        .rename(columns={"acq_date": "Date"})
        .sort_values("Date")
    )

    c1, c2 = st.columns(2)
    with c1:
        render_section_title("Hotspot count by date")
        st.bar_chart(by_date.set_index("Date")["hotspot_count"], height=200)
    with c2:
        render_section_title("Total FRP (MW) by date")
        st.bar_chart(by_date.set_index("Date")["total_frp_mw"], height=200)

    st.dataframe(by_date, hide_index=True, use_container_width=True)


# ── Main panel ─────────────────────────────────────────────────────────────

def render_fire_panel() -> None:
    city_id, bbox, live, day_range = _city_selector()
    h3_res = _DEFAULT_H3_RES

    render_domain_header(
        title="Fire Monitoring",
        caption=(
            "Active fire hotspots from NASA FIRMS VIIRS SNPP satellite, aggregated into H3 cells. "
            "Covers city boundary and 50 km airshed. Supports air quality impact assessment. "
            "Review-support only — field verification required before escalation."
        ),
        primary_alert=(
            "Fire detection is a monitoring signal only. "
            "Do not issue advisories or dispatch resources without field confirmation."
        ),
        primary_alert_kind="warning",
    )

    # ── Confidence filter ──────────────────────────────────────────────────
    min_conf = st.select_slider(
        "Minimum detection confidence (%)",
        options=[0, 30, 60, 90],
        value=30,
        key="fire_min_conf",
        help="VIIRS confidence: 0=all, 30=low+, 60=nominal+, 90=high only",
    )

    # ── Load data ──────────────────────────────────────────────────────────
    with st.spinner("Fetching fire data…"):
        if live:
            fire_df = _load_firms(
                bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                day_range=day_range,
            )
            if fire_df.empty:
                st.warning(
                    "FIRMS returned no data (FIRMS_API_KEY not set or no detections). "
                    "Showing synthetic demo data."
                )
                fire_df = _synthetic_fires(bbox)
                data_note = "synthetic demo"
            else:
                n_sig = int((fire_df["frp"] >= 5).sum()) if "frp" in fire_df.columns else 0
                data_note = f"NASA FIRMS VIIRS ({n_sig} detections ≥5 MW, last {day_range}d)"
        else:
            fire_df = _synthetic_fires(bbox)
            data_note = "synthetic demo"

        dashboard = build_fire_dashboard(
            fire_df=fire_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )
        if live:
            try:
                from urban_platform.decision_events import emit_fire_decisions
                emit_fire_decisions(fire_df, city_id=city_id, bbox=bbox)
            except Exception:
                pass

    # ── Warnings ───────────────────────────────────────────────────────────
    rs = dashboard.get("risk_summary", {})
    cells = dashboard.get("risk_cells", [])

    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{w.get('warning_id', '')}** — {w.get('message', '')}"
        (st.error if sev == "error" else st.warning if sev == "warning" else st.info)(msg)

    # ── Context metrics ────────────────────────────────────────────────────
    render_context_metrics(
        ("City", city_id),
        ("Overall fire risk", rs.get("overall_risk_level", "—").upper()),
        ("Hotspots in city", str(rs.get("hotspots_in_city", 0))),
        ("Hotspots in airshed", str(rs.get("total_hotspots", 0) - rs.get("hotspots_in_city", 0))),
        ("Max FRP (MW)", f"{rs.get('max_frp_mw', 0):.1f}"),
        ("Total FRP (MW)", f"{rs.get('total_frp_mw', 0):.1f}"),
        ("Active H3 cells", str(rs.get("active_cells", 0))),
        ("Data source", data_note),
    )

    st.divider()

    # ── Tabs ───────────────────────────────────────────────────────────────
    t_map, t_hotspots, t_trend = st.tabs(
        ["🗺️ Map", "🔥 Hotspot table", "📈 Trend"]
    )

    with t_map:
        _render_fire_map(dashboard, fire_df, bbox=bbox, h3_res=h3_res, min_confidence=min_conf)
        st.caption(
            "Dark base map highlights fire locations. "
            "**H3 cells** coloured by aggregate fire intensity (total FRP). "
            "**Red circles** (city) and **amber circles** (airshed) are individual VIIRS detections — "
            "size proportional to fire radiative power (FRP in MW). "
            "Airshed buffer extends ~50 km beyond city bbox."
        )

    with t_hotspots:
        render_section_title("Fire hotspot table")
        if fire_df.empty:
            st.info("No fire data loaded.")
        else:
            sig = fire_df[fire_df["frp"] >= 5.0].copy() if "frp" in fire_df.columns else fire_df.copy()
            if min_conf > 0 and "detection_confidence" in sig.columns:
                sig = sig[sig["detection_confidence"] >= min_conf]
            if sig.empty:
                st.info("No detections match the selected confidence filter.")
            else:
                sig = sig.sort_values("frp", ascending=False) if "frp" in sig.columns else sig
                show_cols = [c for c in
                             ["acq_date", "latitude", "longitude", "frp",
                              "detection_confidence", "satellite", "within_bbox"]
                             if c in sig.columns]
                display = sig[show_cols].rename(columns={
                    "acq_date":             "Date",
                    "frp":                  "FRP (MW)",
                    "detection_confidence": "Confidence %",
                    "satellite":            "Satellite",
                    "within_bbox":          "In city",
                })
                st.dataframe(display, hide_index=True, use_container_width=True)
                st.caption(
                    "FRP = Fire Radiative Power. Higher FRP → more intense fire → greater smoke output. "
                    "Confidence: low (<40%), nominal (60%), high (90%)."
                )

        render_section_title("H3 cell aggregates")
        if cells:
            cell_rows = [
                {
                    _risk_emoji(c["risk_level"]): c["risk_level"],
                    "H3 cell":      str(c["h3_id"])[:16] + "…",
                    "Risk":         c["risk_level"],
                    "Detections":   c["fire_count"],
                    "Total FRP MW": c["total_frp_mw"],
                    "Peak FRP MW":  c["max_frp_mw"],
                    "Confidence %": c["avg_confidence"],
                    "Location":     "City" if c["within_city"] else "Airshed",
                    "Dates":        ", ".join(c["acq_dates"][:3]),
                }
                for c in cells
            ]
            st.dataframe(pd.DataFrame(cell_rows), hide_index=True, use_container_width=True)

    with t_trend:
        _render_trend(fire_df)

    render_technical_json_expander(
        title="Technical: Raw fire payloads",
        payload={"fire_dashboard": dashboard},
    )
