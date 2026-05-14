"""Urban Noise Risk dashboard panel.

Proxy-based Noise Risk Index (NRI) from three signals:
  1. Source proximity   — airports, major junctions, railway yards, industrial clusters
  2. Construction CRI   — active earthworks from Sentinel-2 BSI pipeline
  3. Fire activity      — NASA FIRMS FRP (urban waste/industrial fires)

NRI is a prioritisation signal only — not a calibrated noise measurement.
WHO Environmental Noise Guidelines (2018) thresholds shown for context.
"""

from __future__ import annotations

import pandas as pd
import pydeck as pdk
from airos.network.dashboard.pydeck_utils import clean_h3_data
import streamlit as st

from airos.apps.noise.noise_pipeline import (
    build_noise_risk,
    build_noise_dashboard,
    _NOISE_SOURCES,
    _SOURCE_TYPE_COLORS,
)
from airos.network.dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from airos.network.dashboard.formatters import (
    evidence_inputs_to_rows,
    safety_gates_to_rows,
)
from airos.os.city_config import CITIES as _CITY_REGISTRY, get_bbox
from airos.network.dashboard.data_cache import (
    load_firms, load_construction_signals, h3_grid_for_bbox,
)

_DEFAULT_H3_RES = 8

# ── Colour map ─────────────────────────────────────────────────────────────

_NRI_COLORS = {
    "low":      [ 80, 200, 120, 100],
    "moderate": [255, 210,  60, 160],
    "high":     [230, 100,  20, 200],
    "severe":   [180,  20,  20, 230],
}

_LEVEL_EMOJI = {
    "low":      "🟢",
    "moderate": "🟡",
    "high":     "🟠",
    "severe":   "🔴",
}

_SOURCE_EMOJI = {
    "airport":    "✈️",
    "traffic":    "🚗",
    "railway":    "🚂",
    "industrial": "🏭",
}

def _level_emoji(level: str) -> str:
    return _LEVEL_EMOJI.get(level, "⚪")


# ── Demo data ──────────────────────────────────────────────────────────────

def _demo_noise_cells(city_id: str, h3_ids: tuple) -> dict:
    """Build synthetic noise risk by computing proximity to known sources."""
    import h3, math, random

    sources = _NOISE_SOURCES.get(city_id, [])
    rng = random.Random(hash(city_id + "noise") % (2**31))
    result = {}

    for h3_id in h3_ids:
        cell_lat, cell_lon = h3.cell_to_latlng(h3_id)
        prox_score = 0.0
        nearest = "—"
        for src in sources:
            dlat = math.radians(cell_lat - src["lat"])
            dlon = math.radians(cell_lon - src["lon"])
            a    = math.sin(dlat/2)**2 + math.cos(math.radians(cell_lat)) * math.cos(math.radians(src["lat"])) * math.sin(dlon/2)**2
            dist_km = 6371 * 2 * math.asin(math.sqrt(a))
            if dist_km <= src["radius_km"]:
                score = src["weight"] * max(0.0, 1.0 - dist_km / src["radius_km"])
                if score > prox_score:
                    prox_score = score
                    nearest = src["name"]

        if prox_score < 0.10:
            continue

        noise_var = rng.gauss(0, 0.05)
        nri = round(min(1.0, max(0.0, prox_score + noise_var)), 4)
        level = ("severe" if nri >= 0.75 else "high" if nri >= 0.50 else
                 "moderate" if nri >= 0.25 else "low")
        db_proxy = {
            "severe": "> 70 dB", "high": "60–70 dB",
            "moderate": "53–60 dB", "low": "< 53 dB",
        }[level]

        result[h3_id] = {
            "noise_risk_index":   nri,
            "risk_level":         level,
            "proximity_score":    round(prox_score, 3),
            "construction_score": 0.0,
            "fire_score":         0.0,
            "nearest_source":     nearest,
            "db_proxy":           db_proxy,
        }
    return result


# ── Controls ───────────────────────────────────────────────────────────────

def _city_selector() -> tuple[str, dict, bool, int]:
    c1, c2, c3 = st.columns([2, 2, 2])
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    with c1:
        city_label = st.selectbox("City", list(city_options.keys()), key="noise_city_selector")
    with c2:
        live = st.toggle("Live signals", value=True, key="noise_live_toggle",
                         help="Uses cached FIRMS + construction data; no additional API key required")
    with c3:
        day_range = st.selectbox("FIRMS lookback (days)", [1, 3, 7], index=2,
                                 key="noise_day_range")
    city_id = city_options[city_label]
    return city_id, get_bbox(city_id), live, int(day_range)


# ── Map layers ─────────────────────────────────────────────────────────────

def _hex_layer(cells: list[dict]) -> pdk.Layer:
    import h3 as _h3
    rows = []
    for c in cells:
        lat, lon = _h3.cell_to_latlng(c["h3_id"])
        rows.append({
            "lat":    lat, "lon":   lon,
            "h3_id":  c["h3_id"],
            "level":  c["risk_level"],
            "nri":    round(c["noise_risk_index"], 3),
            "db":     c["db_proxy"],
            "source": c["nearest_source"],
            "color":  c["color"],
        })
    return pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(rows),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 30],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.8,
    )


def _sources_layer(sources: list[dict]) -> pdk.Layer:
    rows = [{"lat": s["lat"], "lon": s["lon"],
              "name": s["name"], "type": s.get("type","traffic"),
              "color": _SOURCE_TYPE_COLORS.get(s.get("type","traffic"), [200,200,200,200])}
            for s in sources]
    return pdk.Layer(
        "ScatterplotLayer",
        data=clean_h3_data(rows),
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=200,
        pickable=True,
        opacity=0.95,
    )


def _render_map(dashboard: dict, bbox: dict) -> None:
    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    cells   = dashboard.get("risk_cells", [])
    sources = dashboard.get("noise_sources", [])
    layers  = []
    if cells:   layers.append(_hex_layer(cells))
    if sources: layers.append(_sources_layer(sources))

    if not layers:
        st.info("No noise risk cells above threshold for this city / resolution.")
        return

    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    chart = pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": (
            "<b>{h3_id}</b><br/>Level: {level} | NRI: {nri}<br/>"
            "Proxy: {db}<br/>Nearest: {source}"
        ), "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    legend_cols = st.columns(4)
    for col, (level, emoji) in zip(legend_cols, _LEVEL_EMOJI.items()):
        rgb = _NRI_COLORS[level]
        with col:
            st.markdown(
                f'<span style="color:rgb({rgb[0]},{rgb[1]},{rgb[2]})">{emoji}</span> '
                f'**{level.title()}**',
                unsafe_allow_html=True,
            )

    # Source type legend
    src_cols = st.columns(4)
    for col, (stype, emoji) in zip(src_cols, _SOURCE_EMOJI.items()):
        with col:
            st.caption(f"{emoji} {stype.title()}")


# ── Sources table tab ──────────────────────────────────────────────────────

def _render_sources_tab(dashboard: dict) -> None:
    cells   = dashboard.get("risk_cells", [])
    sources = dashboard.get("noise_sources", [])

    if cells:
        render_section_title("High-Risk Cells")
        rows = []
        for c in cells[:50]:
            rows.append({
                "H3 Cell":     c["h3_id"],
                "Level":       f"{_level_emoji(c['risk_level'])} {c['risk_level'].title()}",
                "NRI":         f"{c['noise_risk_index']:.3f}",
                "Proxy dB":    c["db_proxy"],
                "Nearest":     c["nearest_source"],
                "Prox Score":  f"{c['proximity_score']:.3f}",
                "Const Score": f"{c['construction_score']:.3f}",
                "Fire Score":  f"{c['fire_score']:.3f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if sources:
        render_section_title("Known Noise Sources")
        src_rows = []
        for s in sources:
            src_rows.append({
                "Name":        f"{_SOURCE_EMOJI.get(s.get('type','traffic'),'🔊')} {s['name']}",
                "Type":        s.get("type","").title(),
                "Weight":      f"{s.get('weight',0):.2f}",
                "Radius (km)": s.get("radius_km", 0),
                "Lat":         s["lat"],
                "Lon":         s["lon"],
            })
        st.dataframe(pd.DataFrame(src_rows), use_container_width=True, hide_index=True)


# ── Signal breakdown tab ───────────────────────────────────────────────────

def _render_signal_tab(dashboard: dict) -> None:
    cells = dashboard.get("risk_cells", [])
    if not cells:
        st.info("No noise risk cells detected.")
        return

    df = pd.DataFrame([{
        "H3 Cell":         c["h3_id"],
        "Level":           c["risk_level"],
        "NRI":             c["noise_risk_index"],
        "Proximity":       c["proximity_score"],
        "Construction":    c["construction_score"],
        "Fire":            c["fire_score"],
    } for c in cells])

    render_section_title("NRI Component Breakdown")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.bar_chart(df.set_index("H3 Cell")["Proximity"].head(20), use_container_width=True)
        st.caption("Proximity score (airports / roads / industry)")
    with c2:
        st.bar_chart(df.set_index("H3 Cell")["Construction"].head(20), use_container_width=True)
        st.caption("Construction noise boost (BSI CRI)")
    with c3:
        st.bar_chart(df.set_index("H3 Cell")["Fire"].head(20), use_container_width=True)
        st.caption("Industrial fire noise boost (FIRMS FRP)")

    render_section_title("Risk Level Distribution")
    level_counts = df["Level"].value_counts().rename_axis("Level").reset_index(name="Cells")
    st.bar_chart(level_counts.set_index("Level"), use_container_width=True)

    with st.expander("NRI methodology & WHO guidelines"):
        st.markdown("""
**Noise Risk Index (NRI)** is a proxy computed from available satellite signals — not a calibrated sound level.

| Signal | Contribution | Basis |
|---|---|---|
| Source proximity | Up to 1.0 | Haversine distance from airports/roads/industry, weighted by source strength |
| Construction CRI | Up to 0.3 × CRI | Sentinel-2 BSI — earthworks and machinery |
| Fire FRP | Up to 0.2 | NASA FIRMS — urban/industrial burning |

**NRI → dB proxy** (approximate, not calibrated):

| NRI | dB proxy | WHO guideline |
|---|---|---|
| < 0.25 | < 53 dB | ✅ Below road traffic day limit (53 dB) |
| 0.25–0.50 | 53–60 dB | ⚠️ Approaching transport zone limit |
| 0.50–0.75 | 60–70 dB | 🟠 Industrial zone range |
| > 0.75 | > 70 dB | 🔴 Near major airport / interchange |

WHO Environmental Noise Guidelines (Europe, 2018) — adapted for South Asian urban context.
        """)


# ── Decision packets tab ───────────────────────────────────────────────────

def _render_decisions_tab(packets: list[dict], city_id: str) -> None:
    if not packets:
        st.info("No high/severe noise packets above threshold.")
        return

    render_section_title(f"{len(packets)} Noise Risk Packet(s)")

    from airos.os.decision_events import emit_noise_decisions

    emit_col, _ = st.columns([2, 4])
    with emit_col:
        if st.button("Emit to Decision Log", key="noise_emit_btn"):
            n = emit_noise_decisions(packets, city_id)
            st.success(f"Emitted {n} noise decision(s) to log.")

    for pkt in packets:
        na    = pkt.get("noise_assessment", {})
        level = na.get("risk_level", "high")
        nri   = na.get("noise_risk_index", 0.0)
        dom   = na.get("dominant_source", "traffic_corridor")
        db    = na.get("db_proxy", "—")
        h3_id = pkt.get("h3_id", "")

        with st.expander(
            f"{_level_emoji(level)} {h3_id[:12]}… — {level.title()} "
            f"(NRI {nri:.3f} | {db}) — {dom.replace('_',' ').title()}",
            expanded=False,
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Risk Level", level.title())
                st.metric("Dominant Source", dom.replace("_", " ").title())
            with c2:
                st.metric("NRI", f"{nri:.3f}")
                st.metric("dB Proxy", db)

            st.caption(f"Nearest known source: **{na.get('nearest_source','—')}**")

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

def render_noise_panel() -> None:
    render_domain_header(
        title="Noise Pollution",
        caption=(
            "Proxy Noise Risk Index from source proximity (airports / roads / industry), "
            "construction activity (Sentinel-2 BSI), and fire/industrial burning (NASA FIRMS). "
            "NRI is a prioritisation signal — acoustic measurement required for enforcement."
        ),
        domain="noise",
    )

    city_id, bbox, live, day_range = _city_selector()
    h3_res = _DEFAULT_H3_RES
    lat_min, lon_min = bbox["lat_min"], bbox["lon_min"]
    lat_max, lon_max = bbox["lat_max"], bbox["lon_max"]

    ss_key = f"noise__{city_id}__{h3_res}__{day_range}__{live}"

    if ss_key not in st.session_state:
        h3_ids = h3_grid_for_bbox(lat_min, lon_min, lat_max, lon_max, h3_res)

        # Pull construction and fire signals from shared cache — no new API calls
        construction_cells: dict = {}
        firms_df = pd.DataFrame()
        if live:
            construction_cells = load_construction_signals(
                lat_min, lon_min, lat_max, lon_max, h3_res,
            )
            raw_firms = load_firms(lat_min, lon_min, lat_max, lon_max, day_range)
            firms_df  = raw_firms if isinstance(raw_firms, pd.DataFrame) else pd.DataFrame()

        # Compute noise risk (pure Python, uses proximity model + signal boosts)
        noise_cells = build_noise_risk(
            h3_ids, city_id, construction_cells, firms_df,
            lat_min, lon_min, lat_max, lon_max,
        )

        # Fall back to demo proximity model if nothing computed
        if not noise_cells:
            noise_cells = _demo_noise_cells(city_id, h3_ids)

        data_source = "live signals" if (construction_cells or not firms_df.empty) else "proximity model"

        st.session_state[ss_key] = {
            "noise_cells": noise_cells,
            "data_source": data_source,
            "dashboard":   build_noise_dashboard(
                noise_cells, h3_res, city_id, lat_min, lon_min, lat_max, lon_max,
            ),
        }

    cached      = st.session_state[ss_key]
    data_source = cached["data_source"]
    dashboard   = cached["dashboard"]

    summary = dashboard.get("risk_summary", {})

    for w in dashboard.get("active_warnings", []):
        if w["severity"] == "error":
            st.error(w["message"], icon="🚨")
        elif w["severity"] == "warning":
            st.warning(w["message"], icon="⚠️")
        else:
            st.info(w["message"], icon="ℹ️")

    render_context_metrics(
        ("Overall Risk",    f"{_level_emoji(summary.get('overall_risk_level','low'))} {summary.get('overall_risk_level','—').title()}"),
        ("Total Cells",     summary.get("total_cells", 0)),
        ("Severe (>70 dB)", summary.get("severe_cells", 0)),
        ("High (60–70 dB)", summary.get("high_cells", 0)),
        ("Moderate",        summary.get("moderate_cells", 0)),
        ("Max NRI",         f"{summary.get('max_nri', 0):.3f}"),
        ("Avg NRI",         f"{summary.get('avg_nri', 0):.3f}"),
        ("Signals",         f"{'🟢' if 'live' in data_source else '🟡'} {data_source}"),
    )

    t_map, t_sources, t_signals = st.tabs([
        "🗺️ Map", "🔊 Noise Sources", "📊 Signal Breakdown",
    ])

    with t_map:
        _render_map(dashboard, bbox)
    with t_sources:
        _render_sources_tab(dashboard)
    with t_signals:
        _render_signal_tab(dashboard)
