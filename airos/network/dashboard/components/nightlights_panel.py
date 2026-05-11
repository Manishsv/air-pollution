"""Night Lights context panel — VIIRS NTL radiance, lit fraction, activity class per H3 cell.

Reads VIIRS-derived night-time light signals from the H3 knowledge store.
Structural-context panel only: no risk assessments, no decision packets.
ACTIVITY_CLASS is written by the ingestor (absolute thresholds, not agent-derived).

Colour maps
-----------
radiance         : black (0 nW) → yellow → white (60+ nW)
economic_activity: same gradient keyed on ECONOMIC_ACTIVITY_INDEX (0–1)
activity_class   : fixed RGBA per class
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

# Activity class → RGBA for pydeck H3HexagonLayer
_ACTIVITY_COLOR: dict[str, list[int]] = {
    "dark":        [ 20,  20,  40, 200],   # very dark blue-black
    "residential": [255, 200,  50, 180],   # warm yellow
    "commercial":  [255, 120,  20, 200],   # orange
    "industrial":  [200,  50, 200, 220],   # purple-magenta
    None:          [100, 100, 100, 120],   # grey (unclassified)
}

_ACTIVITY_LABEL: dict[str | None, str] = {
    "dark":        "⚫ Dark",
    "residential": "🟡 Residential",
    "commercial":  "🟠 Commercial",
    "industrial":  "🟣 Industrial",
    None:          "⚪ Unclassified",
}

# ACTIVITY_CLASS_LABELS from ingestor (decode ordinal → string)
_ACTIVITY_CLASS_LABELS: dict[int, str] = {
    0: "dark",
    1: "residential",
    2: "commercial",
    3: "industrial",
}


def _radiance_color(val: float) -> list[int]:
    """Black (0 nW) → yellow → white (60+ nW)."""
    t = max(0.0, min(1.0, val / 60.0))
    if t < 0.5:
        # Black → yellow
        s = t * 2
        r = int(s * 255)
        g = int(s * 220)
        b = 10
    else:
        # Yellow → white
        s = (t - 0.5) * 2
        r = 255
        g = int(220 + s * 35)
        b = int(10 + s * 245)
    return [r, g, b, 210]


# ── Data loading ───────────────────────────────────────────────────────────

def _load_nightlights_signals(city_id: str) -> pd.DataFrame:
    """Pull latest night lights signals for all H3 cells in the city."""
    from airos.os.sdk import store
    try:
        df = store.get_domain_signals_latest(city_id, "nightlights")
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        logger.debug("Night lights signal load failed (%s): %s", city_id, exc)
        return pd.DataFrame()


def _pivot(df: pd.DataFrame) -> pd.DataFrame:
    """Long → wide: one row per H3 cell, signals as columns.

    ACTIVITY_CLASS is stored as a numeric ordinal in the DB — decode it to
    the string label here so downstream code can use it directly in colour
    lookups and display.
    """
    if df.empty:
        return pd.DataFrame()
    wide = (
        df.pivot_table(index="h3_id", columns="signal", values="value", aggfunc="last")
        .reset_index()
    )
    if "ACTIVITY_CLASS" in wide.columns:
        from airos.drivers.store.nightlights_ingestor import ACTIVITY_CLASS_LABELS
        wide["ACTIVITY_CLASS"] = (
            wide["ACTIVITY_CLASS"]
            .dropna()
            .apply(lambda v: ACTIVITY_CLASS_LABELS.get(int(v)))
        ).reindex(wide.index)
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
        st.info("No night lights data to map.")
        return

    rows = []
    for _, row in wide.iterrows():
        h3_id = row["h3_id"]
        try:
            lat, lon = _h3.cell_to_latlng(h3_id)
        except Exception:
            continue

        radiance = row.get("NTL_RADIANCE")
        eai      = row.get("ECONOMIC_ACTIVITY_INDEX")
        ac       = row.get("ACTIVITY_CLASS")
        lit      = row.get("NTL_LIT_FRACTION")
        conf     = row.get("DATA_CONFIDENCE", 0.9)

        if colour_by == "radiance" and radiance is not None:
            color = _radiance_color(float(radiance))
        elif colour_by == "economic_activity" and eai is not None:
            # Same gradient but keyed on 0–1 index
            color = _radiance_color(float(eai) * 60.0)
        elif colour_by == "activity_class":
            color = _ACTIVITY_COLOR.get(ac, _ACTIVITY_COLOR[None])
        else:
            color = [60, 60, 80, 140]

        rows.append({
            "h3_id":      h3_id,
            "lat":        lat,
            "lon":        lon,
            "radiance":   round(float(radiance), 2) if radiance is not None else None,
            "eai":        round(float(eai),      3) if eai      is not None else None,
            "lit":        round(float(lit),       2) if lit      is not None else None,
            "activity":   ac or "unclassified",
            "conf":       round(float(conf),      2) if conf     is not None else None,
            "color":      color,
        })

    if not rows:
        st.info("No cells with valid night lights data.")
        return

    lat_c = (bbox["lat_min"] + bbox["lat_max"]) / 2
    lon_c = (bbox["lon_min"] + bbox["lon_max"]) / 2

    layer = pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(rows),
        get_hexagon="h3_id",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 10],
        line_width_min_pixels=1,
        pickable=True,
        extruded=False,
        opacity=0.85,
    )

    tooltip_html = (
        "<b>{h3_id}</b><br/>"
        "Radiance: {radiance} nW/cm²/sr<br/>"
        "Lit fraction: {lit}<br/>"
        "Economic activity index: {eai}<br/>"
        "Activity class: {activity}<br/>"
        "Confidence: {conf}"
    )

    chart = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(
            latitude=lat_c, longitude=lon_c, zoom=11, pitch=0,
        ),
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={"html": tooltip_html, "style": {"color": "white"}},
    )
    st.pydeck_chart(chart, use_container_width=True)

    # Colour legend
    if colour_by == "activity_class":
        present_classes = (
            wide["ACTIVITY_CLASS"].dropna().unique().tolist()
            if "ACTIVITY_CLASS" in wide.columns else []
        )
        legend = {k: v for k, v in _ACTIVITY_LABEL.items() if k in present_classes or k is None}
        cols = st.columns(min(len(legend), 5))
        for col, (ac_key, label) in zip(cols, legend.items()):
            with col:
                st.markdown(f"**{label}**")
    elif colour_by == "radiance":
        c1, c2, c3 = st.columns(3)
        c1.markdown("⚫ Dark  (0 nW)")
        c2.markdown("🟡 Mid  (~30 nW)")
        c3.markdown("⬜ Bright (60+ nW)")
    elif colour_by == "economic_activity":
        c1, c2, c3 = st.columns(3)
        c1.markdown("⚫ Low  (0)")
        c2.markdown("🟡 Mid  (~0.5)")
        c3.markdown("⬜ High (1.0)")


# ── Distributions tab ──────────────────────────────────────────────────────

def _render_signals_tab(wide: pd.DataFrame) -> None:
    if wide.empty:
        st.info("No night lights signals available.")
        return

    # Activity class distribution
    if "ACTIVITY_CLASS" in wide.columns:
        render_section_title("Activity class distribution")
        ac_counts = (
            wide["ACTIVITY_CLASS"]
            .fillna("unclassified")
            .value_counts()
            .rename_axis("Class")
            .reset_index(name="Cells")
        )
        st.bar_chart(ac_counts.set_index("Class"), use_container_width=True, height=220)
        classified = int(wide["ACTIVITY_CLASS"].notna().sum())
        total = len(wide)
        st.caption(f"Classified: {classified}/{total} cells.")

    # Radiance histogram
    if "NTL_RADIANCE" in wide.columns:
        render_section_title("Radiance distribution (nW/cm²/sr)")
        rad_data = wide["NTL_RADIANCE"].dropna()
        st.bar_chart(
            rad_data.value_counts(bins=20).sort_index().rename("cells"),
            use_container_width=True, height=200,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Min",    f"{rad_data.min():.1f} nW")
        c2.metric("Max",    f"{rad_data.max():.1f} nW")
        c3.metric("Mean",   f"{rad_data.mean():.1f} nW")
        c4.metric("Median", f"{rad_data.median():.1f} nW")

    # Confidence breakdown
    if "DATA_CONFIDENCE" in wide.columns:
        render_section_title("Data confidence")
        conf = wide["DATA_CONFIDENCE"].fillna(0)
        real_viirs  = int((conf >= 0.85).sum())
        cloud_fill  = int(((conf >= 0.60) & (conf < 0.85)).sum())
        synthetic   = int((conf < 0.60).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Real VIIRS (0.90)",        real_viirs,  help="Real NASA Black Marble data")
        c2.metric("Cloud/gap-filled (0.65)",  cloud_fill,  help="Reduced confidence")
        c3.metric("Synthetic (0.0)",          synthetic,   help="Not for operational use")
        if synthetic:
            st.info(
                "Cells with DATA_CONFIDENCE = 0.0 are synthetic and must not be used "
                "for any operational recommendation. "
                "Set EARTHDATA_TOKEN for real VIIRS data."
            )


# ── Per-cell table tab ─────────────────────────────────────────────────────

def _render_table_tab(wide: pd.DataFrame) -> None:
    if wide.empty:
        st.info("No night lights signals available.")
        return

    render_section_title("Per-cell signals")
    display_cols = ["h3_id"] + [
        c for c in [
            "NTL_RADIANCE", "NTL_LIT_FRACTION",
            "ECONOMIC_ACTIVITY_INDEX", "DATA_CONFIDENCE", "ACTIVITY_CLASS",
        ]
        if c in wide.columns
    ]
    display = wide[display_cols].copy()

    for col in display.columns:
        if col in ("h3_id", "ACTIVITY_CLASS"):
            continue
        display[col] = display[col].apply(
            lambda v: round(float(v), 3) if v is not None and str(v) != "nan" else None
        )

    st.dataframe(display, hide_index=True, use_container_width=True)
    st.caption(f"{len(display)} cells shown.")


# ── Main entry point ───────────────────────────────────────────────────────

def render_nightlights_panel() -> None:
    """Main entry point — called from app.py _DOMAIN_PANELS."""
    render_domain_header(
        title="Night Lights (VIIRS)",
        caption=(
            "NASA Black Marble VNP46A2 VIIRS DNB monthly composite — night-time radiance, "
            "lit fraction, and economic activity index per H3 cell. "
            "Structural context used by Air Quality, Heat, Construction, and Waste agents. "
            "No risk assessments generated directly."
        ),
        primary_alert=(
            "Night lights is static context — not a risk signal. "
            "It must not be used as the sole basis for any operational recommendation."
        ),
        primary_alert_kind="info",
    )

    # ── City selector ──────────────────────────────────────────────────────
    try:
        from airos.os.sdk import store as _sdk_store
        cities = _sdk_store.list_cities()
    except Exception:
        cities = ["bangalore", "hyderabad", "mumbai", "delhi", "chennai", "pune"]

    city_id = st.selectbox(
        "City", cities, index=0, key="nightlights_city_selector",
    )

    try:
        from airos.os.city_config import get_bbox as _get_bbox
        bbox = _get_bbox(city_id)
    except Exception:
        bbox = {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}

    # ── Load data ──────────────────────────────────────────────────────────
    cache_key = f"nightlights__{city_id}"
    if cache_key not in st.session_state:
        with st.spinner("Loading night lights signals …"):
            raw = _load_nightlights_signals(city_id)
        st.session_state[cache_key] = raw
    else:
        raw = st.session_state[cache_key]

    wide = _pivot(raw)

    # ── No data state ──────────────────────────────────────────────────────
    if wide.empty:
        st.info(
            f"No night lights signals found for **{city_id}**. "
            "The nightlights driver runs monthly — trigger a manual ingest:\n\n"
            f"`python main.py --step ingest-h3 --domains nightlights --cities {city_id}`"
        )
        if st.button("🔄 Refresh", key="nightlights_refresh_empty"):
            st.session_state.pop(cache_key, None)
            st.rerun()
        return

    # ── Summary metrics ────────────────────────────────────────────────────
    rad_col   = wide["NTL_RADIANCE"]           if "NTL_RADIANCE"           in wide.columns else pd.Series(dtype=float)
    lit_col   = wide["NTL_LIT_FRACTION"]       if "NTL_LIT_FRACTION"       in wide.columns else pd.Series(dtype=float)
    conf_col  = wide["DATA_CONFIDENCE"]        if "DATA_CONFIDENCE"        in wide.columns else pd.Series(dtype=float)
    class_col = wide["ACTIVITY_CLASS"]         if "ACTIVITY_CLASS"         in wide.columns else pd.Series(dtype=str)

    total_cells     = len(wide)
    mean_radiance   = f"{rad_col.mean():.1f} nW" if not rad_col.empty else "—"
    max_radiance    = f"{rad_col.max():.1f} nW"  if not rad_col.empty else "—"
    lit_cells       = int((lit_col > 0.5).sum()) if not lit_col.empty else 0
    industrial_cells = int((class_col == "industrial").sum()) if not class_col.empty else 0

    last_ts = "—"
    if "fetched_at" in raw.columns and not raw["fetched_at"].isna().all():
        last_ts = str(raw["fetched_at"].max())[:16].replace("T", " ") + " UTC"

    render_context_metrics(
        ("H3 cells",             total_cells),
        ("Mean radiance",        mean_radiance),
        ("Max radiance",         max_radiance),
        ("Lit cells (>50% lit)", lit_cells),
        ("Industrial cells",     industrial_cells),
        ("Last ingested",        last_ts),
    )

    # Synthetic data notice
    synthetic_cells = int((conf_col < 0.60).sum()) if not conf_col.empty else 0
    if synthetic_cells:
        st.warning(
            f"⚠️ **{synthetic_cells} cell(s)** have DATA_CONFIDENCE = 0.0 (synthetic). "
            "These cells are excluded from operational recommendations. "
            "Set EARTHDATA_TOKEN in .env for real VIIRS data.",
            icon="⚠️",
        )

    # ── Colour selector + map ──────────────────────────────────────────────
    col_mode = st.selectbox(
        "Map colour mode",
        ["Radiance", "Economic activity", "Activity class"],
        key="nightlights_colour_mode",
    )
    colour_by = {
        "Radiance":          "radiance",
        "Economic activity": "economic_activity",
        "Activity class":    "activity_class",
    }[col_mode]

    _render_map(wide, bbox, colour_by)

    # ── Tabs ───────────────────────────────────────────────────────────────
    t_signals, t_table = st.tabs(["📊 Distributions", "📋 Cell table"])

    with t_signals:
        _render_signals_tab(wide)

    with t_table:
        _render_table_tab(wide)

    # ── Refresh ────────────────────────────────────────────────────────────
    if st.button("🔄 Refresh night lights data", key="nightlights_refresh"):
        st.session_state.pop(cache_key, None)
        st.rerun()
