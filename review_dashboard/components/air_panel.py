"""Air Quality Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.applications.air.air_pipeline import (
    build_air_quality_dashboard,
    build_air_quality_decision_packets,
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

_CITIES = {
    "Bangalore (demo)": ("bangalore_demo", dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)),
    "Delhi (demo)":     ("delhi_demo",     dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30)),
    "Mumbai (demo)":    ("mumbai_demo",    dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00)),
}


# ── Sidebar ────────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, int, bool]:
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        city_label = st.selectbox("City", list(_CITIES.keys()), key="air_city_selector")
    with c2:
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="air_h3_res",
                           help="Higher = smaller cells, more detail, slower")
    with c3:
        live = st.toggle("Live data (cached ≤1h)", value=False, key="air_live_toggle",
                         help="Uses observation store cache if data is <1h old, otherwise calls OpenMeteo AQ")
    city_id, bbox = _CITIES[city_label]
    return city_id, bbox, h3_res, live


# ── Data loading ───────────────────────────────────────────────────────────

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


def _synthetic_aq(bbox: dict) -> pd.DataFrame:
    """3×3 grid of synthetic AQ observations.

    SW corner industrial (heavy pollution), NE corner cleaner.
    """
    lats = [bbox["lat_min"], (bbox["lat_min"] + bbox["lat_max"]) / 2, bbox["lat_max"]]
    lons = [bbox["lon_min"], (bbox["lon_min"] + bbox["lon_max"]) / 2, bbox["lon_max"]]
    # [lat_row][lon_col]: south→north rows, west→east columns
    pm25_vals = [
        [145.0, 95.0, 65.0],   # south: very_poor SW, poor, moderate
        [110.0, 75.0, 45.0],   # center: poor, moderate, satisfactory
        [80.0,  50.0, 25.0],   # north: poor, satisfactory, good NE corner
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
            })
    return pd.DataFrame(rows)


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
    """Collapsible expander: data sources (with status badges) → features → formula."""
    src_status = packet.get("data_source_status") or []
    trace = packet.get("computation_trace") or {}

    with st.expander("How was this score computed?", expanded=False):
        # ── Data sources ──────────────────────────────────────────────────
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

        # ── Features used ─────────────────────────────────────────────────
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

        # ── Scoring formula ───────────────────────────────────────────────
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


# ── AQI color map ──────────────────────────────────────────────────────────

_AQI_COLOR_MAP = {
    "good":         [34, 139, 34, 180],
    "satisfactory": [144, 238, 0, 180],
    "moderate":     [255, 215, 0, 190],
    "poor":         [255, 140, 0, 200],
    "very_poor":    [200, 40, 40, 210],
    "severe":       [128, 0, 32, 230],
}


# ── Map rendering ──────────────────────────────────────────────────────────

def _render_aq_map(
    dashboard: dict,
    aq_df: pd.DataFrame,
    bbox: dict,
    h3_res: int,
) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No H3 cells to display.")
        return

    # ── Layer 1: AQ grid (all cells, coloured by AQI category) ───────────
    grid_df = pd.DataFrame([
        {
            "h3_id": c["h3_id"],
            "aqi_score": c.get("aqi_score") or 0.0,
            "aqi_category": c.get("aqi_category", "good"),
            "color": _AQI_COLOR_MAP.get(c.get("aqi_category", "good"), [128, 128, 128, 150]),
        }
        for c in cells
    ])

    aq_layer = pdk.Layer(
        "H3HexagonLayer",
        data=grid_df,
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

    # ── Layer 2: AQ IDW sample points (blue circles) ──────────────────────
    if not aq_df.empty and "latitude" in aq_df.columns:
        aq_pts = aq_df[["latitude", "longitude", "pm25_ugm3", "station_id"]].copy()
        sample_layer = pdk.Layer(
            "ScatterplotLayer",
            data=aq_pts,
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

    # ── View state: bbox centre + h3_res-appropriate zoom ────────────────
    center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    center_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    zoom = {7: 9, 8: 10, 9: 11, 10: 12}.get(h3_res, 11)
    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    tooltip = {
        "html": """
            <div style="font-family:sans-serif;font-size:12px;padding:4px 8px;
                        background:rgba(0,0,0,0.85);color:#fff;border-radius:4px;max-width:260px;">
              <b>H3:</b> {h3_id}<br/>
              <b>AQI category:</b> {aqi_category} &nbsp; <b>Score:</b> {aqi_score}<br/>
              <i style="color:#6ab0ff;">Station {station_id}: {pm25_ugm3} µg/m³ PM2.5</i>
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
        st.markdown("**Legend**")
        st.markdown(
            """
            <div style="font-size:12px;line-height:1.9;">
            <span style="display:inline-block;width:12px;height:12px;background:rgba(34,139,34,0.7);
                         margin-right:6px;border-radius:2px;"></span>Good (0–30 µg/m³)<br/>
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
            <hr style="margin:6px 0;"/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(30,100,220,0.7);
                         border:2px solid #0a3cc8;margin-right:6px;border-radius:50%;"></span>AQ IDW sample point<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Hover for details.")
        n_severe = sum(1 for c in cells if c.get("aqi_category") == "severe")
        n_vpoor = sum(1 for c in cells if c.get("aqi_category") == "very_poor")
        n_poor = sum(1 for c in cells if c.get("aqi_category") == "poor")
        st.markdown(f"**{n_severe}** severe cells  \n**{n_vpoor}** very poor cells  \n**{n_poor}** poor cells")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_air_panel() -> None:
    city_id, bbox, h3_res, live = _city_selector()

    render_domain_header(
        title="Air Quality Review",
        caption=(
            "Per-H3-cell India AQI scores based on IDW-interpolated PM2.5 from "
            "OpenMeteo Air Quality API. Review-support only."
        ),
        primary_alert=None,
    )

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
                data_note = f"live OpenMeteo AQ ({len(aq_df)} records)"
        else:
            aq_df = _synthetic_aq(bbox)
            data_note = "synthetic demo (toggle 'Fetch live data' in sidebar for real AQ)"

        dashboard = build_air_quality_dashboard(
            aq_df=aq_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )
        packets = build_air_quality_decision_packets(
            aq_df=aq_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
            top_n=10,
        )

    # Schema validation
    validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "air_quality_dashboard.v1.schema.json").resolve())
    ).validate(dashboard)
    for p in packets:
        validator_for_schema_file(
            str((SPEC_ROOT / "consumer_contracts" / "air_quality_decision_packet.v1.schema.json").resolve())
        ).validate(p)

    # ── Context metrics ────────────────────────────────────────────────────
    rs = dashboard.get("risk_summary", {})
    cells = dashboard.get("risk_cells", [])
    summary = dashboard.get("summary", {})
    render_context_metrics(
        ("City", city_id),
        ("H3 resolution", str(h3_res)),
        ("Total cells", str(len(cells))),
        ("Poor+ cells", str(sum(1 for c in cells if c.get("aqi_category") in ("poor", "very_poor", "severe")))),
        ("Overall AQI category", str(rs.get("overall_aqi_category", "—"))),
        ("Max PM2.5 (µg/m³)", f"{summary.get('max_pm25_ugm3') or 0:.1f}"),
        ("Data source", data_note),
        ("Quality flag", dashboard.get("data_quality_flag", "—")),
    )

    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{humanize_warning_id(str(w.get('warning_id', '')))}** — {w.get('message', '')}"
        (st.error if sev == "error" else st.warning if sev == "warning" else st.info)(msg)

    st.divider()

    # ── Tabs: Map / Grid table / Decision packets ──────────────────────────
    t_map, t_browse, t_detail = st.tabs(["🗺️ Map", "📊 AQI grid", "🎯 Decision packets"])

    with t_map:
        _render_aq_map(dashboard, aq_df, bbox=bbox, h3_res=h3_res)
        st.caption(
            "**Blue circles** are IDW sample points — virtual grid coordinates queried from "
            "the OpenMeteo Air Quality API (or synthesised for demo), not physical sensors. "
            "H3 cells are coloured by India AQI category: "
            "green (good) → yellow-green (satisfactory) → yellow (moderate) → "
            "orange (poor) → red (very poor) → maroon (severe)."
        )

    with t_browse:
        render_section_title("Air quality grid")
        if cells:
            rows = [
                {
                    "AQI": _aqi_emoji(c.get("aqi_category", "good")),
                    "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                    "AQI category": c.get("aqi_category", "—"),
                    "AQI score": f"{c.get('aqi_score') or c.get('confidence_score', 0) or 0:.3f}",
                }
                for c in cells
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("AQI score distribution")
            score_df = pd.DataFrame({"aqi_score": [c.get("confidence_score", 0) or 0 for c in cells]})
            st.bar_chart(score_df, y="aqi_score", height=200)
        else:
            st.info("No H3 cells generated.")

    with t_detail:
        render_section_title("Decision packets (top-10 highest AQI)")
        if not packets:
            st.info("No decision packets generated.")
        else:
            rows = [
                {
                    "Packet ID": str(p.get("packet_id") or ""),
                    "H3 cell": str(p.get("h3_id") or "")[:16] + "…",
                    "AQI category": str((p.get("aqi_assessment") or {}).get("aqi_category") or "—"),
                    "Field verification": "Yes" if p.get("field_verification_required") else "No",
                    "Rec. allowed": "Yes" if (p.get("confidence") or {}).get("recommendation_allowed") else "No",
                }
                for p in packets
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("Drill-down")
            ids = [str(p.get("packet_id")) for p in packets if p.get("packet_id")]
            sel = st.selectbox("Select a packet for details", options=ids, index=0,
                               key="air_selected_packet")
            selected = next((p for p in packets if str(p.get("packet_id")) == sel), None)
            if selected:
                aa = selected.get("aqi_assessment") or {}
                conf = selected.get("confidence") or {}
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("AQI category", str(aa.get("aqi_category", "—")))
                    st.metric("Primary pollutant", str(aa.get("primary_pollutant", "—")))
                with col2:
                    st.metric("Confidence score", f"{conf.get('confidence_score', 0):.3f}")
                    st.metric("Field verification required",
                              "Yes" if selected.get("field_verification_required") else "No")

                _render_evidence_chain(selected)

                st.markdown("#### Evidence")
                ev_rows = evidence_inputs_to_rows(selected.get("evidence"))
                if not ev_rows:
                    st.caption("No structured evidence rows.")
                else:
                    st.dataframe(pd.DataFrame(ev_rows), hide_index=True, use_container_width=True)

                rg = selected.get("review_guidance") or {}
                st.markdown("#### Review prompts")
                for q in rg.get("review_prompts") or []:
                    st.markdown(f"- {q}")
                st.markdown("#### When not to act")
                for q in rg.get("when_not_to_act") or []:
                    st.markdown(f"- {q}")

                st.markdown("#### Safety gates")
                gdf = pd.DataFrame(safety_gates_to_rows(selected.get("safety_gates")))
                if gdf.empty:
                    st.caption("No safety gates listed.")
                else:
                    st.dataframe(gdf, hide_index=True, use_container_width=True)

                st.markdown("#### Blocked uses")
                for bu in selected.get("blocked_uses") or []:
                    st.markdown(f"- {humanize_snake_sentence(str(bu))}")

    render_technical_json_expander(
        title="Technical: Raw contract payloads",
        payload={"air_quality_dashboard": dashboard, "air_quality_decision_packets": packets},
    )
