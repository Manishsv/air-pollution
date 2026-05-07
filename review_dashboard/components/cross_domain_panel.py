"""Cross-domain risk panel — combines flood, air quality, and heat from the feature store."""

from __future__ import annotations

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
    "Bangalore (demo)": ("bangalore_demo", dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)),
    "Delhi (demo)":     ("delhi_demo",     dict(lat_min=28.50, lon_min=76.90, lat_max=28.80, lon_max=77.30)),
    "Mumbai (demo)":    ("mumbai_demo",    dict(lat_min=18.90, lon_min=72.75, lat_max=19.20, lon_max=73.00)),
}

_CITY_CENTRES = {
    "bangalore_demo": (12.97, 77.59),
    "delhi_demo":     (28.65, 77.10),
    "mumbai_demo":    (19.05, 72.88),
}


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict]:
    c1, c2 = st.columns([3, 1])
    with c1:
        city_label = st.selectbox("City", list(_CITIES.keys()), key="cross_city_selector")
    with c2:
        st.button("↻ Refresh", key="cross_refresh", help="Re-read from feature store", use_container_width=True)
    city_id, bbox = _CITIES[city_label]
    return city_id, bbox


# ── Data loading ───────────────────────────────────────────────────────────

def _load_cross_domain(city_id: str):
    """Read cross-domain features from store. Not cached — DuckDB reads are fast and
    we need up-to-date results immediately after a pipeline runs in another tab."""
    try:
        from urban_platform.feature_store.reader import FeatureStoreReader
        reader = FeatureStoreReader()
        result = reader.cross_domain_query(city_id=city_id)
        reader.close()
        return result
    except FileNotFoundError:
        return None
    except Exception:
        return None


# ── Map ────────────────────────────────────────────────────────────────────

def _risk_color(score: float | None) -> list[int]:
    if score is None or pd.isna(score):
        return [120, 120, 120, 100]
    r = int(min(score * 255, 255))
    g = int(max((1 - score) * 80, 0))
    return [r, g, 40, 200]


def _render_combined_map(cells_df: pd.DataFrame, city_id: str) -> None:
    import h3 as _h3

    lat_c, lon_c = _CITY_CENTRES.get(city_id, (20.0, 78.0))

    def _fmt(val) -> str:
        return f"{val:.2f}" if pd.notna(val) else "n/a"

    viz = cells_df.copy()
    viz["fill_color"] = viz["composite_risk_score"].apply(_risk_color)
    viz["tooltip_text"] = viz.apply(
        lambda r: (
            f"H3: {r['h3_id']}\n"
            f"Composite: {_fmt(r.get('composite_risk_score'))}\n"
            f"Flood: {_fmt(r.get('flood_risk_score'))}\n"
            f"AQI: {_fmt(r.get('aqi_score'))}\n"
            f"Heat: {_fmt(r.get('heat_risk_score'))}"
        ),
        axis=1,
    )

    layer = pdk.Layer(
        "H3HexagonLayer",
        viz,
        get_hexagon="h3_id",
        get_fill_color="fill_color",
        auto_highlight=True,
        elevation_scale=50,
        elevation_range=[0, 300],
        extruded=False,
        pickable=True,
    )
    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            tooltip={"text": "{tooltip_text}"},
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        ),
        use_container_width=True,
    )


# ── Top-cells table ────────────────────────────────────────────────────────

def _domain_badge(score: float | None, label: str) -> str:
    if score is None or pd.isna(score):
        return f"<span style='color:#aaa'>{label}: n/a</span>"
    color = "#d62728" if score >= 0.7 else "#ff7f0e" if score >= 0.5 else "#2ca02c"
    return f"<span style='color:{color}'>{label}: {score:.2f}</span>"


def _render_top_cells_table(cells_df: pd.DataFrame, top_n: int = 25) -> None:
    render_section_title(f"Top {top_n} multi-risk cells")
    display = cells_df.head(top_n).copy()
    cols = [c for c in [
        "h3_id", "composite_risk_score", "elevated_domain_count",
        "flood_risk_score", "aqi_score", "heat_risk_score",
        "flood_dqf", "air_dqf", "heat_dqf",
    ] if c in display.columns]
    st.dataframe(
        display[cols].rename(columns={
            "h3_id": "H3 cell",
            "composite_risk_score": "Composite",
            "elevated_domain_count": "Elevated domains",
            "flood_risk_score": "Flood",
            "aqi_score": "AQI",
            "heat_risk_score": "Heat",
            "flood_dqf": "Flood DQF",
            "air_dqf": "Air DQF",
            "heat_dqf": "Heat DQF",
        }),
        hide_index=True,
        use_container_width=True,
    )


# ── Main panel ─────────────────────────────────────────────────────────────

def render_cross_domain_panel() -> None:
    city_id, bbox = _city_selector()

    render_domain_header(
        title="Cross-Domain Risk Overview",
        caption=(
            "Combined flood, air quality, and heat risk per H3 cell. "
            "Data sourced from the local feature store — populated when any domain panel runs."
        ),
        primary_alert=None,
    )

    result = _load_cross_domain(city_id=city_id)

    if result is None:
        st.info(
            "Feature store not found. "
            "Open the Flood, Air Quality, or Heat tab first — each pipeline run populates the store automatically."
        )
        return

    if result.cells_df.empty:
        st.info(
            f"No feature store data found for **{city_id}**. "
            "Switch to one of the domain tabs and let the pipeline run, then come back here."
        )
        return

    cells_df = result.cells_df
    multi_risk_count = int((cells_df.get("elevated_domain_count", pd.Series([], dtype=int)) >= 2).sum())

    render_context_metrics(
        ("City", city_id),
        ("Domains in store", ", ".join(result.available_domains) if result.available_domains else "none"),
        ("H3 cells", str(len(cells_df))),
        ("Bucket", result.timestamp_bucket[:16] if result.timestamp_bucket else "—"),
        ("Multi-risk cells (≥2 elevated)", str(multi_risk_count)),
    )

    if result.available_domains:
        missing = [d for d in ["flood", "air", "heat"] if d not in result.available_domains]
        if missing:
            st.warning(
                f"Missing domains in store for this city: **{', '.join(missing)}**. "
                "Open those tabs to populate them."
            )

    t_map, t_table = st.tabs(["Combined Risk Map", "Top Multi-Risk Cells"])

    with t_map:
        _render_combined_map(cells_df, city_id)

    with t_table:
        _render_top_cells_table(cells_df)

    render_technical_json_expander(
        title="Technical: Cross-domain feature snapshot",
        payload={
            "city_id": city_id,
            "timestamp_bucket": result.timestamp_bucket,
            "available_domains": result.available_domains,
            "row_count": len(cells_df),
            "multi_risk_cells": multi_risk_count,
        },
    )
