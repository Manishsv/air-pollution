"""Air Quality Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk
from review_dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.applications.air.air_pipeline import (
    build_air_quality_dashboard,
)
from urban_platform.connectors.air_quality import fetch_air_quality_observations

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from review_dashboard.formatters import (
    evidence_inputs_to_rows,
    humanize_snake_sentence,
    humanize_warning_id,
    safety_gates_to_rows,
)


_LOOKBACK_HOURS = 24

from urban_platform.city_config import CITIES as _CITY_REGISTRY, get_bbox
from review_dashboard.data_cache import load_firms as _load_firms_shared, load_aod as _load_aod_shared


# ── WHO 2021 PM2.5 breakpoints (µg/m³) ─────────────────────────────────────

def _who_category(pm25: float) -> str:
    if pm25 <= 5:    return "WHO good"
    if pm25 <= 10:   return "WHO target"
    if pm25 <= 15:   return "WHO moderate"
    if pm25 <= 25:   return "WHO poor"
    if pm25 <= 75:   return "WHO very poor"
    return "WHO hazardous"


# ── AQI color map ──────────────────────────────────────────────────────────

_AQI_COLOR_MAP = {
    "good":         [34, 139, 34, 180],
    "satisfactory": [144, 238, 0, 180],
    "moderate":     [255, 215, 0, 190],
    "poor":         [255, 140, 0, 200],
    "very_poor":    [200, 40, 40, 210],
    "severe":       [128, 0, 32, 230],
}

# AOD colour ramp: low (green) → high (red)
def _aod_color(aod: float) -> list:
    if aod < 0.1:  return [0, 200, 100, 80]
    if aod < 0.2:  return [180, 220, 0, 100]
    if aod < 0.4:  return [255, 200, 0, 120]
    if aod < 0.6:  return [255, 120, 0, 140]
    return [200, 0, 0, 160]


# ── Sidebar ─────────────────────────────────────────────────────────────────

_DEFAULT_H3_RES = 8  # fixed at H3 Knowledge Store resolution

def _city_selector() -> tuple[str, dict, bool, str]:
    c1, c2, c3 = st.columns([2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="air_city_selector")
    with c2:
        live = st.toggle("Live data (cached ≤1h)", value=True, key="air_live_toggle",
                         help="Uses CPCB if CPCB_API_KEY is set, otherwise OpenMeteo AQ")
    with c3:
        station_type_filter = st.selectbox(
            "Station type",
            ["All", "Residential", "Roadside", "Industrial", "Background"],
            key="air_station_type",
            help="Filter measurement stations by location type",
        )
    city_id = city_options[city_label]
    bbox    = get_bbox(city_id)
    return city_id, bbox, live, station_type_filter


# ── Data loading ────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Loading air quality data…")
def _load_live_aq(city_id: str, lat_min: float, lon_min: float,
                  lat_max: float, lon_max: float, lookback_hours: int) -> pd.DataFrame:
    try:
        from urban_platform.observation_store import ObservationStoreReader, to_wide
        cached = ObservationStoreReader().read_recent("air", city_id, max_age_hours=1)
        if not cached.empty:
            return to_wide(cached)
    except Exception:
        pass
    return fetch_air_quality_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_hours=lookback_hours,
        city_id=city_id,
    )


def _load_fire_data(lat_min: float, lon_min: float,
                    lat_max: float, lon_max: float) -> pd.DataFrame:
    return _load_firms_shared(lat_min, lon_min, lat_max, lon_max, day_range=1)


def _load_aod(h3_ids: tuple, lat_min: float, lon_min: float,
              lat_max: float, lon_max: float) -> dict:
    return _load_aod_shared(h3_ids, lat_min, lon_min, lat_max, lon_max)


def _synthetic_aq(bbox: dict) -> pd.DataFrame:
    lats = [bbox["lat_min"], (bbox["lat_min"] + bbox["lat_max"]) / 2, bbox["lat_max"]]
    lons = [bbox["lon_min"], (bbox["lon_min"] + bbox["lon_max"]) / 2, bbox["lon_max"]]
    pm25_vals = [
        [145.0, 95.0, 65.0],
        [110.0, 75.0, 45.0],
        [80.0,  50.0, 25.0],
    ]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            pm25 = pm25_vals[i][j]
            rows.append({
                "station_id": f"demo_{lat:.3f}_{lon:.3f}",
                "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "pm25_ugm3": pm25,
                "pm10_ugm3": round(pm25 * 1.6, 1),
                "european_aqi": None,
                "data_source": "openmeteo_aq",
                "quality_flag": "synthetic",
                "station_type": "background",
            })
    return pd.DataFrame(rows)


# ── Station-type filtering ──────────────────────────────────────────────────

def _apply_station_filter(aq_df: pd.DataFrame, station_type_filter: str) -> pd.DataFrame:
    if station_type_filter == "All" or aq_df.empty:
        return aq_df
    if "station_type" not in aq_df.columns:
        return aq_df
    filt = station_type_filter.lower()
    return aq_df[aq_df["station_type"].str.lower().str.contains(filt, na=False)]


# ── Colour helpers ─────────────────────────────────────────────────────────

def _aqi_emoji(cat: str) -> str:
    return {
        "good": "🟢",
        "satisfactory": "🟡",
        "moderate": "🟠",
        "poor": "🔴",
        "very_poor": "🟣",
        "severe": "⚫",
    }.get(cat, "⚪")


_STATUS_STYLE = {
    "live":        ("●", "#1a9e3f", "#e6f4ea", "LIVE"),
    "stale":       ("●", "#b45309", "#fef3c7", "STALE"),
    "unavailable": ("●", "#b91c1c", "#fee2e2", "NO DATA"),
}


def _status_badge(status: str) -> str:
    dot, color, bg, label = _STATUS_STYLE.get(status, ("●", "#6b7280", "#f3f4f6", status.upper()))
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:{bg};color:{color};border:1px solid {color};'
        f'border-radius:4px;padding:1px 8px;font-size:11px;font-weight:600;'
        f'font-family:monospace;white-space:nowrap;">'
        f'{dot} {label}</span>'
    )


def _render_evidence_chain(packet: dict) -> None:
    src_status = packet.get("data_source_status") or []
    trace = packet.get("computation_trace") or {}

    with st.expander("How was this score computed?", expanded=False):
        st.markdown("**Data sources**", unsafe_allow_html=False)
        if src_status:
            rows_html = ""
            for s in src_status:
                badge = _status_badge(s.get("status", "unavailable"))
                label = s.get("label", s.get("source", "—"))
                detail = s.get("detail", "")
                rows_html += (
                    f'<tr>'
                    f'<td style="padding:4px 10px 4px 0;white-space:nowrap;">{badge}</td>'
                    f'<td style="padding:4px 12px 4px 0;font-weight:600;white-space:nowrap;">{label}</td>'
                    f'<td style="padding:4px 0;color:#6b7280;font-size:12px;">{detail}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<table style="border-collapse:collapse;font-size:13px;width:100%;'
                f'margin-bottom:12px;">{rows_html}</table>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No source status available.")

        st.markdown("**Features used**")
        ev = packet.get("evidence") or {}
        inputs = ev.get("inputs") or []
        if inputs:
            feat_rows = []
            for inp in inputs:
                feat_rows.append({
                    "Feature": inp.get("name", "—"),
                    "Value": inp.get("value"),
                    "Unit": inp.get("unit", ""),
                })
            st.dataframe(pd.DataFrame(feat_rows), hide_index=True, use_container_width=True)

        if trace:
            st.markdown("**Scoring formula**")
            st.code(trace.get("formula", ""), language=None)
            steps = trace.get("steps") or []
            if steps:
                step_rows = []
                for step in steps:
                    inp_str = ", ".join(
                        f"{k}={v}" for k, v in (step.get("inputs") or {}).items()
                    )
                    step_rows.append({
                        "Step": step.get("name", "—"),
                        "Formula": step.get("formula", "—"),
                        "Inputs": inp_str,
                        "Value": step.get("value"),
                        "Weight": step.get("weight", ""),
                    })
                st.dataframe(pd.DataFrame(step_rows), hide_index=True, use_container_width=True)
            algo = trace.get("algorithm", "")
            if algo:
                st.caption(f"Algorithm: {algo} · Data quality: {trace.get('data_quality_flag', '—')}")


# ── Map rendering ──────────────────────────────────────────────────────────

def _render_aq_map(
    dashboard: dict,
    aq_df: pd.DataFrame,
    fire_df: pd.DataFrame,
    aod_map: dict,
    bbox: dict,
    h3_res: int,
    show_aod: bool,
    show_fires: bool,
) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No H3 cells to display.")
        return

    # ── Layer 1: AQ grid ─────────────────────────────────────────────────
    grid_df = pd.DataFrame([
        {
            "h3_id":        c["h3_id"],
            "aqi_score":    c.get("aqi_score") or 0.0,
            "aqi_category": c.get("aqi_category", "good"),
            "color":        _AQI_COLOR_MAP.get(c.get("aqi_category", "good"), [128, 128, 128, 150]),
            "station_id":   "",
            "pm25_ugm3":    "",
            "who_category": "",
        }
        for c in cells
    ])

    aq_layer = pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(grid_df),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[80, 80, 80],
        line_width_min_pixels=0,
        pickable=True,
        extruded=False,
        opacity=0.75,
        id="aq_grid",
    )
    layers = [aq_layer]

    # ── Layer 2: MODIS AOD overlay ────────────────────────────────────────
    if show_aod and aod_map:
        aod_df = pd.DataFrame([
            {
                "h3_id": h3_id,
                "aod":   aod_val,
                "color": _aod_color(aod_val),
                "aod_label": f"{aod_val:.3f}",
            }
            for h3_id, aod_val in aod_map.items()
        ])
        aod_layer = pdk.Layer(
            "H3HexagonLayer",
            data=clean_h3_data(aod_df),
            get_hexagon="h3_id",
            get_fill_color="color",
            line_width_min_pixels=0,
            pickable=True,
            extruded=False,
            opacity=0.5,
            id="aod_overlay",
        )
        layers.append(aod_layer)

    # ── Layer 3: Station scatter points ───────────────────────────────────
    cell_lookup = {c["h3_id"]: c for c in cells}
    if not aq_df.empty and "latitude" in aq_df.columns:
        try:
            import h3
            def _station_row(row):
                cell = h3.latlng_to_cell(row["latitude"], row["longitude"], h3_res)
                ci = cell_lookup.get(cell, {})
                pm25_raw = row.get("pm25_ugm3")
                pm25_str = "N/A" if pd.isna(pm25_raw) else f"{pm25_raw:.1f}"
                who_cat  = _who_category(float(pm25_raw)) if not pd.isna(pm25_raw) else "—"
                return {
                    "latitude":     row["latitude"],
                    "longitude":    row["longitude"],
                    "station_id":   row.get("station_id", ""),
                    "station_type": row.get("station_type", "—"),
                    "pm25_ugm3":    pm25_str,
                    "h3_id":        cell,
                    "aqi_category": ci.get("aqi_category", ""),
                    "aqi_score":    f"{ci.get('aqi_score', 0):.3f}",
                    "who_category": who_cat,
                }
            aq_pts = pd.DataFrame([_station_row(r) for _, r in aq_df.iterrows()])
        except Exception:
            aq_pts = aq_df[["latitude", "longitude", "pm25_ugm3", "station_id"]].copy()
            aq_pts["h3_id"] = ""
            aq_pts["aqi_category"] = ""
            aq_pts["aqi_score"] = ""
            aq_pts["who_category"] = ""
            aq_pts["station_type"] = ""

        sample_layer = pdk.Layer(
            "ScatterplotLayer",
            data=clean_h3_data(aq_pts),
            get_position=["longitude", "latitude"],
            get_radius=400,
            radius_min_pixels=5,
            get_fill_color=[30, 100, 220, 180],
            get_line_color=[10, 60, 200, 255],
            line_width_min_pixels=2,
            stroked=True, filled=True, pickable=True,
            id="aq_sample_points",
        )
        layers.append(sample_layer)

    # ── Layer 4: FIRMS fire hotspots ──────────────────────────────────────
    if show_fires and fire_df is not None and not fire_df.empty:
        required = {"latitude", "longitude", "frp"}
        if required.issubset(fire_df.columns):
            fire_pts = pd.DataFrame([
                {
                    "latitude":    float(r["latitude"]),
                    "longitude":   float(r["longitude"]),
                    "frp":         float(r.get("frp") or 0),
                    "radius":      max(300, min(1500, float(r.get("frp") or 5) * 40)),
                    "color":       [255, 80, 0, 220] if r.get("within_bbox") else [255, 160, 0, 180],
                    "confidence":  str(r.get("detection_confidence", "—")),
                    "acq_date":    str(r.get("acq_date", "")),
                    "satellite":   str(r.get("satellite", "VIIRS")),
                    "location":    "city" if r.get("within_bbox") else "airshed",
                }
                for _, r in fire_df.iterrows()
                if float(r.get("frp") or 0) >= 5
            ])
            if not fire_pts.empty:
                fire_layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=clean_h3_data(fire_pts),
                    get_position=["longitude", "latitude"],
                    get_radius="radius",
                    radius_min_pixels=6,
                    get_fill_color="color",
                    get_line_color=[200, 40, 0, 255],
                    line_width_min_pixels=2,
                    stroked=True, filled=True, pickable=True,
                    id="fire_hotspots",
                )
                layers.append(fire_layer)

    # ── View state ────────────────────────────────────────────────────────
    center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    center_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    zoom = {7: 9, 8: 10, 9: 11, 10: 12}.get(h3_res, 11)
    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    tooltip = {
        "html": """
            <div style="font-family:sans-serif;font-size:12px;padding:6px 10px;
                        background:rgba(0,0,0,0.88);color:#fff;border-radius:4px;max-width:300px;">
              <b>H3:</b> {h3_id}<br/>
              <b>India AQI:</b> {aqi_category} &nbsp; <b>Score:</b> {aqi_score}<br/>
              <b>WHO 2021:</b> {who_category}<br/>
              <b>Station:</b> {station_id} ({station_type})<br/>
              <b>PM2.5:</b> {pm25_ugm3} µg/m³<br/>
              <span style="color:#f97316;font-weight:600;">{location} 🔥 FRP {frp} MW ({satellite}, {acq_date})</span>
            </div>
        """,
        "style": {"color": "white"},
    }

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip=tooltip,
    )

    col_map, col_legend = st.columns([4, 1])

    with col_map:
        st.pydeck_chart(deck, use_container_width=True, height=520)

    with col_legend:
        st.markdown("**India NAAQS**")
        st.markdown(
            """
            <div style="font-size:11px;line-height:1.9;">
            <span style="display:inline-block;width:12px;height:12px;background:rgba(34,139,34,0.7);
                         margin-right:6px;border-radius:2px;"></span>Good (0–30)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(144,238,0,0.7);
                         margin-right:6px;border-radius:2px;"></span>Satisfactory (30–60)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,215,0,0.75);
                         margin-right:6px;border-radius:2px;"></span>Moderate (60–90)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,140,0,0.8);
                         margin-right:6px;border-radius:2px;"></span>Poor (90–120)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(200,40,40,0.85);
                         margin-right:6px;border-radius:2px;"></span>Very Poor (120–250)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(128,0,32,0.9);
                         margin-right:6px;border-radius:2px;"></span>Severe (&gt;250)<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("**WHO 2021 (PM2.5)**")
        st.markdown(
            """
            <div style="font-size:10px;line-height:1.7;color:#9ca3af;">
            Good ≤5 µg/m³<br/>
            Target ≤10<br/>
            Moderate ≤15<br/>
            Poor ≤25<br/>
            Very Poor ≤75<br/>
            Hazardous &gt;75
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div style="font-size:11px;line-height:1.9;margin-top:6px;">
            <span style="display:inline-block;width:12px;height:12px;background:rgba(30,100,220,0.7);
                         border:2px solid #0a3cc8;margin-right:6px;border-radius:50%;"></span>AQ station<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,80,0,0.85);
                         border:2px solid #c82800;margin-right:6px;border-radius:50%;"></span>Fire (city)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,160,0,0.7);
                         border:2px solid #c87000;margin-right:6px;border-radius:50%;"></span>Fire (airshed)
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Hover for details.")
        n_severe = sum(1 for c in cells if c.get("aqi_category") == "severe")
        n_vpoor  = sum(1 for c in cells if c.get("aqi_category") == "very_poor")
        n_poor   = sum(1 for c in cells if c.get("aqi_category") == "poor")
        st.markdown(f"**{n_severe}** severe  \n**{n_vpoor}** very poor  \n**{n_poor}** poor")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_air_panel() -> None:
    city_id, bbox, live, station_type_filter = _city_selector()
    h3_res = _DEFAULT_H3_RES

    render_domain_header(
        title="Air Quality Review",
        caption=(
            "Per-H3-cell India AQI scores based on IDW-interpolated PM2.5 from "
            "OpenMeteo Air Quality API. Review-support only."
        ),
        primary_alert=None,
    )

    # ── Map layer toggles ──────────────────────────────────────────────────
    c_aod, c_fire = st.columns(2)
    with c_aod:
        show_aod   = st.toggle("MODIS AOD overlay", value=False, key="air_show_aod",
                               help="Aerosol Optical Depth from MODIS MAIAC (requires GEE_PROJECT)")
    with c_fire:
        show_fires = st.toggle("FIRMS fire hotspots", value=True, key="air_show_fires",
                               help="NASA VIIRS active fire detections (requires FIRMS_API_KEY)")

    # ── Load data ──────────────────────────────────────────────────────────
    with st.spinner("Building air quality grid…"):
        if live:
            aq_df = _load_live_aq(
                city_id, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                lookback_hours=_LOOKBACK_HOURS,
            )
            if aq_df.empty:
                st.warning("OpenMeteo AQ returned no data. Falling back to synthetic demo data.")
                aq_df = _synthetic_aq(bbox)
                data_note = "synthetic (OpenMeteo AQ call failed)"
            else:
                data_note = f"live ({len(aq_df)} records)"
        else:
            aq_df = _synthetic_aq(bbox)
            data_note = "synthetic demo"

        # Apply station-type filter
        aq_filtered = _apply_station_filter(aq_df, station_type_filter)
        if len(aq_filtered) < len(aq_df):
            data_note += f" [{station_type_filter} stations only, {len(aq_filtered)}/{len(aq_df)}]"
        aq_df_for_grid = aq_filtered if not aq_filtered.empty else aq_df

        dashboard = build_air_quality_dashboard(
            aq_df=aq_df_for_grid,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )

        # Fire hotspots
        fire_df = pd.DataFrame()
        if live and show_fires:
            fire_df = _load_fire_data(
                bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"]
            )

        # MODIS AOD
        aod_map: dict = {}
        if live and show_aod:
            cells = dashboard.get("risk_cells", [])
            if cells:
                h3_ids = tuple(sorted(c["h3_id"] for c in cells))
                aod_map = _load_aod(
                    h3_ids,
                    bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                )

        if live:
            try:
                from urban_platform.decision_events import emit_fire_decisions
                if not fire_df.empty:
                    emit_fire_decisions(fire_df, city_id=city_id, bbox=bbox)
            except Exception:
                pass

    # Schema validation
    validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "air_quality_dashboard.v1.schema.json").resolve())
    ).validate(dashboard)

    # ── Context metrics ────────────────────────────────────────────────────
    rs = dashboard.get("risk_summary", {})
    cells = dashboard.get("risk_cells", [])
    summary = dashboard.get("summary", {})

    fire_count = 0
    fire_in_city = 0
    if not fire_df.empty and "frp" in fire_df.columns:
        sig = fire_df[fire_df["frp"] >= 5]
        fire_count = len(sig)
        fire_in_city = int(sig["within_bbox"].sum()) if "within_bbox" in sig.columns else 0

    aod_avg = f"{sum(aod_map.values()) / len(aod_map):.3f}" if aod_map else "—"

    render_context_metrics(
        ("City", city_id),
        ("Total cells", str(len(cells))),
        ("Poor+ cells", str(sum(1 for c in cells if c.get("aqi_category") in ("poor", "very_poor", "severe")))),
        ("Overall AQI category", str(rs.get("overall_aqi_category", "—"))),
        ("Max PM2.5 (µg/m³)", f"{summary.get('max_pm25_ugm3') or 0:.1f}"),
        ("Fire hotspots", f"{fire_in_city} city / {fire_count - fire_in_city} airshed"),
        ("Avg MODIS AOD", aod_avg),
        ("Data source", data_note),
        ("Quality flag", dashboard.get("data_quality_flag", "—")),
    )

    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{humanize_warning_id(str(w.get('warning_id', '')))}** — {w.get('message', '')}"
        (st.error if sev == "error" else st.warning if sev == "warning" else st.info)(msg)

    if fire_count > 0:
        st.warning(
            f"**{fire_in_city} active fire(s) detected within city boundary** "
            f"and {fire_count - fire_in_city} in surrounding airshed (VIIRS, last 24h). "
            "Fire smoke may significantly elevate PM2.5 and PM10 readings."
        )

    st.divider()

    # ── Tabs ───────────────────────────────────────────────────────────────
    t_map, t_browse, t_fire = st.tabs(
        ["🗺️ Map", "📊 AQI grid", "🔥 Fire events"]
    )

    with t_map:
        _render_aq_map(
            dashboard, aq_df_for_grid, fire_df, aod_map,
            bbox=bbox, h3_res=h3_res,
            show_aod=show_aod, show_fires=show_fires,
        )
        caption_parts = [
            "**Blue circles** are AQ measurement stations.",
            "H3 cells coloured by India AQI category.",
        ]
        if show_fires:
            caption_parts.append(
                "**Orange/red circles** are VIIRS fire hotspots — size proportional to fire radiative power (FRP)."
            )
        if show_aod and aod_map:
            caption_parts.append(
                "**AOD overlay** shows MODIS MAIAC aerosol optical depth (green=low → red=high)."
            )
        st.caption(" ".join(caption_parts))

    with t_browse:
        render_section_title("Air quality grid")
        if cells:
            # Add WHO category to grid table
            rows = []
            for c in cells:
                pm25 = c.get("aqi_score") or 0
                rows.append({
                    "AQI": _aqi_emoji(c.get("aqi_category", "good")),
                    "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                    "India AQI": c.get("aqi_category", "—"),
                    "AQI score": f"{c.get('aqi_score') or c.get('confidence_score', 0) or 0:.3f}",
                    "WHO 2021": _who_category(pm25 * 250 / 1.0) if pm25 else "—",  # score→µg/m³ approx
                    "AOD": f"{aod_map.get(c['h3_id'], 0):.3f}" if aod_map else "—",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("AQI score distribution")
            score_df = pd.DataFrame({"aqi_score": [c.get("confidence_score", 0) or 0 for c in cells]})
            st.bar_chart(score_df, y="aqi_score", height=200)
        else:
            st.info("No H3 cells generated.")

    with t_fire:
        render_section_title("FIRMS fire hotspots (last 24h)")
        if fire_df.empty:
            if not live:
                st.info("Enable 'Live data' to fetch FIRMS fire hotspots.")
            else:
                st.info("No active fire detections in city or airshed (or FIRMS_API_KEY not set).")
        else:
            sig = fire_df[fire_df.get("frp", pd.Series(dtype=float)) >= 5] if "frp" in fire_df.columns else fire_df
            if sig.empty:
                st.info("No significant fire detections (FRP ≥ 5 MW).")
            else:
                fire_rows = []
                for _, r in sig.iterrows():
                    fire_rows.append({
                        "Date": str(r.get("acq_date", "")),
                        "Lat": f"{float(r['latitude']):.4f}",
                        "Lon": f"{float(r['longitude']):.4f}",
                        "FRP (MW)": f"{float(r.get('frp', 0)):.1f}",
                        "Confidence %": int(r.get("detection_confidence", 0)),
                        "Satellite": str(r.get("satellite", "VIIRS")),
                        "Location": "City" if r.get("within_bbox") else "Airshed",
                    })
                st.dataframe(pd.DataFrame(fire_rows), hide_index=True, use_container_width=True)
                st.caption(
                    "Fire smoke typically elevates PM2.5 by 30–100 µg/m³ within 50 km downwind. "
                    "Decision Objects have been emitted for all detections with FRP ≥ 5 MW."
                )

    render_technical_json_expander(
        title="Technical: Raw contract payload",
        payload={"air_quality_dashboard": dashboard},
    )
