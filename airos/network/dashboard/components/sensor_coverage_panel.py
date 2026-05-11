"""Sensor Coverage & Data Quality panel.

Three tabs:
  1. Coverage Map      — H3 hexagon layer coloured by DATA_CONFIDENCE
  2. Ward Data Quality — ward × domain quality table
  3. Sensor Recommendations — ranked candidate locations with export

All three tabs import defensively from airos.drivers.store.data_quality
so the panel stays functional while that module is being built in parallel.
"""
from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from airos.network.dashboard.ui_shell import render_context_metrics, render_section_title
from airos.os.city_config import CITIES as _CITY_REGISTRY, get_centre, PANEL_CITIES

# ---------------------------------------------------------------------------
# Defensive import of data_quality module + cached wrappers
# ---------------------------------------------------------------------------
# All DB-hitting functions are wrapped with @st.cache_data so they run once
# per (city_id, TTL window) rather than on every Streamlit rerender.
# populate_siting_candidates is intentionally NOT called from the dashboard —
# it is a write operation that belongs exclusively in the scheduler.
# ---------------------------------------------------------------------------

try:
    from airos.drivers.store.data_quality import (
        get_cell_confidence      as _get_cell_confidence,
        get_city_quality_summary as _get_city_quality_summary,
    )
    _DQ_AVAILABLE = True
except Exception:
    _DQ_AVAILABLE = False


@st.cache_data(ttl=300, show_spinner=False)
def _cell_confidence(city_id: str, domain: str | None = None) -> pd.DataFrame:
    if not _DQ_AVAILABLE:
        return pd.DataFrame()
    try:
        return _get_cell_confidence(city_id, domain)
    except Exception:
        return pd.DataFrame()



@st.cache_data(ttl=300, show_spinner=False)
def _city_quality_summary(city_id: str) -> dict:
    if not _DQ_AVAILABLE:
        return {}
    try:
        return _get_city_quality_summary(city_id) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DOMAINS = ["All", "Air Quality", "Flood", "Heat", "Noise"]

_DOMAIN_KEY = {
    "Air Quality": "air",
    "Flood":       "flood",
    "Heat":        "heat",
    "Noise":       "noise",
}

_MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _confidence_color(conf: float | None) -> list[int]:
    if conf is None or (isinstance(conf, float) and pd.isna(conf)):
        return [160, 160, 160, 100]
    if conf >= 0.8:
        return [40, 167, 69, 200]    # green
    if conf >= 0.6:
        return [255, 193, 7, 200]    # yellow
    if conf >= 0.4:
        return [253, 126, 20, 200]   # orange
    return [220, 53, 69, 200]        # red


def _confidence_label(conf: float | None) -> str:
    if conf is None or (isinstance(conf, float) and pd.isna(conf)):
        return "No data"
    if conf >= 0.8:
        return "Analysis-ready"
    if conf >= 0.6:
        return "Marginal"
    if conf >= 0.4:
        return "Poor"
    return "Insufficient"


# ---------------------------------------------------------------------------
# City selector (shared)
# ---------------------------------------------------------------------------

def _city_selector() -> str:
    c1, c2 = st.columns([3, 1])
    with c1:
        label = st.selectbox("City", list(PANEL_CITIES.keys()), key="sc_city_selector")
    with c2:
        if st.button("↻ Refresh", key="sc_refresh",
                     help="Re-read coverage data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    return PANEL_CITIES[label]


# ---------------------------------------------------------------------------
# Tab 1 — Coverage Map
# ---------------------------------------------------------------------------

def _render_coverage_map(city_id: str) -> None:
    render_section_title("H3 cell coverage by DATA_CONFIDENCE")
    st.caption(
        "Each hexagon is an H3 resolution-8 cell. Colour shows how well the cell's "
        "estimated values are grounded in real sensor observations. "
        "Green = reliable; red = interpolated and potentially misleading."
    )

    domain_choice = st.selectbox(
        "Domain filter", _DOMAINS, key="sc_map_domain",
    )

    if not _DQ_AVAILABLE:
        st.info(
            "Module `airos.drivers.store.data_quality` is not yet available. "
            "Coverage map will appear once that module is built and importable."
        )
        return

    domain_key = _DOMAIN_KEY.get(domain_choice)

    with st.spinner("Loading cell confidence data…"):
        df = _cell_confidence(city_id)

    if df is None or df.empty:
        st.info(
            "No DATA_CONFIDENCE signals found for this city. "
            "Run the ingestor to populate the knowledge store."
        )
        return

    # Apply domain filter
    if domain_key and "domain" in df.columns:
        df = df[df["domain"] == domain_key]

    if df.empty:
        st.info(f"No cells found for domain: {domain_choice}")
        return

    # Build colour column
    df = df.copy()
    df["fill_color"] = df["avg_confidence"].apply(_confidence_color)

    # Pydeck H3 hexagon layer
    lat_c, lon_c = get_centre(city_id) if city_id in _CITY_REGISTRY else (20.0, 78.0)

    layer = pdk.Layer(
        "H3HexagonLayer",
        df,
        get_hexagon="h3_id",
        get_fill_color="fill_color",
        get_line_color=[80, 80, 80, 80],
        line_width_min_pixels=0,
        pickable=True,
        auto_highlight=True,
        extruded=False,
        opacity=0.8,
    )
    view = pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=11, pitch=0)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            tooltip={
                "html": (
                    "<b>Cell:</b> {h3_id}<br/>"
                    "<b>Confidence:</b> {avg_confidence}<br/>"
                    "<b>Domain:</b> {domain}"
                ),
                "style": {
                    "backgroundColor": "#1e293b",
                    "color": "white",
                    "fontSize": "12px",
                },
            },
            map_style=_MAP_STYLE,
        ),
        use_container_width=True,
    )

    # Legend
    st.markdown(
        '<div style="display:flex;gap:20px;font-size:12px;margin-top:6px;flex-wrap:wrap;">'
        '<span><span style="color:#28a745;font-size:16px">■</span> '
        'Analysis-ready (≥ 0.8)</span>'
        '<span><span style="color:#ffc107;font-size:16px">■</span> '
        'Marginal (0.6–0.8)</span>'
        '<span><span style="color:#fd7e14;font-size:16px">■</span> '
        'Poor (0.4–0.6)</span>'
        '<span><span style="color:#dc3545;font-size:16px">■</span> '
        'Insufficient (&lt; 0.4)</span>'
        '<span><span style="color:#aaa;font-size:16px">■</span> '
        'No data</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Quick summary metrics below the map
    st.markdown("")
    total = len(df)
    ready = (df["avg_confidence"] >= 0.8).sum() if "avg_confidence" in df.columns else 0
    marginal = ((df["avg_confidence"] >= 0.6) & (df["avg_confidence"] < 0.8)).sum()
    poor = ((df["avg_confidence"] >= 0.4) & (df["avg_confidence"] < 0.6)).sum()
    insufficient = (df["avg_confidence"] < 0.4).sum()
    render_context_metrics(
        ("Total cells", str(total)),
        ("Analysis-ready", f"{ready} ({100*ready//total if total else 0}%)"),
        ("Marginal", f"{marginal}"),
        ("Poor", f"{poor}"),
        ("Insufficient", f"{insufficient}"),
    )


# ---------------------------------------------------------------------------
# Tab 2 — Ward Data Quality
# ---------------------------------------------------------------------------

def _pct_color_html(pct: float) -> str:
    """Return a coloured HTML span for a percentage value."""
    if pct >= 60:
        color = "#28a745"
    elif pct >= 30:
        color = "#ffc107"
    else:
        color = "#dc3545"
    return f'<span style="color:{color};font-weight:600">{pct:.0f}%</span>'


def _render_domain_coverage(city_id: str) -> None:
    """Show H3 cell analysis-readiness by domain.

    Ward boundaries are not yet loaded — we can only report at the city level
    how many H3 cells per domain have DATA_CONFIDENCE ≥ 0.6.  Ward-level
    breakdown will be possible once ward geometry is ingested.
    """
    render_section_title("H3 cell analysis readiness by domain")
    st.caption(
        "Shows how many H3 cells have DATA_CONFIDENCE ≥ 0.6 (analysis-ready) for each domain. "
        "Ward-level breakdown is not yet available — ward boundary data has not been loaded."
    )

    if not _DQ_AVAILABLE:
        st.info("Data quality module not yet available.")
        return

    with st.spinner("Loading cell confidence data…"):
        df = _cell_confidence(city_id)   # reuse the same cached data as the map tab

    if df is None or df.empty:
        st.info("No DATA_CONFIDENCE signals found. Run the ingestor to populate the knowledge store.")
        return

    if "domain" not in df.columns or "avg_confidence" not in df.columns:
        st.info("Unexpected data format — cannot compute readiness summary.")
        return

    # Aggregate by domain
    THRESHOLD = 0.6
    rows = []
    for domain, grp in df.groupby("domain"):
        total  = len(grp)
        ready  = (grp["avg_confidence"] >= THRESHOLD).sum()
        pct    = 100.0 * ready / total if total > 0 else 0.0
        avg_conf = grp["avg_confidence"].mean()
        rows.append({
            "Domain":         domain.title(),
            "Total Cells":    total,
            "Analysis-Ready": ready,
            "Not Ready":      total - ready,
            "% Ready":        round(pct, 1),
            "Avg Confidence": round(avg_conf, 3),
        })

    summary = pd.DataFrame(rows).sort_values("% Ready", ascending=True)

    # City-wide headline
    total_all = summary["Total Cells"].sum()
    ready_all = summary["Analysis-Ready"].sum()
    pct_all   = 100.0 * ready_all / total_all if total_all > 0 else 0.0
    render_context_metrics(
        ("Total H3 cells", f"{total_all:,}"),
        ("Analysis-ready", f"{ready_all:,}"),
        ("City-wide %",    f"{pct_all:.0f}%"),
        ("Domains",        str(len(summary))),
    )

    # Per-domain table with colour-coded % column
    th = "padding:8px 12px;text-align:left;background:rgba(0,0,0,0.05);font-size:12px;font-weight:600;"
    td = "padding:7px 12px;font-size:13px;"
    header = "".join(f'<th style="{th}">{c}</th>' for c in summary.columns)
    rows_html = ""
    for _, row in summary.iterrows():
        pct = float(row["% Ready"])
        color = "#28a745" if pct >= 60 else ("#ffc107" if pct >= 30 else "#dc3545")
        cells = ""
        for col in summary.columns:
            val = row[col]
            if col == "% Ready":
                cells += f'<td style="{td}"><span style="color:{color};font-weight:700">{val}%</span></td>'
            elif col == "Avg Confidence":
                cells += f'<td style="{td};color:rgba(0,0,0,0.5)">{val}</td>'
            else:
                cells += f'<td style="{td}">{val:,}</td>' if isinstance(val, (int, float)) else f'<td style="{td}">{val}</td>'
        rows_html += f"<tr>{cells}</tr>"

    st.markdown(
        f'<div style="overflow-x:auto;border:0.5px solid rgba(0,0,0,0.15);border-radius:6px;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>{header}</tr></thead><tbody>{rows_html}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Analysis-ready = DATA_CONFIDENCE ≥ 0.6. "
        "Cells below threshold are too far from any sensor — IDW interpolation is not predictive there. "
        "Ward-level breakdown will be available once ward boundaries are loaded."
    )

    poor = summary[summary["% Ready"] < 30]
    if not poor.empty:
        domains_str = ", ".join(poor["Domain"].tolist())
        st.warning(f"Domains below 30% ready: **{domains_str}** — AI analysis will not trigger for these cells.")



# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------

def render_sensor_coverage_panel() -> None:
    st.markdown("## Sensor Coverage & Data Quality")
    st.caption(
        "Understand where your sensor network has gaps, which wards lack reliable data, "
        "and where to deploy new sensors for maximum analytical coverage."
    )

    city_id = _city_selector()

    st.markdown("---")

    tab_map, tab_coverage = st.tabs([
        "Coverage Map",
        "Domain Readiness",
    ])

    with tab_map:
        _render_coverage_map(city_id)

    with tab_coverage:
        _render_domain_coverage(city_id)
