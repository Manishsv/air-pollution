"""Terrain context panel — elevation, slope, aspect, ruggedness per H3 cell.

Reads SRTM/Copernicus-derived terrain signals from the H3 knowledge store.
Structural-context panel only: no risk assessments, no decision packets.
TERRAIN_CLASS is shown when the agent has computed it; otherwise cells
display the 5 ingestor-written signals.

Colour maps
-----------
Elevation  : cool blue (low) → warm brown (high)  — standard hypsometric tint
Slope      : green (flat) → orange → red (steep)
Terrain class: fixed palette keyed on domain spec enum values
"""
from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from airos.network.dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
)

logger = logging.getLogger(__name__)

# ── Colour maps ────────────────────────────────────────────────────────────

# Terrain class → RGBA for pydeck H3HexagonLayer
_CLASS_COLOR: dict[str, list[int]] = {
    "valley":      [ 80, 160, 230, 200],   # blue
    "plain":       [180, 210, 140, 180],   # light green
    "hill":        [180, 140,  80, 200],   # tan/brown
    "ridge":       [140,  90,  60, 220],   # dark brown
    "escarpment":  [200,  60,  40, 230],   # red-brown
    "water_body":  [ 40, 120, 200, 180],   # deep blue
    None:          [100, 100, 100, 120],   # grey (unclassified)
}

_CLASS_LABEL: dict[str | None, str] = {
    "valley":     "🔵 Valley",
    "plain":      "🟢 Plain",
    "hill":       "🟤 Hill",
    "ridge":      "🔶 Ridge",
    "escarpment": "🔴 Escarpment",
    "water_body": "💧 Water body",
    None:         "⚪ Unclassified",
}


def _elev_color(elev: float, elev_min: float, elev_max: float) -> list[int]:
    """Hypsometric tint: blue (low) → green → tan → brown (high)."""
    span = elev_max - elev_min if elev_max > elev_min else 1.0
    t = max(0.0, min(1.0, (elev - elev_min) / span))
    if t < 0.33:
        r = int(50  + t * 3 * 100)
        g = int(120 + t * 3 * 80)
        b = int(220 - t * 3 * 80)
    elif t < 0.66:
        s = (t - 0.33) * 3
        r = int(150 + s * 80)
        g = int(200 - s * 40)
        b = int(140 - s * 80)
    else:
        s = (t - 0.66) * 3
        r = int(230 - s * 30)
        g = int(160 - s * 60)
        b = int(60  - s * 20)
    return [r, g, b, 200]


def _slope_color(slope: float) -> list[int]:
    """Slope colour: green (flat 0°) → yellow → orange → red (steep >20°)."""
    t = max(0.0, min(1.0, slope / 25.0))
    if t < 0.5:
        r = int(t * 2 * 255)
        g = 200
        b = 40
    else:
        r = 255
        g = int(200 - (t - 0.5) * 2 * 180)
        b = 40
    return [r, g, b, 200]


# ── Data loading ───────────────────────────────────────────────────────────

def _load_terrain_signals(city_id: str) -> pd.DataFrame:
    """Pull latest terrain signals for all H3 cells in the city."""
    try:
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            """
            SELECT s.h3_id, s.signal_name AS signal, s.value, s.unit,
                   s.recorded_at
            FROM   h3_signals s
            JOIN   h3_cell_metadata m ON m.h3_id = s.h3_id
            WHERE  m.city_id = ?
              AND  s.domain  = 'terrain'
              AND  s.recorded_at = (
                       SELECT MAX(s2.recorded_at)
                       FROM   h3_signals s2
                       WHERE  s2.h3_id       = s.h3_id
                         AND  s2.domain      = 'terrain'
                         AND  s2.signal_name = s.signal_name
                   )
            ORDER BY s.h3_id, s.signal_name
            """,
            [city_id],
        )
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        logger.debug("Terrain signal load failed (%s): %s", city_id, exc)
        return pd.DataFrame()


def _pivot(df: pd.DataFrame) -> pd.DataFrame:
    """Long → wide: one row per H3 cell, signals as columns."""
    if df.empty:
        return pd.DataFrame()
    wide = (
        df.pivot_table(index="h3_id", columns="signal", values="value", aggfunc="last")
        .reset_index()
    )
    return wide


# ── Map rendering ──────────────────────────────────────────────────────────

def _render_map(wide: pd.DataFrame, bbox: dict, colour_by: str) -> None:
    try:
        import pydeck as pdk
        from airos.network.dashboard.pydeck_utils import clean_h3_data
        import h3 as _h3
    except ImportError:
        st.info("Install pydeck for the map view: `pip install pydeck`")
        return

    if wide.empty:
        st.info("No terrain data to map.")
        return

    elev_col  = wide["ELEVATION_M"]      if "ELEVATION_M"     in wide.columns else None
    slope_col = wide["SLOPE_DEG"]        if "SLOPE_DEG"       in wide.columns else None
    class_col = wide["TERRAIN_CLASS"]    if "TERRAIN_CLASS"   in wide.columns else None
    conf_col  = wide["DATA_CONFIDENCE"]  if "DATA_CONFIDENCE" in wide.columns else None

    elev_min = float(elev_col.min()) if elev_col is not None else 0.0
    elev_max = float(elev_col.max()) if elev_col is not None else 1000.0

    rows = []
    for _, row in wide.iterrows():
        h3_id = row["h3_id"]
        try:
            lat, lon = _h3.cell_to_latlng(h3_id)
        except Exception:
            continue

        elev   = row.get("ELEVATION_M")
        slope  = row.get("SLOPE_DEG")
        aspect = row.get("ASPECT_DEG")
        tc     = row.get("TERRAIN_CLASS")
        conf   = row.get("DATA_CONFIDENCE", 0.9)

        if colour_by == "elevation" and elev is not None:
            color = _elev_color(float(elev), elev_min, elev_max)
        elif colour_by == "slope" and slope is not None:
            color = _slope_color(float(slope))
        elif colour_by == "terrain_class":
            color = _CLASS_COLOR.get(tc, _CLASS_COLOR[None])
        else:
            color = [120, 120, 120, 140]

        rows.append({
            "h3_id":   h3_id,
            "lat":     lat,
            "lon":     lon,
            "elev":    round(float(elev),  1) if elev  is not None else None,
            "slope":   round(float(slope), 2) if slope is not None else None,
            "aspect":  round(float(aspect),1) if aspect is not None else None,
            "class":   tc or "unclassified",
            "conf":    round(float(conf),  2) if conf  is not None else None,
            "color":   color,
        })

    if not rows:
        st.info("No cells with valid terrain data.")
        return

    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    layer = pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(rows),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 20],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.85,
    )

    tooltip_html = (
        "<b>{h3_id}</b><br/>"
        "Elevation: {elev} m<br/>"
        "Slope: {slope}° | Aspect: {aspect}°<br/>"
        "Class: {class}<br/>"
        "Confidence: {conf}"
    )

    chart = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            latitude=lat_c, longitude=lon_c, zoom=11, pitch=0
        ),
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": tooltip_html, "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    # Colour legend
    if colour_by == "terrain_class":
        present_classes = wide["TERRAIN_CLASS"].dropna().unique().tolist() if class_col is not None else []
        legend = {k: v for k, v in _CLASS_LABEL.items() if k in present_classes or k is None}
        cols = st.columns(min(len(legend), 6))
        for col, (tc_key, label) in zip(cols, legend.items()):
            with col:
                st.markdown(f"**{label}**")
    elif colour_by == "elevation":
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"🔵 Low  (~{elev_min:.0f} m)")
        c2.markdown(f"🟢 Mid  (~{(elev_min+elev_max)/2:.0f} m)")
        c3.markdown(f"🟤 High (~{elev_max:.0f} m)")
    elif colour_by == "slope":
        c1, c2, c3 = st.columns(3)
        c1.markdown("🟢 Flat (0–5°)")
        c2.markdown("🟡 Gentle (5–15°)")
        c3.markdown("🔴 Steep (>15°)")


# ── Signal breakdown tab ───────────────────────────────────────────────────

def _render_signals_tab(wide: pd.DataFrame) -> None:
    if wide.empty:
        st.info("No terrain signals available.")
        return

    # Terrain class distribution
    if "TERRAIN_CLASS" in wide.columns:
        render_section_title("Terrain class distribution")
        tc_counts = (
            wide["TERRAIN_CLASS"]
            .fillna("unclassified")
            .value_counts()
            .rename_axis("Class")
            .reset_index(name="Cells")
        )
        st.bar_chart(tc_counts.set_index("Class"), use_container_width=True, height=220)
        agent_classified = int(wide["TERRAIN_CLASS"].notna().sum())
        total = len(wide)
        st.caption(
            f"Agent-classified: {agent_classified}/{total} cells. "
            "Unclassified cells are low-confidence (void-fill) and awaiting re-classification."
        )

    # Elevation histogram
    if "ELEVATION_M" in wide.columns:
        render_section_title("Elevation distribution (m)")
        elev_data = wide["ELEVATION_M"].dropna()
        st.bar_chart(
            elev_data.value_counts(bins=20).sort_index().rename("cells"),
            use_container_width=True, height=200,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Min",    f"{elev_data.min():.0f} m")
        c2.metric("Max",    f"{elev_data.max():.0f} m")
        c3.metric("Mean",   f"{elev_data.mean():.0f} m")
        c4.metric("Std dev",f"{elev_data.std():.1f} m")

    # Slope distribution
    if "SLOPE_DEG" in wide.columns:
        render_section_title("Slope distribution (°)")
        slope_data = wide["SLOPE_DEG"].dropna()
        st.bar_chart(
            slope_data.value_counts(bins=15).sort_index().rename("cells"),
            use_container_width=True, height=180,
        )
        steep = int((slope_data >= 20).sum())
        if steep:
            st.warning(
                f"⚠️ {steep} cell(s) with slope ≥ 20° — flagged as steep/escarpment. "
                "Construction permit decisions on these cells require a geotechnical survey.",
                icon="⚠️",
            )

    # Confidence breakdown
    if "DATA_CONFIDENCE" in wide.columns:
        render_section_title("Data confidence")
        conf = wide["DATA_CONFIDENCE"].fillna(0)
        full      = int((conf >= 0.85).sum())
        void_fill = int(((conf >= 0.60) & (conf < 0.85)).sum())
        synthetic = int((conf < 0.60).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Full (0.90)",       full,      help="Clean SRTM/Copernicus pixels")
        c2.metric("Void-filled (0.65)", void_fill, help="Interpolated — reduced confidence")
        c3.metric("Synthetic (0.0)",    synthetic, help="Blocked from operational use")
        if void_fill or synthetic:
            st.info(
                "Cells with DATA_CONFIDENCE < 0.70 will not be used for precision "
                "construction slope decisions (spec safety gate: "
                "`block_void_filled_cells_for_precision_decisions`)."
            )


# ── Per-cell table tab ─────────────────────────────────────────────────────

def _render_table_tab(wide: pd.DataFrame) -> None:
    if wide.empty:
        st.info("No terrain signals available.")
        return

    render_section_title("Per-cell signals")
    display_cols = ["h3_id"] + [
        c for c in [
            "ELEVATION_M", "SLOPE_DEG", "ASPECT_DEG",
            "RUGGEDNESS_INDEX", "DATA_CONFIDENCE", "TERRAIN_CLASS",
        ]
        if c in wide.columns
    ]
    display = wide[display_cols].copy()

    # Format numerics
    for col in display.columns:
        if col in ("h3_id", "TERRAIN_CLASS"):
            continue
        display[col] = display[col].apply(
            lambda v: round(float(v), 3) if v is not None and str(v) != "nan" else None
        )

    st.dataframe(display, hide_index=True, use_container_width=True)
    st.caption(
        f"{len(display)} cells shown. "
        "TERRAIN_CLASS is agent-derived — absent if the agent has not yet run."
    )


# ── Main entry point ───────────────────────────────────────────────────────

def render_terrain_panel() -> None:
    """Main entry point — called from app.py _DOMAIN_PANELS."""
    render_domain_header(
        title="Terrain Context",
        caption=(
            "SRTM / Copernicus 30 m DEM — elevation, slope, aspect, and ruggedness "
            "per H3 cell. Structural context used by Flood, Heat, Air, Construction, "
            "and Water agents. No risk assessments generated directly."
        ),
        primary_alert=(
            "Terrain is static context — not a risk signal. "
            "It must not be used as the sole basis for any operational recommendation "
            "(spec safety gate: block_terrain_as_sole_risk_basis)."
        ),
        primary_alert_kind="info",
    )

    # ── City selector ──────────────────────────────────────────────────────
    try:
        from airos.drivers.store.ingestor import ALL_CITIES
        from airos.os.city_config import get_bbox
        cities = ALL_CITIES
    except Exception:
        cities = ["bangalore", "hyderabad", "mumbai", "delhi", "chennai", "pune"]
        get_bbox = None  # type: ignore[assignment]

    city_id = st.selectbox(
        "City", cities, index=0, key="terrain_city_selector",
    )

    try:
        from airos.os.city_config import get_bbox as _get_bbox
        bbox = _get_bbox(city_id)
    except Exception:
        bbox = {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}

    # ── Load data ──────────────────────────────────────────────────────────
    cache_key = f"terrain__{city_id}"
    if cache_key not in st.session_state:
        with st.spinner("Loading terrain signals …"):
            raw = _load_terrain_signals(city_id)
        st.session_state[cache_key] = raw
    else:
        raw = st.session_state[cache_key]

    wide = _pivot(raw)

    # ── No data state ──────────────────────────────────────────────────────
    if wide.empty:
        st.info(
            f"No terrain signals found for **{city_id}**. "
            "The terrain driver runs quarterly — trigger a manual ingest to populate:\n\n"
            f"`python main.py --step ingest-h3 --domains terrain --cities {city_id}`"
        )
        if st.button("🔄 Refresh", key="terrain_refresh_empty"):
            st.session_state.pop(cache_key, None)
            st.rerun()
        return

    # ── Summary metrics ────────────────────────────────────────────────────
    elev_col   = wide["ELEVATION_M"]     if "ELEVATION_M"     in wide.columns else pd.Series(dtype=float)
    slope_col  = wide["SLOPE_DEG"]       if "SLOPE_DEG"       in wide.columns else pd.Series(dtype=float)
    conf_col   = wide["DATA_CONFIDENCE"] if "DATA_CONFIDENCE" in wide.columns else pd.Series(dtype=float)
    class_col  = wide["TERRAIN_CLASS"]   if "TERRAIN_CLASS"   in wide.columns else pd.Series(dtype=str)

    total_cells     = len(wide)
    classified      = int(class_col.notna().sum()) if not class_col.empty else 0
    elev_range      = f"{elev_col.min():.0f}–{elev_col.max():.0f} m" if not elev_col.empty else "—"
    avg_slope       = f"{slope_col.mean():.1f}°" if not slope_col.empty else "—"
    low_conf_cells  = int((conf_col < 0.70).sum()) if not conf_col.empty else 0

    last_ts = "—"
    if "recorded_at" in raw.columns and not raw["recorded_at"].isna().all():
        last_ts = str(raw["recorded_at"].max())[:16].replace("T", " ") + " UTC"

    render_context_metrics(
        ("H3 cells",               total_cells),
        ("Elevation range",         elev_range),
        ("Avg slope",               avg_slope),
        ("Agent-classified cells",  f"{classified}/{total_cells}"),
        ("Low-confidence cells",    low_conf_cells),
        ("Last ingested",           last_ts),
    )

    # Void-fill notice
    if low_conf_cells:
        st.warning(
            f"⚠️ **{low_conf_cells} cell(s)** have DATA_CONFIDENCE < 0.70 "
            "(void-filled or adjacent to water bodies). "
            "These cells are excluded from precision construction slope decisions "
            "per the domain safety gate.",
            icon="⚠️",
        )

    # ── Colour selector + map ──────────────────────────────────────────────
    col_mode = st.radio(
        "Map colour",
        ["Elevation", "Slope", "Terrain class"],
        horizontal=True,
        key="terrain_colour_mode",
    )
    colour_by = {"Elevation": "elevation", "Slope": "slope",
                 "Terrain class": "terrain_class"}[col_mode]

    _render_map(wide, bbox, colour_by)

    # ── Tabs ───────────────────────────────────────────────────────────────
    t_signals, t_table = st.tabs(["📊 Distributions", "📋 Cell table"])

    with t_signals:
        _render_signals_tab(wide)

    with t_table:
        _render_table_tab(wide)

    # ── Refresh ────────────────────────────────────────────────────────────
    if st.button("🔄 Refresh terrain data", key="terrain_refresh"):
        st.session_state.pop(cache_key, None)
        st.rerun()
