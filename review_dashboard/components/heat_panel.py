"""Heat Risk Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.applications.heat.heat_pipeline import (
    build_heat_risk_dashboard,
    build_intervention_candidates,
)
from urban_platform.connectors.heat.openmeteo import fetch_temperature_observations

from review_dashboard.ui_shell import (
    render_browse_detail_layout,
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from review_dashboard.formatters import humanize_warning_id


_LOOKBACK_DAYS = 1

_CITIES = {
    "Bangalore (demo)": ("bangalore_demo", dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)),
    "Delhi (demo)":     ("delhi_demo",     dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30)),
    "Mumbai (demo)":    ("mumbai_demo",    dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00)),
}


# ── Sidebar ────────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, int, bool]:
    with st.sidebar:
        st.markdown("### Heat Risk Settings")
        city_label = st.selectbox("City", list(_CITIES.keys()), key="heat_city_selector")
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="heat_h3_res",
                           help="Higher = smaller cells, more detail, slower")
        live = st.toggle("Fetch live data from OpenMeteo", value=False, key="heat_live_toggle",
                         help="Real HTTP call to api.open-meteo.com — no API key needed")
    city_id, bbox = _CITIES[city_label]
    return city_id, bbox, h3_res, live


# ── Data loading ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Fetching temperature data from OpenMeteo…")
def _load_live_temperature(city_id: str, lat_min: float, lon_min: float,
                           lat_max: float, lon_max: float, lookback_days: int) -> pd.DataFrame:
    return fetch_temperature_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_days=lookback_days,
    )


def _synthetic_temperature(bbox: dict) -> pd.DataFrame:
    lat_mid = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_mid = (bbox["lon_min"] + bbox["lon_max"]) / 2
    return pd.DataFrame([
        {"station_id": f"demo_{bbox['lat_min']}_{bbox['lon_min']}",
         "latitude": bbox["lat_min"], "longitude": bbox["lon_min"],
         "timestamp": "2026-05-07T06:00:00Z", "temperature_c": 28.0,
         "apparent_temperature_c": 30.5, "relative_humidity_pct": 72.0,
         "data_source": "openmeteo", "quality_flag": "real"},
        {"station_id": f"demo_{lat_mid}_{lon_mid}",
         "latitude": lat_mid, "longitude": lon_mid,
         "timestamp": "2026-05-07T06:00:00Z", "temperature_c": 32.5,
         "apparent_temperature_c": 36.0, "relative_humidity_pct": 60.0,
         "data_source": "openmeteo", "quality_flag": "real"},
        {"station_id": f"demo_{bbox['lat_max']}_{bbox['lon_max']}",
         "latitude": bbox["lat_max"], "longitude": bbox["lon_max"],
         "timestamp": "2026-05-07T06:00:00Z", "temperature_c": 27.5,
         "apparent_temperature_c": 29.5, "relative_humidity_pct": 80.0,
         "data_source": "openmeteo", "quality_flag": "real"},
    ])


# ── Colour helpers ─────────────────────────────────────────────────────────

def _risk_score_to_rgb(score: float) -> list[int]:
    """Continuous green→yellow→red gradient for heat risk score 0–1."""
    s = max(0.0, min(1.0, score))
    if s <= 0.5:
        t = s / 0.5
        r = int(39  + t * (241 - 39))
        g = int(174 + t * (196 - 174))
        b = int(96  + t * (15  - 96))
    else:
        t = (s - 0.5) / 0.5
        r = int(241 + t * (192 - 241))
        g = int(196 + t * (57  - 196))
        b = int(15  + t * (43  - 15))
    return [r, g, b, 180]


def _risk_emoji(score: float) -> str:
    if score >= 0.66:
        return "🔴"
    if score >= 0.33:
        return "🟡"
    return "🟢"


# ── Map rendering ──────────────────────────────────────────────────────────

def _render_heat_map(dashboard: dict, candidates: dict) -> None:
    cells = dashboard.get("heat_cells", [])
    cands = candidates.get("candidates", [])

    if not cells:
        st.info("No H3 cells to display.")
        return

    candidate_ids = {c["h3_id"] for c in cands}

    # ── Layer 1: Heat risk grid (all cells, coloured by risk score) ───────
    grid_df = pd.DataFrame([
        {
            "h3_id": c["h3_id"],
            "heat_risk_score": c.get("heat_risk_score") or 0.0,
            "heat_index_c": c.get("heat_index_c"),
            "uhi_intensity": c.get("uhi_intensity"),
            "green_cover": c.get("green_cover_fraction", 0.0),
            "color": _risk_score_to_rgb(c.get("heat_risk_score") or 0.0),
            "is_candidate": c["h3_id"] in candidate_ids,
        }
        for c in cells
    ])

    heat_layer = pdk.Layer(
        "H3HexagonLayer",
        data=grid_df,
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[80, 80, 80],
        line_width_min_pixels=0,
        pickable=True,
        extruded=False,
        opacity=0.75,
        id="heat_grid",
    )

    # ── Layer 2: Intervention candidates (bright orange outline + taller) ─
    if cands:
        cand_df = pd.DataFrame([
            {
                "h3_id": c["h3_id"],
                "risk_score": c.get("risk_score", 0.0),
                "green_deficit": c.get("green_deficit", 0.0),
                "uhi_intensity": c.get("uhi_intensity"),
                "interventions": ", ".join(c.get("suggested_interventions", [])),
                "rank": i + 1,
            }
            for i, c in enumerate(cands)
        ])

        candidate_layer = pdk.Layer(
            "H3HexagonLayer",
            data=cand_df,
            get_hexagon="h3_id",
            get_fill_color=[255, 140, 0, 40],   # translucent orange fill
            get_line_color=[255, 100, 0, 255],   # solid orange border
            line_width_min_pixels=3,
            pickable=True,
            extruded=False,
            opacity=1.0,
            id="candidates",
        )
    else:
        candidate_layer = None

    # ── View state centred on bbox ────────────────────────────────────────
    avg_lat = grid_df["h3_id"].apply(lambda h: __import__("h3").cell_to_latlng(h)[0]).mean()
    avg_lon = grid_df["h3_id"].apply(lambda h: __import__("h3").cell_to_latlng(h)[1]).mean()
    zoom = {7: 10, 8: 11, 9: 12, 10: 13}.get(int(grid_df.shape[0] > 0 and 9), 11)
    view = pdk.ViewState(latitude=avg_lat, longitude=avg_lon, zoom=zoom, pitch=0)

    layers = [heat_layer] + ([candidate_layer] if candidate_layer else [])

    tooltip = {
        "html": """
            <div style="font-family:sans-serif; font-size:12px; padding:4px 8px; background:rgba(0,0,0,0.8); color:#fff; border-radius:4px; max-width:220px;">
              <b>H3:</b> {h3_id}<br/>
              <b>Risk score:</b> {heat_risk_score}<br/>
              <b>Heat index:</b> {heat_index_c}°C<br/>
              <b>UHI intensity:</b> {uhi_intensity}°C<br/>
              <b>Green cover:</b> {green_cover}
            </div>
        """,
        "style": {"color": "white"},
    }
    cand_tooltip = {
        "html": """
            <div style="font-family:sans-serif; font-size:12px; padding:4px 8px; background:rgba(180,70,0,0.9); color:#fff; border-radius:4px; max-width:240px;">
              <b>🏆 Candidate #</b>{rank}<br/>
              <b>H3:</b> {h3_id}<br/>
              <b>Risk score:</b> {risk_score}<br/>
              <b>Green deficit:</b> {green_deficit}<br/>
              <b>UHI:</b> {uhi_intensity}°C<br/>
              <b>Interventions:</b> {interventions}
            </div>
        """,
        "style": {},
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
            <div style="font-size:12px; line-height:1.8;">
            <span style="display:inline-block;width:12px;height:12px;background:#27ae60;margin-right:6px;border-radius:2px;"></span>Low risk (0–0.33)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:#f1c40f;margin-right:6px;border-radius:2px;"></span>Moderate (0.33–0.66)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:#c0392b;margin-right:6px;border-radius:2px;"></span>High risk (0.66–1.0)<br/>
            <hr style="margin:6px 0;"/>
            <span style="display:inline-block;width:12px;height:12px;border:2px solid #ff6400;background:rgba(255,140,0,0.2);margin-right:6px;border-radius:2px;"></span>Intervention candidate<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Hover a cell for details.")
        n_high = int((grid_df["heat_risk_score"] >= 0.66).sum())
        n_cand = len(cands)
        st.markdown(f"**{n_high}** high-risk cells  \n**{n_cand}** intervention candidates")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_heat_panel() -> None:
    city_id, bbox, h3_res, live = _city_selector()

    render_domain_header(
        title="Urban Heat Risk Review",
        caption=(
            "Per-H3-cell heat risk scores combining Urban Heat Island intensity (IDW-interpolated "
            "from OpenMeteo) and OSM green cover deficit. Review-support only."
        ),
        primary_alert=(
            "**Decision support only.** Heat risk scores are IDW-interpolated estimates. "
            "Human review required before any operational or public-facing action."
        ),
        primary_alert_kind="error",
    )

    # ── Load data ──────────────────────────────────────────────────────────
    with st.spinner("Building heat risk grid…"):
        if live:
            temp_df = _load_live_temperature(
                city_id, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
                lookback_days=_LOOKBACK_DAYS,
            )
            if temp_df.empty:
                st.warning("OpenMeteo returned no data. Falling back to synthetic demo temperatures.")
                temp_df = _synthetic_temperature(bbox)
                data_note = "synthetic (OpenMeteo call failed)"
            else:
                data_note = f"live OpenMeteo ({len(temp_df)} records)"
        else:
            temp_df = _synthetic_temperature(bbox)
            data_note = "synthetic demo (toggle 'Fetch live data' in sidebar for real temperatures)"

        green_df = pd.DataFrame()

        dashboard = build_heat_risk_dashboard(
            temperature_df=temp_df,
            green_cover_df=green_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )
        candidates = build_intervention_candidates(
            temperature_df=temp_df,
            green_cover_df=green_df,
            h3_resolution=h3_res,
            city_id=city_id,
            **bbox,
        )

    # Schema validation
    validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "heat_risk_dashboard.v1.schema.json").resolve())
    ).validate(dashboard)
    validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "heat_intervention_candidates.v1.schema.json").resolve())
    ).validate(candidates)

    # ── Context metrics ────────────────────────────────────────────────────
    summary = dashboard.get("summary", {})
    render_context_metrics(
        ("City", city_id),
        ("H3 resolution", str(h3_res)),
        ("Total cells", str(summary.get("total_cells", "—"))),
        ("High-risk cells (≥0.66)", str(summary.get("high_risk_cell_count", "—"))),
        ("Max risk score", f"{summary.get('max_heat_risk_score') or 0:.3f}"),
        ("Median temp", f"{summary.get('city_median_temperature_c') or '—'}°C"),
        ("Data source", data_note),
        ("Quality flag", dashboard.get("data_quality_flag", "—")),
    )

    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{humanize_warning_id(str(w.get('warning_id', '')))}** — {w.get('message', '')}"
        (st.warning if sev == "warning" else st.info)(msg)

    st.divider()

    # ── Tabs: Map / Browse / Detail ────────────────────────────────────────
    t_map, t_browse, t_detail = st.tabs(["🗺️ Map", "📊 Grid table", "🎯 Intervention candidates"])

    with t_map:
        _render_heat_map(dashboard, candidates)

    with t_browse:
        render_section_title("Heat risk grid")
        cells = dashboard.get("heat_cells", [])
        if cells:
            rows = [
                {
                    "Risk": _risk_emoji(c.get("heat_risk_score", 0) or 0),
                    "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                    "Heat index (°C)": c.get("heat_index_c"),
                    "UHI intensity (°C)": round(c.get("uhi_intensity") or 0, 3),
                    "Green cover": f"{(c.get('green_cover_fraction') or 0):.2f}",
                    "Risk score": f"{c.get('heat_risk_score', 0) or 0:.3f}",
                }
                for c in cells
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("Risk score distribution")
            score_df = pd.DataFrame({"heat_risk_score": [c.get("heat_risk_score", 0) or 0 for c in cells]})
            st.bar_chart(score_df, y="heat_risk_score", height=200)
        else:
            st.info("No H3 cells generated.")

    with t_detail:
        render_section_title("Intervention candidates (top 10)")
        cands = candidates.get("candidates", [])
        if not cands:
            st.info("No intervention candidates generated.")
        else:
            rows = [
                {
                    "Rank": i + 1,
                    "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                    "Risk score": f"{c.get('risk_score', 0):.3f}",
                    "Green deficit": f"{c.get('green_deficit', 0):.3f}",
                    "UHI intensity (°C)": c.get("uhi_intensity"),
                    "Suggested interventions": ", ".join(c.get("suggested_interventions", [])),
                }
                for i, c in enumerate(cands)
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            render_section_title("Drill-down")
            sel = st.selectbox("Select a candidate cell", [c["h3_id"] for c in cands], key="heat_sel_cell")
            selected = next((c for c in cands if c["h3_id"] == sel), None)
            if selected:
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Risk score", f"{selected.get('risk_score', 0):.3f}")
                    st.metric("Green deficit", f"{selected.get('green_deficit', 0):.3f}")
                with col2:
                    st.metric("UHI intensity", f"{selected.get('uhi_intensity') or '—'}°C")
                    st.metric("Water proximity", f"{selected.get('water_proximity_score', 0):.3f}")
                st.markdown("**Suggested interventions:**")
                for s in selected.get("suggested_interventions", []):
                    st.markdown(f"- {s.replace('_', ' ').title()}")
                st.caption(
                    "Heuristic-based suggestions only. Require expert review before "
                    "implementation. Do not use for automated planning or public commitments."
                )

    render_technical_json_expander(
        title="Technical: Raw contract payloads",
        payload={"heat_risk_dashboard": dashboard, "heat_intervention_candidates": candidates},
    )
