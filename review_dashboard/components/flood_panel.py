"""Flood Risk Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.applications.flood.flood_pipeline import (
    build_flood_risk_dashboard,
    build_flood_decision_packets,
)
from urban_platform.connectors.flood import fetch_rainfall_observations

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


_LOOKBACK_HOURS = 3

_CITIES = {
    "Bangalore (demo)": ("bangalore_demo", dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)),
    "Delhi (demo)":     ("delhi_demo",     dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30)),
    "Mumbai (demo)":    ("mumbai_demo",    dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00)),
}


# ── Sidebar ────────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, int, bool]:
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        city_label = st.selectbox("City", list(_CITIES.keys()), key="flood_city_selector")
    with c2:
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="flood_h3_res",
                           help="Higher = smaller cells, more detail, slower")
    with c3:
        live = st.toggle("Live data (cached ≤1h)", value=False, key="flood_live_toggle",
                         help="Uses observation store cache if data is <1h old, otherwise calls OpenMeteo")
    city_id, bbox = _CITIES[city_label]
    return city_id, bbox, h3_res, live


# ── Data loading ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Loading rainfall data…")
def _load_live_rainfall(city_id: str, lat_min: float, lon_min: float,
                        lat_max: float, lon_max: float, lookback_hours: int) -> pd.DataFrame:
    try:
        from urban_platform.observation_store import ObservationStoreReader, to_wide
        cached = ObservationStoreReader().read_recent("flood", city_id, max_age_hours=1)
        if not cached.empty:
            return to_wide(cached)
    except Exception:
        pass
    return fetch_rainfall_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_hours=lookback_hours,
        city_id=city_id,
    )


def _synthetic_rainfall(bbox: dict) -> pd.DataFrame:
    """3×3 grid of synthetic rainfall matching OpenMeteo's sampling pattern.

    NE corner is the storm cell (45 mm/hr), creating a flood risk gradient
    across the city with two elevated-risk clusters at center and NE corner.
    """
    lats = [bbox["lat_min"], (bbox["lat_min"] + bbox["lat_max"]) / 2, bbox["lat_max"]]
    lons = [bbox["lon_min"], (bbox["lon_min"] + bbox["lon_max"]) / 2, bbox["lon_max"]]
    # [lat_row][lon_col]: south→north rows, west→east columns
    intensities = [
        [0.5,  2.0,  5.0],   # south: mostly dry
        [1.5,  4.0, 15.0],   # center: moderate in NE direction
        [3.0, 18.0, 45.0],   # north: heavy storm cell at NE corner
    ]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            r = intensities[i][j]
            rows.append({
                "station_id": f"demo_{lat:.3f}_{lon:.3f}",
                "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "rainfall_intensity_mm_per_hr": r,
                "rainfall_accumulation_3h_mm": round(r * 3, 1),
                "data_source": "openmeteo",
                "quality_flag": "synthetic",
            })
    return pd.DataFrame(rows)


def _synthetic_incidents(bbox: dict) -> pd.DataFrame:
    """A few waterlogging incidents near the storm cell (NE corner)."""
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]
    lat_mid = (bbox["lat_min"] + lat_max) / 2
    lon_mid = (bbox["lon_min"] + lon_max) / 2
    return pd.DataFrame([
        {"latitude": lat_max - 0.01, "longitude": lon_max - 0.02,
         "severity": "high", "incident_type": "waterlogging", "quality_flag": "unverified"},
        {"latitude": lat_max - 0.03, "longitude": lon_max - 0.05,
         "severity": "high", "incident_type": "road_flooding", "quality_flag": "unverified"},
        {"latitude": lat_mid + 0.02, "longitude": lon_mid + 0.03,
         "severity": "moderate", "incident_type": "waterlogging", "quality_flag": "unverified"},
    ])


def _synthetic_assets(bbox: dict) -> pd.DataFrame:
    """Distributed drainage assets across the city."""
    lat_min, lat_max = bbox["lat_min"], bbox["lat_max"]
    lon_min, lon_max = bbox["lon_min"], bbox["lon_max"]
    lat_mid = (lat_min + lat_max) / 2
    lon_mid = (lon_min + lon_max) / 2
    return pd.DataFrame([
        {"latitude": lat_mid - 0.04, "longitude": lon_mid - 0.03, "asset_type": "drain"},
        {"latitude": lat_mid + 0.05, "longitude": lon_mid - 0.04, "asset_type": "drain"},
        {"latitude": lat_min + 0.03, "longitude": lon_min + 0.05, "asset_type": "pump_station"},
        {"latitude": lat_max - 0.05, "longitude": lon_min + 0.04, "asset_type": "drain"},
    ])


# ── Colour helpers ─────────────────────────────────────────────────────────

def _flood_risk_emoji(level: str) -> str:
    return {"low": "🟢", "moderate": "🟡", "high": "🟠", "severe": "🔴"}.get(level, "⚪")


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


# ── Map rendering ──────────────────────────────────────────────────────────

_FLOOD_COLOR_MAP = {
    "low":      [30, 120, 220, 160],
    "moderate": [240, 170, 30, 180],
    "high":     [220, 60, 20, 200],
    "severe":   [140, 10, 10, 220],
}


def _render_flood_map(
    dashboard: dict,
    rainfall_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    assets_df: pd.DataFrame,
    bbox: dict,
    h3_res: int,
) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No H3 cells to display.")
        return

    # ── Layer 1: Flood risk grid (all cells, coloured by risk level) ──────
    grid_df = pd.DataFrame([
        {
            "h3_id": c["h3_id"],
            "flood_risk_score": c.get("flood_risk_score") or 0.0,
            "risk_level": c.get("risk_level", "low"),
            "rainfall_mm_per_hr": c.get("rainfall_mm_per_hr"),
            "incident_count": c.get("incident_count", 0),
            "color": _FLOOD_COLOR_MAP.get(c.get("risk_level", "low"), [30, 120, 220, 160]),
        }
        for c in cells
    ])

    risk_layer = pdk.Layer(
        "H3HexagonLayer",
        data=grid_df,
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[80, 80, 80],
        line_width_min_pixels=0,
        pickable=True,
        extruded=False,
        opacity=0.75,
        id="flood_grid",
    )
    layers = [risk_layer]

    # ── Layer 2: Rainfall IDW sample points (blue circles) ────────────────
    # OpenMeteo is a forecast API queried at a 3×3 virtual grid — not rain gauges.
    if not rainfall_df.empty and "latitude" in rainfall_df.columns:
        rain_layer = pdk.Layer(
            "ScatterplotLayer",
            data=rainfall_df[["latitude", "longitude",
                               "rainfall_intensity_mm_per_hr", "station_id"]].copy(),
            get_position=["longitude", "latitude"],
            get_radius=400,
            radius_min_pixels=5,
            get_fill_color=[30, 100, 220, 180],
            get_line_color=[10, 60, 200, 255],
            line_width_min_pixels=2,
            stroked=True, filled=True, pickable=True,
            id="rainfall_points",
        )
        layers.append(rain_layer)

    # ── Layer 3: Waterlogging incidents (red/orange circles) ──────────────
    if not incidents_df.empty and "latitude" in incidents_df.columns:
        _sev_color = {"high": [220, 40, 20, 220], "moderate": [240, 140, 20, 200]}
        inc_df = incidents_df.copy()
        inc_df["color"] = inc_df["severity"].apply(
            lambda s: _sev_color.get(str(s).lower(), [200, 100, 20, 180])
        )
        inc_layer = pdk.Layer(
            "ScatterplotLayer",
            data=inc_df,
            get_position=["longitude", "latitude"],
            get_radius=600,
            radius_min_pixels=7,
            get_fill_color="color",
            get_line_color=[100, 0, 0, 255],
            line_width_min_pixels=2,
            stroked=True, filled=True, pickable=True,
            id="incidents",
        )
        layers.append(inc_layer)

    # ── Layer 4: Drainage assets (green circles) ──────────────────────────
    if not assets_df.empty and "latitude" in assets_df.columns:
        asset_layer = pdk.Layer(
            "ScatterplotLayer",
            data=assets_df,
            get_position=["longitude", "latitude"],
            get_radius=300,
            radius_min_pixels=4,
            get_fill_color=[20, 180, 80, 180],
            get_line_color=[10, 100, 40, 255],
            line_width_min_pixels=2,
            stroked=True, filled=True, pickable=True,
            id="assets",
        )
        layers.append(asset_layer)

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
              <b>Risk level:</b> {risk_level} &nbsp; <b>Score:</b> {flood_risk_score}<br/>
              <b>Rainfall:</b> {rainfall_mm_per_hr} mm/hr<br/>
              <b>Incidents:</b> {incident_count}<br/>
              <i style="color:#6ab0ff;">Station {station_id}: {rainfall_intensity_mm_per_hr} mm/hr</i>
            </div>
        """,
        "style": {"color": "white"},
    }

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="light",
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
            <span style="display:inline-block;width:12px;height:12px;background:rgba(30,120,220,0.65);
                         margin-right:6px;border-radius:2px;"></span>Low risk<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(240,170,30,0.75);
                         margin-right:6px;border-radius:2px;"></span>Moderate risk<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(220,60,20,0.8);
                         margin-right:6px;border-radius:2px;"></span>High risk<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(140,10,10,0.9);
                         margin-right:6px;border-radius:2px;"></span>Severe risk<br/>
            <hr style="margin:6px 0;"/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(30,100,220,0.7);
                         border:2px solid #0a3cc8;margin-right:6px;border-radius:50%;"></span>Rainfall IDW point<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(220,40,20,0.85);
                         border:2px solid #640000;margin-right:6px;border-radius:50%;"></span>Waterlogging incident<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(20,180,80,0.7);
                         border:2px solid #0a6428;margin-right:6px;border-radius:50%;"></span>Drainage asset<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Hover for details.")
        n_severe = sum(1 for c in cells if c.get("risk_level") == "severe")
        n_high = sum(1 for c in cells if c.get("risk_level") == "high")
        st.markdown(f"**{n_severe}** severe cells  \n**{n_high}** high-risk cells")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_flood_panel() -> None:
    city_id, bbox, h3_res, live = _city_selector()

    render_domain_header(
        title="Flood Risk Review",
        caption=(
            "Per-H3-cell flood risk scores combining IDW-interpolated rainfall intensity, "
            "waterlogging incidents, and drainage asset coverage. Review-support only."
        ),
        primary_alert=None,
    )

    # ── Load data ──────────────────────────────────────────────────────────
    with st.spinner("Building flood risk grid…"):
        if live:
            rainfall_df = _load_live_rainfall(
                city_id, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                lookback_hours=_LOOKBACK_HOURS,
            )
            if rainfall_df.empty:
                st.warning("OpenMeteo returned no rainfall data. Falling back to synthetic demo data.")
                rainfall_df = _synthetic_rainfall(bbox)
                data_note = "synthetic (OpenMeteo call failed)"
            else:
                data_note = f"live OpenMeteo ({len(rainfall_df)} records)"
        else:
            rainfall_df = _synthetic_rainfall(bbox)
            data_note = "synthetic demo (toggle 'Fetch live data' in sidebar for real rainfall)"

        incidents_df = _synthetic_incidents(bbox)
        assets_df = _synthetic_assets(bbox)

        dashboard = build_flood_risk_dashboard(
            rainfall_df=rainfall_df,
            incidents_df=incidents_df,
            assets_df=assets_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )
        packets = build_flood_decision_packets(
            rainfall_df=rainfall_df,
            incidents_df=incidents_df,
            assets_df=assets_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
            top_n=10,
        )

    # Schema validation
    validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve())
    ).validate(dashboard)
    for p in packets:
        validator_for_schema_file(
            str((SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve())
        ).validate(p)

    # ── Context metrics ────────────────────────────────────────────────────
    rs = dashboard.get("risk_summary", {})
    cells = dashboard.get("risk_cells", [])
    render_context_metrics(
        ("City", city_id),
        ("H3 resolution", str(h3_res)),
        ("Total cells", str(len(cells))),
        ("Severe/high cells", str(sum(1 for c in cells if c.get("risk_level") in ("severe", "high")))),
        ("Overall risk", str(rs.get("overall_risk_level", "—"))),
        ("Data quality flag", dashboard.get("data_quality_flag", "—")),
        ("Packets reviewed", str(len(packets))),
        ("Data source", data_note),
    )

    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{humanize_warning_id(str(w.get('warning_id', '')))}** — {w.get('message', '')}"
        (st.error if sev == "high" else st.warning if sev == "medium" else st.info)(msg)

    st.divider()

    # ── Tabs: Map / Grid table / Decision packets ──────────────────────────
    t_map, t_browse, t_detail = st.tabs(["🗺️ Map", "📊 Risk grid", "🎯 Decision packets"])

    with t_map:
        _render_flood_map(dashboard, rainfall_df, incidents_df, assets_df, bbox=bbox, h3_res=h3_res)
        st.caption(
            "**Blue circles** are IDW sample points — virtual grid coordinates queried from "
            "the OpenMeteo forecast API (or synthesised for demo), not physical rain gauges. "
            "**Red/orange circles** are reported waterlogging incidents. "
            "**Green circles** are drainage infrastructure assets. "
            "H3 cells are coloured by flood risk score: "
            "blue (low) → orange (moderate) → red (high) → dark red (severe)."
        )

    with t_browse:
        render_section_title("Flood risk grid")
        if cells:
            rows = [
                {
                    "Risk": _flood_risk_emoji(c.get("risk_level", "low")),
                    "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                    "Rainfall (mm/hr)": c.get("rainfall_mm_per_hr"),
                    "Incidents": c.get("incident_count", 0),
                    "Drainage assets": c.get("asset_count", 0),
                    "Risk score": f"{c.get('flood_risk_score', 0) or 0:.3f}",
                    "Risk level": c.get("risk_level", "—"),
                }
                for c in cells
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("Risk score distribution")
            score_df = pd.DataFrame({"flood_risk_score": [c.get("flood_risk_score", 0) or 0 for c in cells]})
            st.bar_chart(score_df, y="flood_risk_score", height=200)
        else:
            st.info("No H3 cells generated.")

    with t_detail:
        render_section_title("Decision packets (top-10 highest risk)")
        if not packets:
            st.info("No decision packets generated.")
        else:
            rows = [
                {
                    "Packet ID": str(p.get("packet_id") or ""),
                    "H3 cell": str(p.get("h3_id") or "")[:16] + "…",
                    "Risk level": str((p.get("risk_assessment") or {}).get("risk_level") or "—"),
                    "Field verification": "Yes" if p.get("field_verification_required") else "No",
                    "Rec. allowed": "Yes" if (p.get("confidence") or {}).get("recommendation_allowed") else "No",
                }
                for p in packets
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("Drill-down")
            ids = [str(p.get("packet_id")) for p in packets if p.get("packet_id")]
            sel = st.selectbox("Select a packet for details", options=ids, index=0,
                               key="flood_selected_packet")
            selected = next((p for p in packets if str(p.get("packet_id")) == sel), None)
            if selected:
                ra = selected.get("risk_assessment") or {}
                conf = selected.get("confidence") or {}
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Risk level", str(ra.get("risk_level", "—")))
                    st.metric("Primary driver", str(ra.get("primary_driver", "—")))
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
        payload={"flood_risk_dashboard": dashboard, "flood_decision_packets": packets},
    )
