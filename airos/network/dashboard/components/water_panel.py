"""Water Quality dashboard panel.

Aggregates Sentinel-2 SR water quality indices into per-H3-cell risk assessments:
  MNDWI  — water body presence (> 0 = water pixel)
  NDTI   — turbidity / suspended sediment
  CI     — chlorophyll-a proxy (algal bloom intensity)
  FAI    — floating algae / surface foam
"""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
from airos.network.dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from airos.apps.water.water_pipeline import (
    build_water_dashboard,
)
from airos.network.dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from airos.network.dashboard.formatters import (
    evidence_inputs_to_rows,
    humanize_snake_sentence,
    safety_gates_to_rows,
)
from airos.os.city_config import CITIES as _CITY_REGISTRY, get_bbox
from airos.network.dashboard.data_cache import load_water_quality, h3_grid_for_bbox

_DEFAULT_H3_RES = 8

# ── Colour maps ────────────────────────────────────────────────────────────

_WQI_COLORS = {
    "good":     [30,  144, 255, 160],
    "moderate": [255, 200,  50, 180],
    "poor":     [220,  80,  20, 200],
    "severe":   [120,   0,  80, 220],
}

_LEVEL_EMOJI = {
    "good":     "🔵",
    "moderate": "🟡",
    "poor":     "🟠",
    "severe":   "🟣",
}

_RISK_EMOJI = {
    "low":      "🟢",
    "moderate": "🟡",
    "high":     "🔴",
}

def _level_emoji(level: str) -> str:
    return _LEVEL_EMOJI.get(level, "⚪")


# ── Demo data ──────────────────────────────────────────────────────────────

def _demo_water_cells(city_id: str, h3_ids: tuple) -> dict:
    """Synthetic water quality data for demo when GEE unavailable."""
    import random, math
    rng = random.Random(hash(city_id) % (2**31))

    city_presets = {
        "bangalore": {"frac": 0.15, "bias": 0.6},
        "hyderabad": {"frac": 0.12, "bias": 0.4},
        "chennai":   {"frac": 0.10, "bias": 0.3},
        "mumbai":    {"frac": 0.08, "bias": 0.35},
        "delhi":     {"frac": 0.20, "bias": 0.7},
        "pune":      {"frac": 0.08, "bias": 0.3},
    }
    preset = city_presets.get(city_id, {"frac": 0.10, "bias": 0.4})

    result = {}
    sample = rng.sample(list(h3_ids), max(1, int(len(h3_ids) * preset["frac"])))
    for h3_id in sample:
        wqi_base  = rng.gauss(preset["bias"], 0.2)
        wqi       = round(min(1.0, max(0.0, wqi_base)), 4)
        ndti_val  = round(rng.uniform(-0.2, 0.4), 4)
        ci_val    = round(rng.uniform(0.9, 3.5), 4)
        fai_val   = round(rng.uniform(0.0, 0.08), 6)
        turb      = min(1.0, max(0.0, (ndti_val + 0.2) / 0.6))
        algal     = min(1.0, max(0.0, (ci_val - 1.0) / 2.0))
        foam      = min(1.0, max(0.0, fai_val / 0.05))
        result[h3_id] = {
            "mndwi":               round(rng.uniform(0.05, 0.6), 4),
            "ndti":                ndti_val,
            "ci":                  ci_val,
            "fai":                 fai_val,
            "water_quality_index": wqi,
            "turbidity_score":     round(turb, 3),
            "algal_score":         round(algal, 3),
            "foam_score":          round(foam, 3),
        }
    return result


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, bool, int]:
    c1, c2, c3 = st.columns([2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="water_city_selector")
    with c2:
        live = st.toggle("Live data", value=True, key="water_live_toggle",
                         help="Requires GEE_PROJECT env var for Sentinel-2 access")
    with c3:
        lookback = st.selectbox("Lookback (days)", [5, 10, 20, 30], index=1,
                                key="water_lookback",
                                help="Sentinel-2 revisit ~5 days; 10d recommended")
    city_id = city_options[city_label]
    return city_id, get_bbox(city_id), live, int(lookback)


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
            "wqi":   c["water_quality_index"],
            "level": c["quality_level"],
            "color": c["color"],
            "turb":  round(c["turbidity_score"], 3),
            "algal": round(c["algal_score"], 3),
            "foam":  round(c["foam_score"], 3),
        })
    return pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(rows),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 60],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.75,
    )


def _known_water_bodies_layer(bodies: list[dict]) -> pdk.Layer:
    rows = []
    for b in bodies:
        rows.append({
            "lat":  b["lat"],
            "lon":  b["lon"],
            "name": b["name"],
            "risk": b.get("risk", "low"),
            "color": {"high": [255, 60, 60, 220], "moderate": [255, 180, 0, 200],
                      "low": [30, 200, 80, 180]}.get(b.get("risk", "low"), [100, 200, 255, 180]),
        })
    return pdk.Layer(
        "ScatterplotLayer",
        data=clean_h3_data(rows),
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=300,
        pickable=True,
        opacity=0.9,
    )


# ── Map ────────────────────────────────────────────────────────────────────

def _render_map(dashboard: dict, bbox: dict) -> None:
    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    cells   = dashboard.get("risk_cells", [])
    bodies  = dashboard.get("known_water_bodies", [])
    layers  = []

    if cells:
        layers.append(_hex_layer(cells))
    if bodies:
        layers.append(_known_water_bodies_layer(bodies))

    if not layers:
        st.info("No water body cells detected for this city / resolution.")
        return

    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)

    tooltip_html = (
        "<b>{h3_id}</b><br/>"
        "WQI: {wqi}<br/>"
        "Level: {level}<br/>"
        "Turbidity: {turb} | Algal: {algal} | Foam: {foam}"
    ) if cells else "<b>{name}</b><br/>Risk: {risk}"

    chart = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": tooltip_html, "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    # Legend
    legend_cols = st.columns(4)
    for col, (level, emoji) in zip(legend_cols, _LEVEL_EMOJI.items()):
        with col:
            rgb = _WQI_COLORS[level]
            st.markdown(
                f'<span style="color:rgb({rgb[0]},{rgb[1]},{rgb[2]})">{emoji}</span> '
                f'**{level.title()}**',
                unsafe_allow_html=True,
            )


# ── Water bodies table tab ─────────────────────────────────────────────────

def _render_water_bodies_tab(dashboard: dict) -> None:
    cells  = dashboard.get("risk_cells", [])
    bodies = dashboard.get("known_water_bodies", [])

    if cells:
        render_section_title("Detected Water Cells")
        rows = []
        for c in cells[:50]:
            rows.append({
                "H3 Cell":   c["h3_id"],
                "Level":     f"{_level_emoji(c['quality_level'])} {c['quality_level'].title()}",
                "WQI":       f"{c['water_quality_index']:.3f}",
                "Turbidity": f"{c['turbidity_score']:.3f}",
                "Algal":     f"{c['algal_score']:.3f}",
                "Foam":      f"{c['foam_score']:.3f}",
                "MNDWI":     f"{c.get('mndwi', 0):.3f}",
                "NDTI":      f"{c.get('ndti', 0):.3f}",
                "CI":        f"{c.get('ci', 0):.3f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if bodies:
        render_section_title("Known Water Bodies")
        body_rows = []
        for b in bodies:
            body_rows.append({
                "Name":     b["name"],
                "Lat":      b["lat"],
                "Lon":      b["lon"],
                "Historical Risk": f"{_RISK_EMOJI.get(b.get('risk','low'), '⚪')} {b.get('risk','low').title()}",
            })
        st.dataframe(pd.DataFrame(body_rows), use_container_width=True, hide_index=True)

    if not cells and not bodies:
        st.info("No water quality data available.")


# ── Signal breakdown tab ───────────────────────────────────────────────────

def _render_signal_tab(dashboard: dict) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No water cells detected.")
        return

    df = pd.DataFrame([{
        "H3 Cell":    c["h3_id"],
        "Level":      c["quality_level"],
        "WQI":        c["water_quality_index"],
        "Turbidity":  c["turbidity_score"],
        "Algal":      c["algal_score"],
        "Foam":       c["foam_score"],
    } for c in cells])

    render_section_title("Signal Distribution")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.bar_chart(df.set_index("H3 Cell")["Turbidity"].head(20), use_container_width=True)
        st.caption("Turbidity score (NDTI-based)")
    with c2:
        st.bar_chart(df.set_index("H3 Cell")["Algal"].head(20), use_container_width=True)
        st.caption("Algal bloom score (CI-based)")
    with c3:
        st.bar_chart(df.set_index("H3 Cell")["Foam"].head(20), use_container_width=True)
        st.caption("Foam/scum score (FAI-based)")

    render_section_title("Quality Level Distribution")
    level_counts = df["Level"].value_counts().rename_axis("Level").reset_index(name="Cells")
    st.bar_chart(level_counts.set_index("Level"), use_container_width=True)

    with st.expander("Signal methodology"):
        st.markdown("""
| Signal | Index | Formula | Interpretation |
|---|---|---|---|
| **Turbidity** | NDTI | (Red − Green) / (Red + Green) | > 0 → sediment / sewage |
| **Algal** | CI | Red-Edge / Red | > 1.5 → algal bloom likely |
| **Foam/Scum** | FAI | B8 − baseline | > 0.02 → floating algae / foam |
| **Water presence** | MNDWI | (Green − SWIR1) / (Green + SWIR1) | > 0 → water body |

**WQI** = max(0.4·turbidity + 0.4·algal + 0.2·foam, individual signal maxes)
0 = clean, 1 = severely polluted
        """)


# ── Decision packets tab ───────────────────────────────────────────────────

def _render_decisions_tab(packets: list[dict], city_id: str) -> None:
    if not packets:
        st.info("No actionable water quality packets (all cells below WQI threshold or no data).")
        return

    render_section_title(f"{len(packets)} Water Quality Decision Packet(s)")

    from airos.os.decision_events import emit_water_decisions

    emit_col, _ = st.columns([2, 4])
    with emit_col:
        if st.button("Emit to Decision Log", key="water_emit_btn"):
            n = emit_water_decisions(packets, city_id)
            st.success(f"Emitted {n} water decision(s) to log.")

    for pkt in packets:
        wa    = pkt.get("water_assessment", {})
        level = wa.get("quality_level", "moderate")
        wqi   = wa.get("water_quality_index", 0.0)
        dom   = wa.get("dominant_issue", "turbidity")
        h3_id = pkt.get("h3_id", "")

        with st.expander(
            f"{_level_emoji(level)} {h3_id[:12]}… — {level.title()} (WQI {wqi:.3f}) — {dom.replace('_', ' ').title()}",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Quality Level", level.title())
                st.metric("Dominant Issue", dom.replace("_", " ").title())
            with c2:
                st.metric("WQI", f"{wqi:.3f}")
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

def render_water_panel() -> None:
    render_domain_header(
        title="Water Quality",
        caption="Sentinel-2 SR water quality indices (MNDWI / NDTI / CI / FAI) aggregated to H3 cells.",
        domain="water",
    )

    city_id, bbox, live, lookback = _city_selector()
    h3_res = _DEFAULT_H3_RES
    lat_min, lon_min = bbox["lat_min"], bbox["lon_min"]
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]

    # ── Fetch / cache water quality data ──
    # Cache key is just 6 scalars; h3_ids are computed inside the cached function.
    data_source = "demo"
    ss_key = f"water__{city_id}__{h3_res}__{lookback}__{live}"

    if ss_key not in st.session_state:
        water_cells: dict = {}
        if live:
            water_cells = load_water_quality(lat_min, lon_min, lat_max, lon_max,
                                             h3_res, lookback_days=lookback)
        if not water_cells:
            h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_res)
            water_cells = _demo_water_cells(city_id, h3_ids)
            data_source = "demo"
        else:
            data_source = "live"

        st.session_state[ss_key] = {
            "water_cells": water_cells,
            "data_source": data_source,
            "dashboard": build_water_dashboard(
                water_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
            ),
        }
        if live and not water_cells:
            st.warning(
                "No live Sentinel-2 water data available — using demo data. "
                "Set `GEE_PROJECT` env var and ensure GEE credentials are configured.",
                icon="⚠️",
            )

    cached      = st.session_state[ss_key]
    water_cells = cached["water_cells"]
    data_source = cached["data_source"]
    dashboard   = cached["dashboard"]

    summary = dashboard.get("risk_summary", {})

    # ── Warnings ──
    for w in dashboard.get("active_warnings", []):
        if w["severity"] == "error":
            st.error(w["message"], icon="🚨")
        else:
            st.warning(w["message"], icon="⚠️")

    # ── Metrics ──
    render_context_metrics(
        ("Overall Quality",    f"{_level_emoji(summary.get('overall_quality_level','good'))} {summary.get('overall_quality_level','—').title()}"),
        ("Water Cells",        summary.get("water_cells_total", 0)),
        ("Severe",             summary.get("severe_cells", 0)),
        ("Poor",               summary.get("poor_cells", 0)),
        ("Max WQI",            f"{summary.get('max_wqi', 0):.3f}"),
        ("Avg WQI",            f"{summary.get('avg_wqi', 0):.3f}"),
        ("Data Source",        f"{'🟢' if data_source == 'live' else '🟡'} {data_source}"),
    )

    # ── Signal availability info ──
    with st.expander("Signal requirements", expanded=False):
        st.markdown("""
| Signal | Source | Requirement |
|---|---|---|
| **Water quality (MNDWI/NDTI/CI/FAI)** | Sentinel-2 SR via GEE | `GEE_PROJECT` env var + service account |
| **Cloud filter** | S2 QA bands | Applied automatically (<30% cloud) |
| **Water body mask** | MNDWI > 0 | Only cells with positive MNDWI processed |
        """)

    # ── Tabs ──
    t_map, t_bodies, t_signals = st.tabs([
        "🗺️ Map", "💧 Water Bodies", "📊 Signal Breakdown",
    ])

    with t_map:
        _render_map(dashboard, bbox)
    with t_bodies:
        _render_water_bodies_tab(dashboard)
    with t_signals:
        _render_signal_tab(dashboard)
