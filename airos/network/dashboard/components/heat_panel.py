"""Heat Risk Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk
from airos.network.dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from airos.os.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from airos.apps.heat.heat_pipeline import (
    build_heat_risk_dashboard,
    build_intervention_candidates,
)
from airos.drivers.connectors.heat import fetch_temperature_observations

from airos.network.dashboard.ui_shell import (
    render_browse_detail_layout,
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from airos.network.dashboard.formatters import humanize_warning_id


_LOOKBACK_DAYS = 1
_DEFAULT_H3_RES = 8

from airos.os.city_config import CITIES as _CITY_REGISTRY, get_bbox


# ── Sidebar ────────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, bool]:
    c1, c2 = st.columns([2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="heat_city_selector")
    with c2:
        live = st.toggle("Live data (cached ≤1h)", value=True, key="heat_live_toggle",
                         help="Uses GEE MODIS LST if GEE_PROJECT is set, otherwise OpenMeteo")
    city_id = city_options[city_label]
    bbox    = get_bbox(city_id)
    return city_id, bbox, live


# ── Data loading ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Loading temperature data…")
def _load_live_temperature(city_id: str, lat_min: float, lon_min: float,
                           lat_max: float, lon_max: float, lookback_days: int) -> pd.DataFrame:
    try:
        from airos.os.sdk import store as _sdk_store
        cached = _sdk_store.get_recent_observations("heat", city_id, max_age_hours=1)
        if not cached.empty:
            from airos.drivers.observation_store import to_wide
            return to_wide(cached)
    except Exception:
        pass
    return fetch_temperature_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_days=lookback_days,
        city_id=city_id,
    )


def _synthetic_temperature(bbox: dict) -> pd.DataFrame:
    """3×3 grid of synthetic stations matching OpenMeteo's sampling pattern.

    Temperature pattern creates two distinct heat islands (center-east and
    south-center) so IDW spreads candidates across the city, not just one corner.
    """
    lats = [bbox["lat_min"], (bbox["lat_min"] + bbox["lat_max"]) / 2, bbox["lat_max"]]
    lons = [bbox["lon_min"], (bbox["lon_min"] + bbox["lon_max"]) / 2, bbox["lon_max"]]
    # [lat_row][lon_col]: south→north rows, west→east columns
    # Two equally-hot stations at SW and NE corners create two distinct candidate clusters
    # spread across the full bbox diagonal rather than piling up around a single peak.
    temps = [
        [33.0, 29.0, 27.5],   # south: SW industrial hotspot, south-mid warm, SE cool
        [28.5, 29.5, 28.0],   # center: moderate gradient
        [27.0, 27.5, 33.0],   # north: NW cool, NE dense-urban hotspot
    ]
    rows = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            t = temps[i][j]
            rows.append({
                "station_id": f"demo_{lat:.3f}_{lon:.3f}",
                "latitude": lat, "longitude": lon,
                "timestamp": "2026-05-07T06:00:00Z",
                "temperature_c": t,
                "apparent_temperature_c": round(t + 2.5, 1),
                "relative_humidity_pct": 70.0,
                "data_source": "openmeteo",
                "quality_flag": "synthetic",
            })
    return pd.DataFrame(rows)


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

def _render_heat_map(
    dashboard: dict,
    candidates: dict,
    bbox: dict,
    h3_res: int,
    temp_df: pd.DataFrame,
) -> None:
    import h3 as _h3

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
            "station_id": "",
            "temperature_c": "",
            "rank": "",
            "interventions": "",
        }
        for c in cells
    ])

    heat_layer = pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(grid_df),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[80, 80, 80],
        line_width_min_pixels=0,
        pickable=True,
        extruded=False,
        opacity=0.75,
        id="heat_grid",
    )

    layers = [heat_layer]

    # ── Layer 2: Intervention candidates — large ScatterplotLayer circles ──
    # H3HexagonLayer borders (~174m at res-9) are invisible at city-bbox zoom.
    # ScatterplotLayer circles (r=500m) are clearly visible regardless of zoom.
    if cands:
        cand_scatter_df = pd.DataFrame([
            {
                "lat": _h3.cell_to_latlng(c["h3_id"])[0],
                "lon": _h3.cell_to_latlng(c["h3_id"])[1],
                "h3_id": c["h3_id"],
                "rank": i + 1,
                "risk_score": round(c.get("risk_score", 0.0), 3),
                "green_deficit": round(c.get("green_deficit", 0.0), 3),
                "uhi_intensity": c.get("uhi_intensity"),
                "interventions": ", ".join(c.get("suggested_interventions", [])),
                "heat_risk_score": round(c.get("heat_risk_score") or c.get("risk_score", 0.0), 4),
                "heat_index_c": c.get("heat_index_c", ""),
                "green_cover": c.get("green_cover_fraction", ""),
                "station_id": "",
                "temperature_c": "",
            }
            for i, c in enumerate(cands)
        ])
        candidate_layer = pdk.Layer(
            "ScatterplotLayer",
            data=clean_h3_data(cand_scatter_df),
            get_position=["lon", "lat"],
            get_radius=900,           # ~900m radius so clusters are clearly visible at city scale
            radius_min_pixels=6,
            get_fill_color=[255, 100, 0, 180],
            get_line_color=[180, 40, 0, 255],
            line_width_min_pixels=2,
            stroked=True,
            filled=True,
            pickable=True,
            id="candidates",
        )
        layers.append(candidate_layer)

    # ── Layer 3: IDW sample points (NOT physical weather stations) ────────
    if not temp_df.empty and "latitude" in temp_df.columns:
        cell_lookup = {c["h3_id"]: c for c in cells}
        try:
            def _srow(row):
                cell = _h3.latlng_to_cell(row["latitude"], row["longitude"], h3_res)
                ci = cell_lookup.get(cell, {})
                return {
                    "latitude":       row["latitude"],
                    "longitude":      row["longitude"],
                    "station_id":     row.get("station_id", ""),
                    "temperature_c":  f"{row['temperature_c']:.1f}" if row.get("temperature_c") == row.get("temperature_c") else "N/A",
                    "h3_id":          cell,
                    "heat_risk_score": f"{ci.get('heat_risk_score', 0):.3f}",
                    "heat_index_c":   ci.get("heat_index_c", ""),
                    "uhi_intensity":  ci.get("uhi_intensity", ""),
                    "green_cover":    ci.get("green_cover_fraction", ""),
                    "rank":           "",
                    "interventions":  "",
                }
            station_df = pd.DataFrame([_srow(r) for _, r in temp_df.iterrows()])
        except Exception:
            station_df = temp_df[["latitude", "longitude", "temperature_c", "station_id"]].copy()
            for f in ["h3_id", "heat_risk_score", "heat_index_c", "uhi_intensity", "green_cover", "rank", "interventions"]:
                station_df[f] = ""

        station_layer = pdk.Layer(
            "ScatterplotLayer",
            data=clean_h3_data(station_df),
            get_position=["longitude", "latitude"],
            get_radius=400,
            radius_min_pixels=5,
            get_fill_color=[30, 100, 220, 180],
            get_line_color=[10, 60, 200, 255],
            line_width_min_pixels=2,
            stroked=True,
            filled=True,
            pickable=True,
            id="stations",
        )
        layers.append(station_layer)

    # ── View state: bbox centre + h3_res-appropriate zoom ────────────────
    center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    center_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2
    zoom = {7: 9, 8: 10, 9: 11, 10: 12}.get(h3_res, 11)
    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)

    tooltip = {
        "html": """
            <div style="font-family:sans-serif;font-size:12px;padding:4px 8px;background:rgba(0,0,0,0.85);color:#fff;border-radius:4px;max-width:240px;">
              <b>H3:</b> {h3_id}<br/>
              <b>Risk score:</b> {heat_risk_score}<br/>
              <b>Heat index:</b> {heat_index_c}°C &nbsp; <b>UHI:</b> {uhi_intensity}°C<br/>
              <b>Green cover:</b> {green_cover}<br/>
              <i style="color:#ffa040;">Candidate #{rank} — {interventions}</i><br/>
              <i style="color:#6ab0ff;">Station {station_id}: {temperature_c}°C</i>
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
            <span style="display:inline-block;width:12px;height:12px;background:#27ae60;margin-right:6px;border-radius:2px;"></span>Low risk (0–0.33)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:#f1c40f;margin-right:6px;border-radius:2px;"></span>Moderate (0.33–0.66)<br/>
            <span style="display:inline-block;width:12px;height:12px;background:#c0392b;margin-right:6px;border-radius:2px;"></span>High risk (0.66–1.0)<br/>
            <hr style="margin:6px 0;"/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(255,100,0,0.65);border:2px solid #dc3200;margin-right:6px;border-radius:50%;"></span>Intervention candidate<br/>
            <span style="display:inline-block;width:12px;height:12px;background:rgba(30,100,220,0.7);border:2px solid #0a3cc8;margin-right:6px;border-radius:50%;"></span>IDW sample point<br/>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Hover for details.")
        n_high = int((grid_df["heat_risk_score"] >= 0.66).sum())
        n_cand = len(cands)
        st.markdown(f"**{n_high}** high-risk cells  \n**{n_cand}** candidates")


# ── Main panel ─────────────────────────────────────────────────────────────

def render_heat_panel() -> None:
    city_id, bbox, live = _city_selector()
    h3_res = _DEFAULT_H3_RES

    render_domain_header(
        title="Urban Heat Risk Review",
        caption=(
            "Per-H3-cell heat risk scores combining Urban Heat Island intensity (IDW-interpolated "
            "from OpenMeteo) and OSM green cover deficit. Review-support only."
        ),
        primary_alert=None,
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
        if live:
            try:
                from airos.os.decision_events import emit_heat_decisions
                emit_heat_decisions(candidates, city_id=city_id)
            except Exception:
                pass

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
        _render_heat_map(dashboard, candidates, bbox=bbox, h3_res=h3_res, temp_df=temp_df)
        st.caption(
            "**Blue circles** are IDW sample points — virtual grid coordinates queried from "
            "the OpenMeteo forecast API (or synthesised for demo), not physical weather stations. "
            "Both live and synthetic data use the same 3×3 sampling grid. "
            "**Orange circles** mark the top-10 intervention candidates; they cluster near the "
            "hottest sample points because IDW interpolation peaks at observation locations. "
            "Enable 'Fetch live data' for real temperature readings across the full grid."
        )

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
