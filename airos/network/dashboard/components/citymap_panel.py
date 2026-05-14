"""City situational-awareness map — full-screen pydeck H3 view.

The landing view for AirOS dashboard. Per user spec:
  - Streamlit + pydeck (deck.gl H3HexagonLayer for GPU rendering)
  - Each H3 cell is shaded by the WORST risk_level across assessment
    domains for that cell ("auto-collapse to worst-risk-per-cell")
  - Point-event icons overlay for fire FRP, waste hotspots,
    crowd GATHERING_ALERT, flood high-risk
  - Cells with an open insight (tier ∈ high/medium/critical) get a
    coloured border (border colour = tier)
  - Click a cell → side panel with cell signals + insight if present
  - Hover → tooltip
  - Top-left: city dropdown overlay
  - Top-right (popover): layer toggles + legend

Stays inside Streamlit so it shares auth, session, city_config, etc.
Methodology §11 (Design Principles): translucent overlays so the
operator can always see the basemap underneath.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import h3
import pandas as pd
import pydeck as pdk
import streamlit as st

logger = logging.getLogger(__name__)


# ── Visual config (translucent overlays, methodology §11) ────────────────────

# Risk-tier RGB shading (alpha kept low so basemap shows through).
# Order matches the canonical 4-tier vocabulary (good/low/moderate/high/severe).
_RISK_FILL_RGBA: dict[str, tuple[int, int, int, int]] = {
    "good":     (88, 180, 90,  60),    # green
    "low":      (140, 200, 90, 60),    # yellow-green
    "moderate": (240, 200, 60, 90),    # yellow
    "high":     (240, 130, 50, 110),   # orange
    "severe":   (220, 50,  50, 130),   # red
    "unknown":  (160, 160, 160, 40),
}

# Insight-tier border colour (no fill — these draw on top of the shade layer).
_INSIGHT_BORDER_RGBA: dict[str, tuple[int, int, int, int]] = {
    "critical": (220, 0,   0,   220),
    "high":     (240, 120, 0,   220),
    "medium":   (240, 200, 0,   200),
    # low is intentionally excluded — only operationally meaningful insights
    # earn a border (per user spec choice (ii))
}

# Numeric severity rank — used to pick "worst risk" when multiple domains
# assess the same cell.
_RISK_RANK: dict[str, int] = {
    "good": 0, "low": 1, "unknown": 1, "moderate": 2, "high": 3, "severe": 4,
}

# Icon mapping for point-event domains. Uses public Maki icons via CDN —
# no auth, simple PNGs. Width/height enforced in IconLayer.
_ICON_ATLAS = {
    "fire":  {"url": "https://img.icons8.com/color/48/000000/fire-element.png",
              "label": "Fire / FRP"},
    "waste": {"url": "https://img.icons8.com/color/48/000000/biohazard.png",
              "label": "Waste hotspot"},
    "crowd": {"url": "https://img.icons8.com/color/48/000000/conference-call.png",
              "label": "Crowd / gathering"},
    "flood": {"url": "https://img.icons8.com/color/48/000000/wave.png",
              "label": "Flood risk"},
}


def _db_path() -> str:
    from airos.drivers.store.schema import DB_PATH
    return str(DB_PATH)


def _filter_by_city_bbox(df: pd.DataFrame, city_id: str, *, label: str) -> pd.DataFrame:
    """Drop rows whose H3 cell centroid falls outside the city's bbox.

    Defensive guard: some ingestors (notably FIRMS fire) over-attribute
    rows to a city by tagging city_id="kanpur" on hotspots that are
    geographically 30-80 km outside the Kanpur urban bbox. The proper
    fix is upstream in the ingestor, but until that lands the citymap
    must not render stray hexes / icons in neighbouring districts.

    Expects a 'h3_id' column. Logs how many rows were dropped.
    """
    if df.empty or "h3_id" not in df.columns:
        return df
    try:
        from airos.os.city_config import get_bbox
        bbox = get_bbox(city_id)
    except (ImportError, KeyError):
        return df
    lat_min, lat_max = bbox["lat_min"], bbox["lat_max"]
    lon_min, lon_max = bbox["lon_min"], bbox["lon_max"]

    def _inside(cell: str) -> bool:
        lat, lon = h3.cell_to_latlng(cell)
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max

    mask = df["h3_id"].apply(_inside)
    dropped = int((~mask).sum())
    if dropped:
        logger.info(
            "[citymap/%s] %s: dropped %d cell(s) outside bbox "
            "(upstream city_id mis-attribution).",
            city_id, label, dropped,
        )
    return df[mask].copy()


# ── Data loaders (cached) ────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_worst_risk_per_cell(city_id: str) -> pd.DataFrame:
    """Per-cell worst risk_level across all assessment domains.

    Reads the latest row per (h3_id, domain) from h3_assessments, then
    keeps the row whose risk_level has the highest severity per cell.
    Result: one row per cell with (h3_id, risk_level, primary_index,
    primary_value, dominant_issue, dominant_domain).
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT a.h3_id, a.domain, a.risk_level, a.primary_index,
                   a.primary_value, a.dominant_issue
            FROM h3_assessments a
            INNER JOIN (
                SELECT h3_id, domain, MAX(day_bucket) AS db
                FROM h3_assessments
                WHERE city_id = ?
                GROUP BY h3_id, domain
            ) latest ON latest.h3_id = a.h3_id
                    AND latest.domain = a.domain
                    AND latest.db = a.day_bucket
            WHERE a.city_id = ? AND a.risk_level IS NOT NULL
            """,
            (city_id, city_id),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(
            columns=["h3_id", "risk_level", "dominant_domain",
                     "primary_index", "primary_value", "dominant_issue"]
        )
    df = pd.DataFrame([dict(r) for r in rows])
    df["risk_rank"] = df["risk_level"].map(_RISK_RANK).fillna(0)
    # Keep the highest-severity domain per cell.
    df = df.sort_values("risk_rank", ascending=False).drop_duplicates("h3_id")
    df = df.rename(columns={"domain": "dominant_domain"})
    df = _filter_by_city_bbox(df, city_id, label="risk_shade")
    return df.drop(columns=["risk_rank"]).reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def _load_open_insights_by_cell(city_id: str) -> pd.DataFrame:
    """One row per cell that has at least one open insight with tier in
    {critical, high, medium}. Returns the highest-tier insight per cell
    so we can colour the border by tier.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT insight_id, h3_id, priority_tier, finding, confidence,
                   created_at
            FROM h3_insights
            WHERE city_id = ? AND outcome_status = 'open'
              AND priority_tier IN ('critical', 'high', 'medium')
            ORDER BY h3_id,
                CASE priority_tier
                    WHEN 'critical' THEN 0
                    WHEN 'high'     THEN 1
                    WHEN 'medium'   THEN 2
                END,
                created_at DESC
            """,
            (city_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(
            columns=["insight_id", "h3_id", "priority_tier", "finding",
                     "confidence", "created_at"]
        )
    df = pd.DataFrame([dict(r) for r in rows])
    df = df.drop_duplicates("h3_id")
    df = _filter_by_city_bbox(df, city_id, label="insight_border")
    return df.reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def _load_event_points(city_id: str) -> pd.DataFrame:
    """Active point-event signals — fire FRP > 0, waste SITE = 1,
    crowd GATHERING_ALERT = 1, flood risk_level in (high, severe).

    Filters to cells whose centroid falls inside the city's bbox. Some
    upstream ingestors (notably FIRMS fire) tag a wide regional area
    with city_id="kanpur" even for hotspots 50+ km outside — we don't
    want those rendered on the city map. See follow-up task for the
    proper upstream fix.

    Returns (h3_id, domain, lat, lon, magnitude_label) for IconLayer.
    """
    from airos.os.city_config import get_bbox
    try:
        bbox = get_bbox(city_id)
        lat_min, lat_max = bbox["lat_min"], bbox["lat_max"]
        lon_min, lon_max = bbox["lon_min"], bbox["lon_max"]
    except KeyError:
        lat_min = lat_max = lon_min = lon_max = None

    def _in_bbox(lat: float, lon: float) -> bool:
        if lat_min is None:
            return True
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        # Latest per (h3_id, signal) within the last 24h to keep the icon set fresh
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN (
                SELECT h3_id, signal, MAX(hour_bucket) AS hb
                FROM h3_signals
                WHERE city_id = ?
                  AND signal IN ('FRP', 'SITE', 'GATHERING_ALERT')
                  AND hour_bucket >= datetime('now', '-24 hours')
                GROUP BY h3_id, signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            LEFT JOIN h3_metadata m ON m.h3_id = s.h3_id AND m.city_id = s.city_id
            WHERE s.city_id = ? AND s.value > 0
            """,
            (city_id, city_id),
        ).fetchall()
        # Flood: pulled from assessments (high/severe risk_level), not from a
        # single boolean signal.
        flood_rows = conn.execute(
            """
            SELECT a.h3_id, m.centroid_lat, m.centroid_lon
            FROM h3_assessments a
            INNER JOIN (
                SELECT h3_id, MAX(day_bucket) AS db
                FROM h3_assessments
                WHERE city_id = ? AND domain = 'flood'
                GROUP BY h3_id
            ) latest ON latest.h3_id = a.h3_id AND latest.db = a.day_bucket
            LEFT JOIN h3_metadata m ON m.h3_id = a.h3_id AND m.city_id = a.city_id
            WHERE a.city_id = ? AND a.domain = 'flood'
              AND a.risk_level IN ('high', 'severe')
            """,
            (city_id, city_id),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    dropped = 0
    sig_to_domain = {"FRP": "fire", "SITE": "waste", "GATHERING_ALERT": "crowd"}
    for r in rows:
        d = dict(r)
        lat, lon = d.get("centroid_lat"), d.get("centroid_lon")
        if lat is None or lon is None:
            lat, lon = h3.cell_to_latlng(d["h3_id"])
        if not _in_bbox(float(lat), float(lon)):
            dropped += 1
            continue
        out.append({
            "h3_id":    d["h3_id"],
            "domain":   sig_to_domain.get(d["signal"], d["signal"].lower()),
            "lat":      float(lat),
            "lon":      float(lon),
            "magnitude": f"{d['signal']}={d['value']:.2g}",
        })
    for r in flood_rows:
        d = dict(r)
        lat, lon = d.get("centroid_lat"), d.get("centroid_lon")
        if lat is None or lon is None:
            lat, lon = h3.cell_to_latlng(d["h3_id"])
        if not _in_bbox(float(lat), float(lon)):
            dropped += 1
            continue
        out.append({
            "h3_id":    d["h3_id"],
            "domain":   "flood",
            "lat":      float(lat),
            "lon":      float(lon),
            "magnitude": "high flood risk",
        })
    if dropped:
        logger.info(
            "[citymap/%s] event-points: filtered %d row(s) outside bbox "
            "(upstream city_id mis-attribution; see follow-up task).",
            city_id, dropped,
        )
    return pd.DataFrame(out)


# ── Layer assembly ───────────────────────────────────────────────────────────

def _hex_to_rgba_array(s: pd.Series, table: dict) -> list[list[int]]:
    """Map a Series of risk/tier strings to a list of [r, g, b, a] arrays
    (pydeck expects per-row list-of-ints, not tuples)."""
    default = list(table.get("unknown", (160, 160, 160, 40)))
    return [list(table.get(v, default)) for v in s.fillna("unknown")]


def _build_layers(
    risk_df: pd.DataFrame,
    insight_df: pd.DataFrame,
    event_df: pd.DataFrame,
    *,
    show_risk_shade: bool,
    show_insight_border: bool,
    show_event_icons: bool,
) -> list[pdk.Layer]:
    layers: list[pdk.Layer] = []

    # 1. Risk shade — full H3 hex fill per cell, colour by worst risk_level
    if show_risk_shade and not risk_df.empty:
        risk_df = risk_df.copy()
        risk_df["fill_rgba"] = _hex_to_rgba_array(risk_df["risk_level"], _RISK_FILL_RGBA)
        layers.append(pdk.Layer(
            "H3HexagonLayer",
            data=risk_df,
            get_hexagon="h3_id",
            get_fill_color="fill_rgba",
            stroked=False,
            extruded=False,
            pickable=True,
            auto_highlight=True,
            id="risk_shade",
        ))

    # 2. Insight border — same hex shape, no fill, thick stroke coloured by tier
    if show_insight_border and not insight_df.empty:
        insight_df = insight_df.copy()
        insight_df["line_rgba"] = _hex_to_rgba_array(
            insight_df["priority_tier"], _INSIGHT_BORDER_RGBA,
        )
        layers.append(pdk.Layer(
            "H3HexagonLayer",
            data=insight_df,
            get_hexagon="h3_id",
            get_fill_color=[0, 0, 0, 0],
            get_line_color="line_rgba",
            stroked=True,
            filled=False,
            line_width_min_pixels=2,
            extruded=False,
            pickable=True,
            auto_highlight=False,
            id="insight_border",
        ))

    # 3. Event icons — Fire / Waste / Crowd / Flood
    if show_event_icons and not event_df.empty:
        event_df = event_df.copy()
        event_df["icon_data"] = event_df["domain"].map(
            lambda d: {
                "url": _ICON_ATLAS.get(d, _ICON_ATLAS["fire"])["url"],
                "width": 96, "height": 96, "anchorY": 96,
            }
        )
        layers.append(pdk.Layer(
            "IconLayer",
            data=event_df,
            get_icon="icon_data",
            get_position=["lon", "lat"],
            get_size=4,
            size_scale=8,
            pickable=True,
            id="event_icons",
        ))

    return layers


# ── Cell detail side-panel ───────────────────────────────────────────────────

def _render_cell_detail(h3_id: str, city_id: str) -> None:
    """Right-side panel content for a clicked cell. Shows the cell dossier
    (signals by domain, cause hypotheses, POI summary) + any open insight."""
    from airos.os.cell_dossier import build_cell_dossier

    try:
        dossier = build_cell_dossier(city_id, h3_id)
    except Exception as exc:
        st.error(f"Failed to load cell dossier: {exc}")
        return

    meta = dossier.get("metadata") or {}
    st.markdown(f"#### {meta.get('area_name') or 'Cell'} · `{h3_id[:10]}…`")
    if meta.get("centroid_lat") and meta.get("centroid_lon"):
        st.caption(
            f"{float(meta['centroid_lat']):.4f}°N, "
            f"{float(meta['centroid_lon']):.4f}°E"
            + (f" · {meta.get('land_use_class')}" if meta.get('land_use_class') else "")
        )

    # Cause hypotheses (top 3)
    hyps = dossier.get("hypotheses") or []
    if hyps:
        st.markdown("**Cause hypotheses**")
        for h in hyps[:3]:
            st.caption(f"`{h['cause']}` — confidence {h.get('confidence', 0):.2f}")

    # Latest open insight on this cell (if any)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT insight_id, finding, priority_tier, confidence, created_at
            FROM h3_insights
            WHERE h3_id = ? AND city_id = ? AND outcome_status = 'open'
            ORDER BY created_at DESC LIMIT 1
            """,
            (h3_id, city_id),
        ).fetchone()
    finally:
        conn.close()

    if row:
        st.markdown("**Open insight**")
        tier = row["priority_tier"] or "low"
        st.markdown(f"`{tier.upper()}` · confidence {row['confidence']:.2f}")
        st.write(row["finding"])
        st.caption(f"created {row['created_at']}")
    else:
        st.info("No open insight on this cell — signals only.")

    # POI summary (compact)
    pois = dossier.get("poi_summary") or {}
    if pois:
        st.markdown("**POIs**")
        st.caption(" · ".join(f"{k}: {v}" for k, v in pois.items() if v))


# ── Main entry ───────────────────────────────────────────────────────────────

def render_citymap_panel() -> None:
    """Full-screen city situational-awareness map. Registered as the
    default landing view in app.py."""
    from airos.os.city_config import CITIES, get_centre, get_zoom

    # Inject a small bit of CSS so the map feels full-bleed and the
    # selectbox overlay floats over the deck.
    st.markdown(
        """
        <style>
        /* Tighten the top padding so the map takes more screen */
        section.main > div.block-container { padding-top: 1rem; }
        /* Floating overlay row */
        .citymap-overlay-row { margin-bottom: 0.25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Floating overlay row: city dropdown + layer toggles popover ──────
    col_city, col_layers, _spacer = st.columns([2.0, 1.6, 6.0])

    with col_city:
        city_labels  = {v["display_name"]: k for k, v in CITIES.items()}
        if not city_labels:
            st.error("No cities configured — add one to data/config/cities.yaml.")
            return
        default_label = next(iter(city_labels.keys()))
        label = st.selectbox(
            "City", list(city_labels.keys()),
            index=list(city_labels.keys()).index(
                st.session_state.get("citymap_city_label", default_label)
            ) if st.session_state.get("citymap_city_label") in city_labels else 0,
            key="citymap_city_selector", label_visibility="collapsed",
        )
        st.session_state["citymap_city_label"] = label
        city_id = city_labels[label]

    with col_layers:
        with st.popover("🧭 Layers", use_container_width=True):
            show_risk    = st.checkbox("Risk shade (worst per cell)", value=True,
                                       key="citymap_show_risk")
            show_border  = st.checkbox("Insight border (high/medium)", value=True,
                                       key="citymap_show_border")
            show_icons   = st.checkbox("Event icons (fire/waste/crowd/flood)",
                                       value=True, key="citymap_show_icons")
            st.divider()
            st.caption("**Risk shade legend**")
            for tier in ("severe", "high", "moderate", "low", "good"):
                r, g, b, a = _RISK_FILL_RGBA[tier]
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;"
                    f"background:rgba({r},{g},{b},{a/255:.2f});"
                    f"border:1px solid #888;margin-right:6px;'></span>"
                    f"<small>{tier}</small>",
                    unsafe_allow_html=True,
                )
            st.caption("**Insight border**")
            for tier in ("critical", "high", "medium"):
                r, g, b, a = _INSIGHT_BORDER_RGBA[tier]
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;"
                    f"border:3px solid rgba({r},{g},{b},{a/255:.2f});"
                    f"margin-right:6px;'></span><small>{tier}</small>",
                    unsafe_allow_html=True,
                )

    # ── Load data ────────────────────────────────────────────────────────
    risk_df    = _load_worst_risk_per_cell(city_id)
    insight_df = _load_open_insights_by_cell(city_id)
    event_df   = _load_event_points(city_id)

    layers = _build_layers(
        risk_df, insight_df, event_df,
        show_risk_shade=show_risk,
        show_insight_border=show_border,
        show_event_icons=show_icons,
    )

    # ── Initial viewport: city centre + sensible zoom ────────────────────
    centre = get_centre(city_id)
    view_state = pdk.ViewState(
        latitude=centre[0],
        longitude=centre[1],
        zoom=get_zoom(city_id),
        pitch=0,
        bearing=0,
    )

    tooltip = {
        "html": (
            "<b>{dominant_domain}</b> &middot; risk: <b>{risk_level}</b>"
            "<br/>{dominant_issue}"
            "<br/><small>{h3_id}</small>"
        ),
        "style": {
            "backgroundColor": "rgba(20,20,28,0.92)",
            "color": "white",
            "padding": "6px 8px",
            "borderRadius": "6px",
            "fontSize": "12px",
        },
    }

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="light",
        tooltip=tooltip,
    )

    # ── Map + side panel layout ──────────────────────────────────────────
    map_col, side_col = st.columns([3.0, 1.0])
    with map_col:
        event = st.pydeck_chart(
            deck, use_container_width=True, height=760,
            on_select="rerun", selection_mode="single-object",
            key="citymap_deck",
        )

    # Resolve clicked cell from pydeck selection event
    clicked_h3: str | None = None
    if event is not None and hasattr(event, "selection"):
        sel = event.selection or {}
        objs = sel.get("objects") or {}
        # `objects` is a dict of layer_id → list[picked rows]
        for layer_id in ("risk_shade", "insight_border"):
            picks = objs.get(layer_id) or []
            if picks:
                row = picks[0]
                clicked_h3 = row.get("h3_id")
                break
        if not clicked_h3:
            picks = objs.get("event_icons") or []
            if picks:
                clicked_h3 = picks[0].get("h3_id")

    with side_col:
        if clicked_h3:
            _render_cell_detail(clicked_h3, city_id)
        else:
            n_cells   = len(risk_df)
            n_insight = len(insight_df)
            n_events  = len(event_df)
            st.markdown(f"#### {city_id.title()}")
            st.caption(f"{n_cells:,} assessed cells")
            if n_insight:
                tier_counts = insight_df["priority_tier"].value_counts().to_dict()
                bits = []
                for t in ("critical", "high", "medium"):
                    if tier_counts.get(t):
                        bits.append(f"{tier_counts[t]} {t}")
                st.caption("Open insights: " + ", ".join(bits) if bits else "Open insights: 0")
            else:
                st.caption("Open insights: 0")
            if n_events:
                ev_counts = event_df["domain"].value_counts().to_dict()
                st.caption("Active events: " + ", ".join(
                    f"{n} {d}" for d, n in ev_counts.items()
                ))
            st.divider()
            st.info("Click any cell on the map for details.")
