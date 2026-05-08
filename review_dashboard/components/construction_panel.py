"""Construction Activity & Dust dashboard panel.

Combines two satellite signals:
  Sentinel-2 BSI   — bare soil index (active earthworks / cleared plots)
  Sentinel-5P NO2  — tropospheric column (machinery exhaust proxy)

Construction Risk Index (CRI) = weighted BSI + NO2, dampened by NDVI.
"""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from urban_platform.applications.construction.construction_pipeline import (
    build_construction_dashboard,
    build_construction_decision_packets,
)
from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from review_dashboard.formatters import (
    evidence_inputs_to_rows,
    safety_gates_to_rows,
)
from urban_platform.city_config import CITIES as _CITY_REGISTRY, get_bbox
from review_dashboard.data_cache import load_construction_signals, h3_grid_for_bbox


# ── Colour map ─────────────────────────────────────────────────────────────

_CRI_COLORS = {
    "minimal":  [180, 180, 180,  60],
    "low":      [255, 230, 140, 150],
    "moderate": [230, 160,  40, 180],
    "high":     [200,  80,  10, 200],
    "severe":   [140,  20,  20, 220],
}

_LEVEL_EMOJI = {
    "minimal":  "⚪",
    "low":      "🟡",
    "moderate": "🟠",
    "high":     "🔴",
    "severe":   "⚫",
}

_ACTIVITY_ICONS = {
    "metro":      "🚇",
    "metro_road": "🚇",
    "road":       "🛣️",
    "commercial": "🏗️",
    "industrial": "🏭",
    "airport":    "✈️",
}

def _level_emoji(level: str) -> str:
    return _LEVEL_EMOJI.get(level, "⚪")


# ── Demo data ──────────────────────────────────────────────────────────────

def _demo_construction_cells(city_id: str, h3_ids: tuple) -> dict:
    import random
    rng = random.Random(hash(city_id + "construction") % (2**31))

    city_presets = {
        "bangalore": {"frac": 0.18, "bias": 0.50},
        "hyderabad": {"frac": 0.15, "bias": 0.45},
        "chennai":   {"frac": 0.12, "bias": 0.40},
        "mumbai":    {"frac": 0.14, "bias": 0.42},
        "delhi":     {"frac": 0.22, "bias": 0.60},
        "pune":      {"frac": 0.12, "bias": 0.38},
    }
    preset = city_presets.get(city_id, {"frac": 0.12, "bias": 0.40})

    result = {}
    sample = rng.sample(list(h3_ids), max(1, int(len(h3_ids) * preset["frac"])))
    for h3_id in sample:
        bsi_val    = round(rng.gauss(0.15, 0.08), 4)
        bsi_val    = max(0.06, min(0.5, bsi_val))
        ndvi_val   = round(rng.gauss(0.15, 0.10), 4)
        ndvi_val   = max(0.0, min(0.6, ndvi_val))
        no2_val    = rng.gauss(7e-5, 3e-5)
        no2_val    = max(2e-5, min(2.5e-4, no2_val))
        bsi_score  = min(1.0, max(0.0, (bsi_val - 0.05) / 0.45))
        no2_score  = min(1.0, max(0.0, (no2_val - 3.5e-5) / (1.5e-4 - 3.5e-5)))
        ndvi_f     = max(0.3, 1.0 - max(0.0, ndvi_val))
        cri        = round(min(1.0, (bsi_score * 0.6 + no2_score * 0.4) * ndvi_f), 4)
        result[h3_id] = {
            "bsi":                    round(bsi_val, 4),
            "ndvi":                   round(ndvi_val, 4),
            "no2_mol_m2":             round(no2_val, 8),
            "bsi_score":              round(bsi_score, 3),
            "no2_score":              round(no2_score, 3),
            "ndvi_factor":            round(ndvi_f, 3),
            "construction_risk_index": cri,
        }
    return result


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, int, bool, int]:
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="construction_city_selector")
    with c2:
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="construction_h3_res")
    with c3:
        live = st.toggle("Live data", value=True, key="construction_live_toggle",
                         help="Requires GEE_PROJECT for Sentinel-2 BSI + Sentinel-5P NO2")
    with c4:
        lookback = st.selectbox("Lookback (days)", [10, 20, 30], index=1,
                                key="construction_lookback",
                                help="Sentinel-2 revisit ~5 days; 20d balances coverage vs. currency")
    city_id = city_options[city_label]
    return city_id, get_bbox(city_id), h3_res, live, int(lookback)


# ── H3 hex layer ───────────────────────────────────────────────────────────

def _hex_layer(cells: list[dict]) -> pdk.Layer:
    import h3
    rows = []
    for c in cells:
        lat, lon = h3.cell_to_latlng(c["h3_id"])
        rows.append({
            "lat":   lat,
            "lon":   lon,
            "h3_id": c["h3_id"],
            "cri":   round(c["construction_risk_index"], 3),
            "level": c["risk_level"],
            "color": c["color"],
            "bsi":   round(c["bsi"], 3),
            "ndvi":  round(c["ndvi"], 3),
            "no2":   f"{c['no2_mol_m2']:.2e}",
        })
    return pdk.Layer(
        "H3HexagonLayer",
        data=rows,
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 40],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.8,
    )


def _zones_layer(zones: list[dict]) -> pdk.Layer:
    rows = []
    for z in zones:
        rows.append({
            "lat":      z["lat"],
            "lon":      z["lon"],
            "name":     z["name"],
            "activity": z.get("activity", ""),
            "color":    [255, 220, 50, 220],
        })
    return pdk.Layer(
        "ScatterplotLayer",
        data=rows,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=250,
        pickable=True,
        opacity=0.9,
    )


# ── Map ────────────────────────────────────────────────────────────────────

def _render_map(dashboard: dict, bbox: dict) -> None:
    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    cells  = dashboard.get("risk_cells", [])
    zones  = dashboard.get("known_construction_zones", [])
    layers = []

    if cells:
        layers.append(_hex_layer(cells))
    if zones:
        layers.append(_zones_layer(zones))

    if not layers:
        st.info("No active construction cells detected for this city / resolution.")
        return

    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    tooltip_html = (
        "<b>{h3_id}</b><br/>"
        "CRI: {cri} | Level: {level}<br/>"
        "BSI: {bsi} | NDVI: {ndvi} | NO₂: {no2}"
    )
    chart = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": tooltip_html, "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    legend_cols = st.columns(5)
    for col, (level, emoji) in zip(legend_cols, _LEVEL_EMOJI.items()):
        with col:
            rgb = _CRI_COLORS[level]
            st.markdown(
                f'<span style="color:rgb({rgb[0]},{rgb[1]},{rgb[2]})">{emoji}</span> '
                f'**{level.title()}**',
                unsafe_allow_html=True,
            )


# ── Construction sites tab ─────────────────────────────────────────────────

def _render_sites_tab(dashboard: dict) -> None:
    cells = dashboard.get("risk_cells", [])
    zones = dashboard.get("known_construction_zones", [])

    if cells:
        render_section_title("Active Construction Cells")
        rows = []
        for c in cells[:50]:
            rows.append({
                "H3 Cell": c["h3_id"],
                "Level":   f"{_level_emoji(c['risk_level'])} {c['risk_level'].title()}",
                "CRI":     f"{c['construction_risk_index']:.3f}",
                "BSI":     f"{c['bsi']:.3f}",
                "NDVI":    f"{c['ndvi']:.3f}",
                "NO₂":     f"{c['no2_mol_m2']:.2e}",
                "BSI Score": f"{c['bsi_score']:.3f}",
                "NO₂ Score": f"{c['no2_score']:.3f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if zones:
        render_section_title("Known Construction Corridors")
        zone_rows = []
        for z in zones:
            icon = _ACTIVITY_ICONS.get(z.get("activity", ""), "🏗️")
            zone_rows.append({
                "Name":     f"{icon} {z['name']}",
                "Activity": z.get("activity", "").replace("_", " ").title(),
                "Lat":      z["lat"],
                "Lon":      z["lon"],
            })
        st.dataframe(pd.DataFrame(zone_rows), use_container_width=True, hide_index=True)

    if not cells and not zones:
        st.info("No construction data available.")


# ── Signal breakdown tab ───────────────────────────────────────────────────

def _render_signal_tab(dashboard: dict) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No active construction cells detected.")
        return

    df = pd.DataFrame([{
        "H3 Cell":  c["h3_id"],
        "Level":    c["risk_level"],
        "CRI":      c["construction_risk_index"],
        "BSI Score":c["bsi_score"],
        "NO₂ Score":c["no2_score"],
        "BSI":      c["bsi"],
        "NDVI":     c["ndvi"],
    } for c in cells])

    render_section_title("Signal Distribution")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.bar_chart(df.set_index("H3 Cell")["BSI Score"].head(20), use_container_width=True)
        st.caption("BSI score (bare soil intensity)")
    with c2:
        st.bar_chart(df.set_index("H3 Cell")["NO₂ Score"].head(20), use_container_width=True)
        st.caption("NO₂ score (machinery exhaust proxy)")
    with c3:
        st.bar_chart(df.set_index("H3 Cell")["CRI"].head(20), use_container_width=True)
        st.caption("Construction Risk Index (composite)")

    render_section_title("Risk Level Distribution")
    level_counts = df["Level"].value_counts().rename_axis("Level").reset_index(name="Cells")
    st.bar_chart(level_counts.set_index("Level"), use_container_width=True)

    with st.expander("Signal methodology"):
        st.markdown("""
| Signal | Index | Formula | Interpretation |
|---|---|---|---|
| **Bare Soil** | BSI | ((SWIR1+Red) − (NIR+Blue)) / ((SWIR1+Red) + (NIR+Blue)) | > 0.05 → bare/disturbed; > 0.15 → active works |
| **Vegetation** | NDVI | (NIR − Red) / (NIR + Red) | Low NDVI + high BSI = construction (not forest) |
| **Exhaust** | NO₂ | S5P TROPOMI column (mol/m²) | > 8×10⁻⁵ → elevated; > 1.5×10⁻⁴ → heavy activity |

**CRI** = (BSI_score×0.6 + NO₂_score×0.4) × (1 − NDVI_clamp)
NDVI factor prevents high-BSI vegetated areas (bare laterite soil under forest) from triggering false alarms.
        """)


# ── Decision packets tab ───────────────────────────────────────────────────

def _render_decisions_tab(packets: list[dict], city_id: str) -> None:
    if not packets:
        st.info("No actionable construction packets (all cells below CRI threshold or no data).")
        return

    render_section_title(f"{len(packets)} Construction Decision Packet(s)")

    from urban_platform.decision_events import emit_construction_decisions

    emit_col, _ = st.columns([2, 4])
    with emit_col:
        if st.button("Emit to Decision Log", key="construction_emit_btn"):
            n = emit_construction_decisions(packets, city_id)
            st.success(f"Emitted {n} construction decision(s) to log.")

    for pkt in packets:
        ca    = pkt.get("construction_assessment", {})
        level = ca.get("risk_level", "moderate")
        cri   = ca.get("construction_risk_index", 0.0)
        dom   = ca.get("dominant_activity", "soil_disturbance")
        h3_id = pkt.get("h3_id", "")

        with st.expander(
            f"{_level_emoji(level)} {h3_id[:12]}… — {level.title()} (CRI {cri:.3f}) — {dom.replace('_', ' ').title()}",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Risk Level", level.title())
                st.metric("Dominant Activity", dom.replace("_", " ").title())
            with c2:
                st.metric("CRI", f"{cri:.3f}")
                st.metric("Field Verification", "Required" if pkt.get("field_verification_required") else "Optional")

            ev_rows = evidence_inputs_to_rows(pkt.get("evidence", {}))
            if ev_rows:
                st.dataframe(pd.DataFrame(ev_rows), use_container_width=True, hide_index=True)

            guidance = pkt.get("review_guidance", {})
            prompts  = guidance.get("review_prompts", [])
            caveats  = guidance.get("when_not_to_act", [])
            if prompts:
                st.markdown("**Review prompts:**")
                for p in prompts:
                    st.markdown(f"- {p}")
            if caveats:
                st.markdown("**When not to act:**")
                for cv in caveats:
                    st.markdown(f"- {cv}")

            gates = safety_gates_to_rows(pkt.get("safety_gates", []))
            if gates:
                st.markdown("**Safety gates:**")
                st.dataframe(pd.DataFrame(gates), use_container_width=True, hide_index=True)

            blocked = pkt.get("blocked_uses", [])
            if blocked:
                st.markdown("**Blocked automated uses:**")
                for b in blocked:
                    st.markdown(f"- `{b}`")

            render_technical_json_expander(title="Raw packet", payload=pkt)


# ── Main render ────────────────────────────────────────────────────────────

def render_construction_panel() -> None:
    render_domain_header(
        title="Construction Activity & Dust",
        caption=(
            "Sentinel-2 Bare Soil Index + Sentinel-5P NO₂ aggregated to H3 cells — "
            "detects active earthworks, construction sites, and machinery dust emissions."
        ),
    )

    city_id, bbox, h3_res, live, lookback = _city_selector()
    lat_min, lon_min = bbox["lat_min"], bbox["lon_min"]
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]

    # ── Fetch / cache construction signals ──
    # Cache key is just 6 scalars; h3_ids are computed inside the cached function.
    data_source = "demo"
    ss_key = f"construction__{city_id}__{h3_res}__{lookback}__{live}"

    if ss_key not in st.session_state:
        construction_cells: dict = {}
        if live:
            construction_cells = load_construction_signals(
                lat_min, lon_min, lat_max, lon_max, h3_res, lookback_days=lookback,
            )
        if not construction_cells:
            h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_res)
            construction_cells = _demo_construction_cells(city_id, h3_ids)
            data_source = "demo"
        else:
            data_source = "live"

        packets_construction = build_construction_decision_packets(
            construction_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
        )

        # ── Persist to H3 Knowledge Store (best-effort) ──
        try:
            from urban_platform.h3_knowledge.writer import ingest_assessment_cells, write_packet as _wp
            cell_list = [{"h3_id": k, **v} for k, v in construction_cells.items()]
            ingest_assessment_cells(
                cell_list, city_id=city_id, domain="construction",
                signal_key="cri", risk_key="risk_level",
                issue_key="dominant_issue", unit="index", source=data_source,
            )
            for pkt in packets_construction:
                _wp(
                    packet_id=pkt.get("packet_id", ""),
                    h3_id=pkt.get("spatial_unit_id", ""),
                    city_id=city_id, domain="construction",
                    risk_level=pkt.get("risk_level", "unknown"),
                    confidence_score=pkt.get("confidence_score"),
                    field_verification_required=bool(pkt.get("field_verification_required")),
                    packet=pkt,
                )
        except Exception:
            pass

        st.session_state[ss_key] = {
            "construction_cells": construction_cells,
            "data_source":        data_source,
            "dashboard":          build_construction_dashboard(
                construction_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
            ),
            "packets":            packets_construction,
        }
        if live and not construction_cells:
            st.warning(
                "No live satellite construction data available — using demo data. "
                "Set `GEE_PROJECT` env var and ensure GEE credentials are configured.",
                icon="⚠️",
            )

    cached             = st.session_state[ss_key]
    construction_cells = cached["construction_cells"]
    data_source        = cached["data_source"]
    dashboard          = cached["dashboard"]
    packets            = cached["packets"]

    summary = dashboard.get("risk_summary", {})

    for w in dashboard.get("active_warnings", []):
        if w["severity"] == "error":
            st.error(w["message"], icon="🚨")
        else:
            st.warning(w["message"], icon="⚠️")

    render_context_metrics(
        ("Overall Risk",       f"{_level_emoji(summary.get('overall_risk_level','minimal'))} {summary.get('overall_risk_level','—').title()}"),
        ("Active Cells",       summary.get("active_cells_total", 0)),
        ("Severe",             summary.get("severe_cells", 0)),
        ("High",               summary.get("high_cells", 0)),
        ("Moderate",           summary.get("moderate_cells", 0)),
        ("Max CRI",            f"{summary.get('max_cri', 0):.3f}"),
        ("Avg CRI",            f"{summary.get('avg_cri', 0):.3f}"),
        ("Data Source",        f"{'🟢' if data_source == 'live' else '🟡'} {data_source}"),
    )

    with st.expander("Signal requirements", expanded=False):
        st.markdown("""
| Signal | Source | Requirement |
|---|---|---|
| **BSI (Bare Soil Index)** | Sentinel-2 SR via GEE | `GEE_PROJECT` + service account |
| **NO₂ column** | Sentinel-5P TROPOMI via GEE | same GEE credentials |
| **Cloud filter** | S2 QA bands | <30% cloud cover applied automatically |
| **BSI threshold** | — | Only cells with BSI > 0.05 flagged as construction candidates |
        """)

    t_map, t_sites, t_signals, t_decisions = st.tabs([
        "🗺️ Map", "🏗️ Construction Sites", "📊 Signal Breakdown", "📋 Decision Packets",
    ])

    with t_map:
        _render_map(dashboard, bbox)
    with t_sites:
        _render_sites_tab(dashboard)
    with t_signals:
        _render_signal_tab(dashboard)
    with t_decisions:
        _render_decisions_tab(packets, city_id)
