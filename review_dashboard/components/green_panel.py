"""Urban Green Cover Change dashboard panel.

Sentinel-2 NDVI/EVI change detection vs. 12-month baseline:
  NDVI  (NIR − Red) / (NIR + Red)    overall greenness
  EVI   enhanced vegetation index     canopy-sensitive
  ΔNDVI current − baseline            change magnitude

GCCI (Green Cover Change Index): −1 = severe loss, +1 = dense gain.
"""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from urban_platform.applications.green.green_pipeline import (
    build_green_dashboard,
    build_green_decision_packets,
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
from review_dashboard.data_cache import load_green_cover, h3_grid_for_bbox


# ── Colour maps ────────────────────────────────────────────────────────────

_CHANGE_COLORS = {
    "severe_loss":      [180,  20,  20, 230],
    "high_loss":        [230,  80,  20, 210],
    "moderate_loss":    [255, 160,  40, 180],
    "stable":           [100, 200,  80, 100],
    "moderate_gain":    [ 40, 160,  80, 170],
    "significant_gain": [  0, 100,  40, 210],
}

_CHANGE_EMOJI = {
    "severe_loss":      "🔴",
    "high_loss":        "🟠",
    "moderate_loss":    "🟡",
    "stable":           "🟢",
    "moderate_gain":    "💚",
    "significant_gain": "🌳",
}

_TYPE_ICON = {
    "park":        "🌳",
    "forest":      "🌲",
    "wetland":     "🌿",
    "urban_green": "🪴",
}

def _change_emoji(level: str) -> str:
    return _CHANGE_EMOJI.get(level, "⚪")


# ── Demo data ──────────────────────────────────────────────────────────────

def _demo_green_cells(city_id: str, h3_ids: tuple) -> dict:
    import random
    rng = random.Random(hash(city_id + "green") % (2**31))

    city_presets = {
        "bangalore": {"frac": 0.30, "loss_bias": 0.55},
        "hyderabad": {"frac": 0.25, "loss_bias": 0.45},
        "chennai":   {"frac": 0.25, "loss_bias": 0.40},
        "mumbai":    {"frac": 0.28, "loss_bias": 0.50},
        "delhi":     {"frac": 0.32, "loss_bias": 0.60},
        "pune":      {"frac": 0.22, "loss_bias": 0.35},
    }
    preset = city_presets.get(city_id, {"frac": 0.25, "loss_bias": 0.40})

    result = {}
    sample = rng.sample(list(h3_ids), max(1, int(len(h3_ids) * preset["frac"])))
    for h3_id in sample:
        ndvi_baseline = round(rng.uniform(0.25, 0.70), 4)
        # Bias towards loss but include some gain
        if rng.random() < preset["loss_bias"]:
            delta = round(rng.gauss(-0.12, 0.08), 4)
        else:
            delta = round(rng.gauss(0.06, 0.05), 4)
        ndvi_curr = round(max(0.0, min(1.0, ndvi_baseline + delta)), 4)
        evi_curr  = round(ndvi_curr * rng.uniform(0.7, 0.9), 4)
        gcci      = round(max(-1.0, min(1.0, delta * 4)), 4)

        if ndvi_curr >= 0.6:      cov = "dense"
        elif ndvi_curr >= 0.4:    cov = "moderate"
        elif ndvi_curr >= 0.2:    cov = "sparse"
        else:                     cov = "bare"

        if delta < -0.15:         cat = "significant_loss"
        elif delta < -0.05:       cat = "moderate_loss"
        elif delta > 0.05:        cat = "gain"
        else:                     cat = "stable"

        result[h3_id] = {
            "ndvi":                     ndvi_curr,
            "evi":                      evi_curr,
            "ndvi_baseline":            ndvi_baseline,
            "ndvi_change":              round(delta, 4),
            "change_category":          cat,
            "coverage_class":           cov,
            "green_cover_change_index": gcci,
        }
    return result


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, int, bool, int, int]:
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="green_city_selector")
    with c2:
        h3_res = st.slider("H3 resolution", min_value=7, max_value=10, value=9, key="green_h3_res")
    with c3:
        live = st.toggle("Live data", value=True, key="green_live_toggle",
                         help="Requires GEE_PROJECT for Sentinel-2 access")
    with c4:
        recent = st.selectbox("Recent window (days)", [15, 30, 60], index=1,
                              key="green_recent_days",
                              help="Sentinel-2 composite window for current state")
    with c5:
        baseline = st.selectbox("Baseline (days)", [180, 365, 730], index=1,
                                key="green_baseline_days",
                                help="Historical window for change baseline")
    city_id = city_options[city_label]
    return city_id, get_bbox(city_id), h3_res, live, int(recent), int(baseline)


# ── Map layers ─────────────────────────────────────────────────────────────

def _hex_layer(cells: list[dict], mode: str = "change") -> pdk.Layer:
    import h3 as _h3
    rows = []
    for c in cells:
        lat, lon = _h3.cell_to_latlng(c["h3_id"])
        rows.append({
            "lat":    lat,
            "lon":    lon,
            "h3_id":  c["h3_id"],
            "level":  c["change_level"],
            "gcci":   round(c["green_cover_change_index"], 3),
            "delta":  f"{c['ndvi_change']:+.3f}",
            "ndvi":   round(c["ndvi"], 3),
            "cover":  c["coverage_class"],
            "color":  c["color"] if mode == "change" else c["coverage_color"],
        })
    return pdk.Layer(
        "H3HexagonLayer",
        data=rows,
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 30],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.8,
    )


def _green_spaces_layer(spaces: list[dict]) -> pdk.Layer:
    rows = [{"lat": s["lat"], "lon": s["lon"],
              "name": s["name"], "type": s.get("type", "park"),
              "color": [0, 180, 80, 220]} for s in spaces]
    return pdk.Layer(
        "ScatterplotLayer",
        data=rows,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=300,
        pickable=True,
        opacity=0.9,
    )


def _render_map(dashboard: dict, bbox: dict, mode: str) -> None:
    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    cells  = dashboard.get("all_cells", [])
    spaces = dashboard.get("known_green_spaces", [])
    layers = []
    if cells:
        layers.append(_hex_layer(cells, mode=mode))
    if spaces:
        layers.append(_green_spaces_layer(spaces))

    if not layers:
        st.info("No vegetated cells detected for this city / resolution.")
        return

    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    tooltip_html = (
        "<b>{h3_id}</b><br/>"
        "Level: {level}<br/>"
        "GCCI: {gcci} | ΔNDVI: {delta}<br/>"
        "NDVI: {ndvi} | Coverage: {cover}"
    )
    chart = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": tooltip_html, "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    # Legend
    if mode == "change":
        legend_items = list(_CHANGE_EMOJI.items())
    else:
        legend_items = [("dense","🌳"),("moderate","🌿"),("sparse","🍃"),("bare","🏜️")]

    cols = st.columns(len(legend_items))
    for col, (level, emoji) in zip(cols, legend_items):
        with col:
            st.markdown(f"{emoji} **{level.replace('_',' ').title()}**")


# ── Cover table tab ────────────────────────────────────────────────────────

def _render_cover_tab(dashboard: dict) -> None:
    cells  = dashboard.get("all_cells", [])
    spaces = dashboard.get("known_green_spaces", [])

    if cells:
        render_section_title("All Vegetated Cells")
        rows = []
        for c in sorted(cells, key=lambda x: x["green_cover_change_index"])[:60]:
            rows.append({
                "H3 Cell":   c["h3_id"],
                "Change":    f"{_change_emoji(c['change_level'])} {c['change_level'].replace('_',' ').title()}",
                "GCCI":      f"{c['green_cover_change_index']:+.3f}",
                "ΔNDVI":     f"{c['ndvi_change']:+.3f}",
                "NDVI Now":  f"{c['ndvi']:.3f}",
                "Baseline":  f"{c['ndvi_baseline']:.3f}",
                "Coverage":  c["coverage_class"].title(),
                "EVI":       f"{c['evi']:.3f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if spaces:
        render_section_title("Known Green Spaces")
        space_rows = []
        for s in spaces:
            icon = _TYPE_ICON.get(s.get("type", "park"), "🌳")
            space_rows.append({
                "Name":  f"{icon} {s['name']}",
                "Type":  s.get("type", "park").replace("_", " ").title(),
                "Lat":   s["lat"],
                "Lon":   s["lon"],
            })
        st.dataframe(pd.DataFrame(space_rows), use_container_width=True, hide_index=True)


# ── Signal breakdown tab ───────────────────────────────────────────────────

def _render_signal_tab(dashboard: dict) -> None:
    cells = dashboard.get("all_cells", [])
    if not cells:
        st.info("No vegetated cells detected.")
        return

    df = pd.DataFrame([{
        "H3 Cell":  c["h3_id"],
        "Level":    c["change_level"],
        "GCCI":     c["green_cover_change_index"],
        "ΔNDVI":    c["ndvi_change"],
        "NDVI":     c["ndvi"],
    } for c in cells])

    render_section_title("NDVI Change Distribution")
    c1, c2 = st.columns(2)
    with c1:
        st.bar_chart(
            df.sort_values("ΔNDVI").set_index("H3 Cell")["ΔNDVI"].head(30),
            use_container_width=True,
        )
        st.caption("ΔNDVI (current − baseline) — negative = loss")
    with c2:
        st.bar_chart(
            df.set_index("H3 Cell")["NDVI"].head(30),
            use_container_width=True,
        )
        st.caption("Current NDVI")

    render_section_title("Change Level Breakdown")
    level_counts = df["Level"].value_counts().rename_axis("Level").reset_index(name="Cells")
    st.bar_chart(level_counts.set_index("Level"), use_container_width=True)

    loss  = dashboard.get("loss_cells", [])
    gain  = dashboard.get("gain_cells", [])
    c1, c2, c3 = st.columns(3)
    c1.metric("Loss cells",  len(loss))
    c2.metric("Gain cells",  len(gain))
    c3.metric("Stable cells", len(cells) - len(loss) - len(gain))

    with st.expander("Signal methodology"):
        st.markdown("""
| Signal | Formula | Interpretation |
|---|---|---|
| **NDVI** | (NIR − Red) / (NIR + Red) | > 0.4 = moderate canopy; > 0.6 = dense |
| **EVI** | 2.5 × (NIR−Red) / (NIR + 6Red − 7.5Blue + 1) | Less saturated in dense canopy |
| **ΔNDVI** | current − 12-month baseline | Negative = loss; positive = gain |
| **GCCI** | clip(ΔNDVI × 4, −1, 1) | Scaled change index for decision thresholds |

Change categories: significant_loss ΔNDVI < −0.15 · moderate_loss −0.15 to −0.05 · stable ±0.05 · gain > 0.05
        """)


# ── Decision packets tab ───────────────────────────────────────────────────

def _render_decisions_tab(packets: list[dict], city_id: str) -> None:
    if not packets:
        st.info("No loss packets above threshold (all cells stable/gaining or no data).")
        return

    render_section_title(f"{len(packets)} Green Cover Loss Packet(s)")

    from urban_platform.decision_events import emit_green_decisions

    emit_col, _ = st.columns([2, 4])
    with emit_col:
        if st.button("Emit to Decision Log", key="green_emit_btn"):
            n = emit_green_decisions(packets, city_id)
            st.success(f"Emitted {n} green cover decision(s) to log.")

    for pkt in packets:
        ga    = pkt.get("green_assessment", {})
        level = ga.get("change_level", "moderate_loss")
        gcci  = ga.get("green_cover_change_index", 0.0)
        delta = ga.get("ndvi_change", 0.0)
        h3_id = pkt.get("h3_id", "")

        with st.expander(
            f"{_change_emoji(level)} {h3_id[:12]}… — {level.replace('_',' ').title()} "
            f"(GCCI {gcci:+.3f}, ΔNDVI {delta:+.3f})",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Change Level", level.replace("_", " ").title())
                st.metric("Coverage Class", ga.get("coverage_class", "—").title())
            with c2:
                st.metric("GCCI", f"{gcci:+.3f}")
                st.metric("ΔNDVI", f"{delta:+.3f}")

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

def render_green_panel() -> None:
    render_domain_header(
        title="Urban Green Cover Change",
        caption=(
            "Sentinel-2 NDVI/EVI change detection vs. historical baseline — "
            "tracks canopy loss from construction/felling and green cover gain from plantation."
        ),
    )

    city_id, bbox, h3_res, live, recent_days, baseline_days = _city_selector()
    lat_min, lon_min = bbox["lat_min"], bbox["lon_min"]
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]

    ss_key = f"green__{city_id}__{h3_res}__{recent_days}__{baseline_days}__{live}"

    if ss_key not in st.session_state:
        green_cells: dict = {}
        data_source = "demo"

        if live:
            green_cells = load_green_cover(
                lat_min, lon_min, lat_max, lon_max,
                h3_res,
                recent_days=recent_days,
                baseline_days=baseline_days,
            )
            if green_cells:
                data_source = "live"
            else:
                st.warning(
                    "No live Sentinel-2 green cover data — using demo data. "
                    "Set `GEE_PROJECT` env var to enable live satellite access.",
                    icon="⚠️",
                )

        if not green_cells:
            h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_res)
            green_cells = _demo_green_cells(city_id, h3_ids)
            data_source = "demo"

        packets_green = build_green_decision_packets(
            green_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
        )

        st.session_state[ss_key] = {
            "green_cells": green_cells,
            "data_source": data_source,
            "dashboard":   build_green_dashboard(
                green_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
            ),
            "packets":     packets_green,
        }

    cached      = st.session_state[ss_key]
    data_source = cached["data_source"]
    dashboard   = cached["dashboard"]
    packets     = cached["packets"]

    summary = dashboard.get("risk_summary", {})

    for w in dashboard.get("active_warnings", []):
        if w["severity"] == "error":
            st.error(w["message"], icon="🚨")
        else:
            st.warning(w["message"], icon="⚠️")

    render_context_metrics(
        ("Overall Status",  f"{_change_emoji(summary.get('overall_status','stable'))} {summary.get('overall_status','—').replace('_',' ').title()}"),
        ("Total Cells",     summary.get("total_cells", 0)),
        ("Severe Loss",     summary.get("severe_loss", 0)),
        ("High Loss",       summary.get("high_loss", 0)),
        ("Moderate Loss",   summary.get("moderate_loss", 0)),
        ("Gain Cells",      summary.get("gain", 0)),
        ("Avg NDVI",        f"{summary.get('avg_ndvi', 0):.3f}"),
        ("Data Source",     f"{'🟢' if data_source == 'live' else '🟡'} {data_source}"),
    )

    with st.expander("Signal requirements", expanded=False):
        st.markdown("""
| Signal | Source | Requirement |
|---|---|---|
| **NDVI / EVI (current)** | Sentinel-2 SR via GEE | `GEE_PROJECT` + service account |
| **NDVI baseline** | Sentinel-2 SR 12-month median | Same GEE credentials |
| **Cloud filter** | S2 QA bands | <30% cloud cover applied automatically |
        """)

    map_mode = st.radio("Map colour mode", ["Change (ΔNDVI)", "Coverage (NDVI)"],
                        horizontal=True, key="green_map_mode")
    mode = "change" if "Change" in map_mode else "coverage"

    t_map, t_cover, t_signals, t_decisions = st.tabs([
        "🗺️ Map", "🌳 Green Spaces", "📊 Signal Breakdown", "📋 Decision Packets",
    ])

    with t_map:
        _render_map(dashboard, bbox, mode)
    with t_cover:
        _render_cover_tab(dashboard)
    with t_signals:
        _render_signal_tab(dashboard)
    with t_decisions:
        _render_decisions_tab(packets, city_id)
