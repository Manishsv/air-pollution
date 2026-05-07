"""Ward-level quality of life panel.

Aggregates H3 feature store data to named ward boundaries and renders a
citizen-outcome-first view: QoL index, composite risk, and per-domain
contribution per ward.
"""
from __future__ import annotations

import json
from typing import Optional

import pandas as pd
import pydeck as pdk
import streamlit as st

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)

_CITIES = {
    "Bangalore (demo)": "bangalore_demo",
    "Delhi (demo)":     "delhi_demo",
    "Mumbai (demo)":    "mumbai_demo",
}

_CITY_CENTRES = {
    "bangalore_demo": (12.97, 77.59),
    "delhi_demo":     (28.65, 77.10),
    "mumbai_demo":    (19.05, 72.88),
}


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> str:
    c1, c2 = st.columns([3, 1])
    with c1:
        label = st.selectbox("City", list(_CITIES.keys()), key="ward_city_selector")
    with c2:
        st.button("↻ Refresh", key="ward_refresh",
                  help="Re-read from feature store", use_container_width=True)
    return _CITIES[label]


# ── Data loading ───────────────────────────────────────────────────────────

def _load_wards(city_id: str):
    try:
        from urban_platform.place import aggregate_city_wards
        return aggregate_city_wards(city_id)
    except Exception as exc:
        return None


# ── Colour helpers ─────────────────────────────────────────────────────────

def _qol_color(qol: Optional[float]) -> list[int]:
    """Green (high QoL) → red (low QoL)."""
    if qol is None or pd.isna(qol):
        return [160, 160, 160, 100]
    g = int(min(qol * 220, 220))
    r = int(min((1 - qol) * 220, 220))
    return [r, g, 40, 200]


def _qol_label(qol: Optional[float]) -> str:
    if qol is None or pd.isna(qol):
        return "—"
    if qol >= 0.75:
        return "Good"
    if qol >= 0.55:
        return "Fair"
    if qol >= 0.35:
        return "Poor"
    return "Critical"


# ── Map ────────────────────────────────────────────────────────────────────

def _build_geojson(result) -> dict:
    """Build GeoJSON FeatureCollection from ward registry + aggregated scores."""
    from urban_platform.place import load_wards
    wards = load_wards(result.city_id)
    ward_lookup = result.wards_df.set_index("ward_id").to_dict("index") if not result.wards_df.empty else {}

    features = []
    for w in wards:
        data = ward_lookup.get(w.ward_id, {})
        qol = data.get("qol_index")
        risk = data.get("composite_risk")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [w.coordinates]},
            "properties": {
                "ward_id": w.ward_id,
                "name": w.name,
                "qol_index": qol,
                "qol_label": _qol_label(qol),
                "composite_risk": risk,
                "avg_flood_risk": data.get("avg_flood_risk"),
                "avg_aqi_score": data.get("avg_aqi_score"),
                "avg_heat_risk": data.get("avg_heat_risk"),
                "cell_count": data.get("cell_count", 0),
                "multi_risk_cells": data.get("multi_risk_cell_count", 0),
                "fill_color": _qol_color(qol),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _render_ward_map(result, city_id: str) -> None:
    geojson = _build_geojson(result)
    lat_c, lon_c = _CITY_CENTRES.get(city_id, (20.0, 78.0))

    layer = pdk.Layer(
        "GeoJsonLayer",
        geojson,
        get_fill_color="properties.fill_color",
        get_line_color=[80, 80, 80, 180],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
        opacity=0.75,
    )
    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            tooltip={
                "html": (
                    "<b>{properties.name}</b><br/>"
                    "QoL: <b>{properties.qol_label}</b> ({properties.qol_index})<br/>"
                    "Composite risk: {properties.composite_risk}<br/>"
                    "Flood: {properties.avg_flood_risk} | "
                    "AQI: {properties.avg_aqi_score} | "
                    "Heat: {properties.avg_heat_risk}<br/>"
                    "H3 cells: {properties.cell_count} | "
                    "Multi-risk: {properties.multi_risk_cells}"
                ),
                "style": {"backgroundColor": "#1e293b", "color": "white", "fontSize": "12px"},
            },
            map_style="mapbox://styles/mapbox/light-v10",
        ),
        use_container_width=True,
    )

    # Legend
    st.markdown(
        '<div style="display:flex;gap:16px;font-size:12px;margin-top:4px;">'
        '<span style="color:#dc3545">■ Critical (&lt;0.35)</span>'
        '<span style="color:#fd7e14">■ Poor (0.35–0.55)</span>'
        '<span style="color:#ffc107">■ Fair (0.55–0.75)</span>'
        '<span style="color:#28a745">■ Good (&gt;0.75)</span>'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Ward table ─────────────────────────────────────────────────────────────

def _render_ward_table(wards_df: pd.DataFrame) -> None:
    render_section_title("Ward quality of life index")
    display_cols = [c for c in [
        "ward_name", "qol_index", "composite_risk",
        "avg_flood_risk", "avg_aqi_score", "avg_heat_risk",
        "multi_risk_cell_count", "cell_count",
    ] if c in wards_df.columns]
    st.dataframe(
        wards_df[display_cols].rename(columns={
            "ward_name":            "Ward",
            "qol_index":            "QoL Index",
            "composite_risk":       "Composite Risk",
            "avg_flood_risk":       "Flood Risk",
            "avg_aqi_score":        "AQI Score",
            "avg_heat_risk":        "Heat Risk",
            "multi_risk_cell_count":"Multi-risk Cells",
            "cell_count":           "H3 Cells",
        }),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "QoL Index = weighted average of (1 − risk) across available domains. "
        "Lower QoL → worse citizen outcomes. Sorted worst-first."
    )


# ── Main panel ─────────────────────────────────────────────────────────────

def render_ward_panel() -> None:
    city_id = _city_selector()

    render_domain_header(
        title="Ward Quality of Life",
        caption=(
            "Ward-level citizen outcomes derived from H3 feature store data. "
            "QoL index = weighted composite of safety (flood), health (air quality), "
            "and thermal comfort (heat). Lower = worse outcomes for citizens in that ward."
        ),
        primary_alert=None,
    )

    with st.spinner("Aggregating ward features…"):
        result = _load_wards(city_id)

    if result is None:
        st.info(
            "Feature store not found. Visit Air Quality, Flood, or Heat tabs first "
            "to populate the store, then return here."
        )
        return

    if result.wards_df.empty:
        st.info(
            f"No data found for **{city_id}**. "
            "Visit the domain tabs to run the pipelines, then refresh."
        )
        return

    wards_df = result.wards_df
    worst_ward = wards_df.iloc[0] if not wards_df.empty else None
    best_ward  = wards_df.iloc[-1] if not wards_df.empty else None

    render_context_metrics(
        ("City", city_id),
        ("Wards", str(result.ward_count)),
        ("Domains", ", ".join(result.available_domains) or "none"),
        ("Bucket", result.timestamp_bucket[:16] if result.timestamp_bucket else "—"),
        ("Worst ward", worst_ward["ward_name"] if worst_ward is not None else "—"),
        ("City QoL avg", f"{wards_df['qol_index'].dropna().mean():.2f}" if "qol_index" in wards_df else "—"),
    )

    t_map, t_table = st.tabs(["Ward QoL Map", "Ward Detail Table"])

    with t_map:
        _render_ward_map(result, city_id)

    with t_table:
        _render_ward_table(wards_df)

    render_technical_json_expander(
        title="Technical: Ward aggregation snapshot",
        payload={
            "city_id": city_id,
            "timestamp_bucket": result.timestamp_bucket,
            "available_domains": result.available_domains,
            "ward_count": result.ward_count,
            "qol_weights": {"safety": 0.40, "health": 0.35, "thermal_comfort": 0.25},
        },
    )
