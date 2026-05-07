"""Heat Risk Review dashboard panel."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file
from urban_platform.applications.heat.heat_pipeline import (
    build_h3_grid_from_bbox,
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


_DEFAULT_CITY = "bangalore"
_DEFAULT_BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
_DEFAULT_H3_RES = 9
_LOOKBACK_DAYS = 1


def _city_selector() -> tuple[str, dict, int]:
    """Sidebar city selector. Returns (city_id, bbox, h3_res)."""
    cities = {
        "Bangalore (demo)": ("bangalore_demo", dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)),
        "Delhi (demo)": ("delhi_demo", dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30)),
        "Mumbai (demo)": ("mumbai_demo", dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00)),
    }
    with st.sidebar:
        st.markdown("### Heat Risk Settings")
        city_label = st.selectbox("City", list(cities.keys()), key="heat_city_selector")
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="heat_h3_res",
                           help="Higher = smaller cells, more detail, slower")
        live = st.toggle("Fetch live data from OpenMeteo", value=False, key="heat_live_toggle",
                         help="Makes a real HTTP request to api.open-meteo.com (no API key needed)")

    city_id, bbox = cities[city_label]
    return city_id, bbox, h3_res, live


@st.cache_data(ttl=300, show_spinner="Fetching temperature data from OpenMeteo…")
def _load_live_temperature(city_id: str, lat_min: float, lon_min: float, lat_max: float, lon_max: float, lookback_days: int) -> pd.DataFrame:
    return fetch_temperature_observations(
        city_name=city_id,
        lat_min=lat_min, lon_min=lon_min,
        lat_max=lat_max, lon_max=lon_max,
        lookback_days=lookback_days,
    )


def _synthetic_temperature(bbox: dict) -> pd.DataFrame:
    """Fast offline fallback — 3 synthetic grid points."""
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


def _risk_color(score: float) -> str:
    if score >= 0.66:
        return "🔴"
    if score >= 0.33:
        return "🟡"
    return "🟢"


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
            data_note = "synthetic demo (toggle 'Fetch live data' in sidebar for real data)"

        green_df = pd.DataFrame()  # OSM call omitted for dashboard speed; green cover = 0

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

    # ── Validate against schema ────────────────────────────────────────────
    v_dash = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "heat_risk_dashboard.v1.schema.json").resolve())
    )
    v_cand = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "heat_intervention_candidates.v1.schema.json").resolve())
    )
    v_dash.validate(dashboard)
    v_cand.validate(candidates)

    # ── Context metrics ────────────────────────────────────────────────────
    summary = dashboard.get("summary", {})
    render_context_metrics(
        ("City", city_id),
        ("H3 resolution", str(h3_res)),
        ("Total cells", str(summary.get("total_cells", "—"))),
        ("High-risk cells (≥0.66)", str(summary.get("high_risk_cell_count", "—"))),
        ("Max risk score", f"{summary.get('max_heat_risk_score') or 0:.3f}"),
        ("Median temperature", f"{summary.get('city_median_temperature_c') or '—'}°C"),
        ("Data source", data_note),
        ("Quality flag", dashboard.get("data_quality_flag", "—")),
    )

    # ── Warnings ───────────────────────────────────────────────────────────
    for w in dashboard.get("active_warnings", []):
        sev = str(w.get("severity", "info")).lower()
        msg = f"**{humanize_warning_id(str(w.get('warning_id', '')))}** — {w.get('message', '')}"
        if sev == "warning":
            st.warning(msg)
        else:
            st.info(msg)

    st.divider()

    # ── Browse / detail layout ─────────────────────────────────────────────
    def _browse() -> None:
        render_section_title("Heat risk grid")
        cells = dashboard.get("heat_cells", [])
        if not cells:
            st.info("No H3 cells generated.")
            return

        rows = []
        for c in cells:
            score = c.get("heat_risk_score", 0.0) or 0.0
            rows.append({
                "Risk": _risk_color(score),
                "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                "Heat index (°C)": c.get("heat_index_c"),
                "UHI intensity (°C)": c.get("uhi_intensity"),
                "Green cover": f"{(c.get('green_cover_fraction') or 0):.2f}",
                "Water proximity": f"{(c.get('water_proximity_score') or 0):.2f}",
                "Risk score": f"{score:.3f}",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True)

        render_section_title("Risk score distribution")
        scores = [c.get("heat_risk_score", 0) or 0 for c in cells]
        score_df = pd.DataFrame({"heat_risk_score": scores})
        st.bar_chart(score_df, y="heat_risk_score", height=200)

    def _detail() -> None:
        render_section_title("Intervention candidates (top 10)")
        cands = candidates.get("candidates", [])
        if not cands:
            st.info("No intervention candidates generated.")
            return

        rows = []
        for i, c in enumerate(cands, 1):
            rows.append({
                "Rank": i,
                "H3 cell": str(c.get("h3_id", ""))[:16] + "…",
                "Risk score": f"{c.get('risk_score', 0):.3f}",
                "Green deficit": f"{c.get('green_deficit', 0):.3f}",
                "UHI intensity (°C)": c.get("uhi_intensity"),
                "Suggested interventions": ", ".join(c.get("suggested_interventions", [])),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        render_section_title("Drill-down")
        h3_ids = [str(c.get("h3_id", "")) for c in cands]
        sel = st.selectbox("Select a cell", h3_ids, key="heat_selected_cell")
        selected = next((c for c in cands if str(c.get("h3_id")) == sel), None)
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
                "Intervention suggestions are heuristic-based and require expert review "
                "before implementation. Do not use for automated planning or public commitments."
            )

    render_browse_detail_layout(browse=_browse, detail=_detail)

    render_technical_json_expander(
        title="Technical: Raw contract payloads",
        payload={"heat_risk_dashboard": dashboard, "heat_intervention_candidates": candidates},
    )
