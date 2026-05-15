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


# _filter_by_city_bbox removed — the spatial JOINs in the loaders above
# (h3_metadata.centroid_lat/lon BETWEEN bbox) make this defensive guard
# redundant. Out-of-bbox cells are now excluded at the query level.


# ── Data loaders (cached) ────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_worst_risk_per_cell(aoi_id: str) -> pd.DataFrame:
    """Per-cell worst risk_level across all assessment domains, filtered
    spatially to the AOI's bbox (city_id-agnostic — Phase 1 AOI lens).

    Reads the latest row per (h3_id, domain) from h3_assessments joined
    to h3_metadata for the centroid, and keeps the row whose risk_level
    has the highest severity per cell. Works identically for city,
    airshed, watershed and other AOI kinds — the bbox does the work.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT a.h3_id, a.domain, a.risk_level, a.primary_index,
                   a.primary_value, a.dominant_issue
            FROM h3_assessments a
            INNER JOIN h3_metadata m ON m.h3_id = a.h3_id
            INNER JOIN (
                SELECT h3_id, domain, MAX(day_bucket) AS db
                FROM h3_assessments
                GROUP BY h3_id, domain
            ) latest ON latest.h3_id = a.h3_id
                    AND latest.domain = a.domain
                    AND latest.db = a.day_bucket
            WHERE a.risk_level IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
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
    return df.drop(columns=["risk_rank"]).reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def _load_open_insights_by_cell(aoi_id: str) -> pd.DataFrame:
    """One row per cell inside the AOI bbox with an open insight at tier
    ∈ {critical, high, medium}. Spatial filter (Phase 1 lens model).
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT i.insight_id, i.h3_id, i.priority_tier, i.finding,
                   i.confidence, i.created_at
            FROM h3_insights i
            INNER JOIN h3_metadata m ON m.h3_id = i.h3_id
            WHERE i.outcome_status = 'open'
              AND i.priority_tier IN ('critical', 'high', 'medium')
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            ORDER BY i.h3_id,
                CASE i.priority_tier
                    WHEN 'critical' THEN 0
                    WHEN 'high'     THEN 1
                    WHEN 'medium'   THEN 2
                END,
                i.created_at DESC
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
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
    return df.reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def _load_source_receptor_ranking(
    aoi_id: str, *, top_n: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Identify top emission sources and top receptors inside an AOI.

    Pulls the latest PM25 + UPWIND_PM25_LOAD_K10 (~7.5 km regional cone)
    per cell inside the AOI bbox, then computes:

      source_score   = max(PM25 - UPWIND_PM25_LOAD_K10, 0)
                       Cells that generate more pollution than they receive
                       — net contributors to the airshed.
      receptor_score = UPWIND_PM25_LOAD_K10
                       Cells receiving the most incoming pollution — net
                       importers, regardless of local emission level.

    Returns (sources_df, receptors_df), each with columns
    (h3_id, pm25, upwind_k10, source_score | receptor_score, area_name).
    Empty frames if the necessary signals haven't been ingested yet.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.area_name
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, s2.signal, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('PM25', 'UPWIND_PM25_LOAD_K10')
                  AND s2.value IS NOT NULL
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"],
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        empty = pd.DataFrame(columns=["h3_id", "pm25", "upwind_k10",
                                      "score", "area_name"])
        return empty, empty.copy()

    df = pd.DataFrame([dict(r) for r in rows])
    pivot = (df.pivot_table(index=["h3_id", "area_name"], columns="signal",
                            values="value", aggfunc="first")
               .reset_index()
               .rename_axis(None, axis=1))
    # Ensure both columns exist even if one signal is missing for all cells
    for col in ("PM25", "UPWIND_PM25_LOAD_K10"):
        if col not in pivot.columns:
            pivot[col] = None
    pivot = pivot.rename(columns={"PM25": "pm25",
                                  "UPWIND_PM25_LOAD_K10": "upwind_k10"})

    valid = pivot.dropna(subset=["pm25"]).copy()
    valid["upwind_k10"] = valid["upwind_k10"].fillna(0.0)

    valid["source_score"]   = (valid["pm25"] - valid["upwind_k10"]).clip(lower=0)
    valid["receptor_score"] = valid["upwind_k10"]

    sources = (valid.sort_values("source_score", ascending=False)
                    .head(top_n)
                    .loc[:, ["h3_id", "pm25", "upwind_k10",
                             "source_score", "area_name"]]
                    .rename(columns={"source_score": "score"})
                    .reset_index(drop=True))
    receptors = (valid.sort_values("receptor_score", ascending=False)
                      .head(top_n)
                      .loc[:, ["h3_id", "pm25", "upwind_k10",
                               "receptor_score", "area_name"]]
                      .rename(columns={"receptor_score": "score"})
                      .reset_index(drop=True))
    return sources, receptors


@st.cache_data(ttl=60, show_spinner=False)
def _load_event_points(aoi_id: str) -> pd.DataFrame:
    """Active point-event signals inside the AOI bbox — fire FRP > 0,
    waste SITE = 1, crowd GATHERING_ALERT = 1, flood risk_level in
    (high, severe). Spatial filter (Phase 1 lens model) replaces the
    earlier defensive city_id bbox guard.

    Returns (h3_id, domain, lat, lon, magnitude_label) for IconLayer.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        # Latest per (h3_id, signal) within the last 24h, spatially scoped.
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, s2.signal, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('FRP', 'SITE', 'GATHERING_ALERT')
                  AND s2.hour_bucket >= datetime('now', '-24 hours')
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value > 0
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"],
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
        flood_rows = conn.execute(
            """
            SELECT a.h3_id, m.centroid_lat, m.centroid_lon
            FROM h3_assessments a
            INNER JOIN h3_metadata m ON m.h3_id = a.h3_id
            INNER JOIN (
                SELECT h3_id, MAX(day_bucket) AS db
                FROM h3_assessments
                WHERE domain = 'flood'
                GROUP BY h3_id
            ) latest ON latest.h3_id = a.h3_id AND latest.db = a.day_bucket
            WHERE a.domain = 'flood'
              AND a.risk_level IN ('high', 'severe')
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    sig_to_domain = {"FRP": "fire", "SITE": "waste", "GATHERING_ALERT": "crowd"}
    for r in rows:
        d = dict(r)
        lat, lon = d.get("centroid_lat"), d.get("centroid_lon")
        if lat is None or lon is None:
            lat, lon = h3.cell_to_latlng(d["h3_id"])
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
        out.append({
            "h3_id":    d["h3_id"],
            "domain":   "flood",
            "lat":      float(lat),
            "lon":      float(lon),
            "magnitude": "high flood risk",
        })
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

def _render_cell_detail(h3_id: str, aoi_id: str) -> None:
    """Right-side panel content for a clicked cell. The dossier needs a
    `city_id` (it joins to h3_metadata + h3_signals which still carry
    that column); we resolve the cell's primary city by spatial lookup
    when the parent AOI isn't itself a city kind.

    Shows the cell dossier (signals by domain, cause hypotheses, POI
    summary) + any open insight."""
    from airos.os.cell_dossier import build_cell_dossier
    from airos.os.aoi_registry import get_aoi, aois_for_cell

    aoi_cfg = get_aoi(aoi_id)
    if aoi_cfg["kind"] == "city":
        # When viewing a city AOI, that's the dossier's reference city.
        city_id = aoi_id
    else:
        # For airshed / watershed / corridor AOIs the cell belongs to
        # some underlying city; pick the first city-kind AOI that
        # contains it. Falls back to the parent AOI if none found.
        city_containers = aois_for_cell(h3_id, kind="city")
        city_id = city_containers[0] if city_containers else aoi_id

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

    # Latest open insight on this cell (if any). Spatial cell lookup by
    # h3_id alone — no city_id filter, so an airshed-AOI click still
    # surfaces insights tagged with any constituent city's id.
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT insight_id, finding, priority_tier, confidence, created_at
            FROM h3_insights
            WHERE h3_id = ? AND outcome_status = 'open'
            ORDER BY created_at DESC LIMIT 1
            """,
            (h3_id,),
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

_AOI_KIND_ICON: dict[str, str] = {
    "city":      "🏙️",
    "airshed":   "🌫️",
    "watershed": "💧",
    "corridor":  "🛣️",
    "port":      "⚓",
    "airport":   "✈️",
}


def _render_source_receptor(aoi_id: str) -> None:
    """Top-N source + receptor cells for non-city AOIs.

    A "source" cell is a net emitter (local PM > regional upwind PM —
    contributes more than it receives). A "receptor" cell is dominated
    by incoming regional load (high UPWIND_PM25_LOAD_K10). The split
    tells the airshed dispatcher who to enforce on (sources) versus
    who needs cross-jurisdiction coordination (receptors).
    """
    sources, receptors = _load_source_receptor_ranking(aoi_id, top_n=8)
    if sources.empty and receptors.empty:
        st.caption(
            "_No PM25 / UPWIND_PM25_LOAD_K10 yet — run an air ingest "
            "sweep first._"
        )
        return

    def _fmt_row(r: pd.Series, score_label: str) -> str:
        area = r.get("area_name") or "—"
        pm = r["pm25"] or 0
        up = r["upwind_k10"] or 0
        return (
            f"<small><b>{area}</b> · {score_label} {r['score']:.1f}  "
            f"<span style='color:#888;'>(PM25 {pm:.0f}, "
            f"upwind-7km {up:.0f})</span></small>"
        )

    if not sources.empty:
        st.markdown("**🏭 Top emission sources**")
        st.caption(
            "_Cells where local PM exceeds regional incoming — net "
            "contributors to the airshed. Local enforcement targets._"
        )
        for _, r in sources.iterrows():
            st.markdown(_fmt_row(r, "net+"), unsafe_allow_html=True)
        st.markdown("")

    if not receptors.empty:
        st.markdown("**📥 Top receptors**")
        st.caption(
            "_Cells receiving the most incoming pollution from upwind "
            "(~7 km cone). Need cross-jurisdiction coordination._"
        )
        for _, r in receptors.iterrows():
            st.markdown(_fmt_row(r, "in"), unsafe_allow_html=True)


def render_citymap_panel() -> None:
    """Full-screen AOI situational-awareness map. Registered as the
    default landing view in app.py. Selecting any AOI — city, airshed,
    watershed, corridor — renders the same overlays at the AOI's
    auto-derived resolution."""
    from airos.os.aoi_registry import (
        list_aois, get_aoi, bbox_of, resolution_of,
    )

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

    # ── Floating overlay row: AOI dropdown + layer toggles popover ───────
    col_aoi, col_layers, _spacer = st.columns([2.4, 1.6, 6.0])

    with col_aoi:
        aoi_ids = list_aois()
        if not aoi_ids:
            st.error("No AOIs configured — add one to data/config/aoi.yaml.")
            return
        # Build display label "<icon> <display_name>" per AOI; selector
        # value is the AOI id.
        def _aoi_label(aoi_id: str) -> str:
            cfg = get_aoi(aoi_id)
            return f"{_AOI_KIND_ICON.get(cfg['kind'], '📍')} {cfg['display_name']}"
        label_to_id = {_aoi_label(a): a for a in aoi_ids}
        labels = list(label_to_id.keys())
        # Restore previous selection if still valid
        prev = st.session_state.get("citymap_aoi_label")
        idx = labels.index(prev) if prev in label_to_id else 0
        label = st.selectbox(
            "AOI", labels, index=idx,
            key="citymap_aoi_selector", label_visibility="collapsed",
        )
        st.session_state["citymap_aoi_label"] = label
        aoi_id = label_to_id[label]
        aoi_cfg = get_aoi(aoi_id)

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

    # ── Load data (spatial — Phase 1 AOI lens) ────────────────────────────
    risk_df    = _load_worst_risk_per_cell(aoi_id)
    insight_df = _load_open_insights_by_cell(aoi_id)
    event_df   = _load_event_points(aoi_id)

    layers = _build_layers(
        risk_df, insight_df, event_df,
        show_risk_shade=show_risk,
        show_insight_border=show_border,
        show_event_icons=show_icons,
    )

    # ── Initial viewport: AOI bbox centroid + zoom derived from area ─────
    bbox = bbox_of(aoi_id)
    centre_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2.0
    centre_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2.0
    # Map the AOI's H3 resolution to a sensible default zoom (smaller
    # AOIs → finer res → higher zoom).
    zoom_by_resolution = {9: 13, 8: 11, 7: 9, 6: 7, 5: 5}
    zoom = zoom_by_resolution.get(resolution_of(aoi_id), 11)
    view_state = pdk.ViewState(
        latitude=centre_lat,
        longitude=centre_lon,
        zoom=zoom,
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
            _render_cell_detail(clicked_h3, aoi_id)
        else:
            n_cells   = len(risk_df)
            n_insight = len(insight_df)
            n_events  = len(event_df)
            kind_icon = _AOI_KIND_ICON.get(aoi_cfg["kind"], "📍")
            st.markdown(f"#### {kind_icon} {aoi_cfg['display_name']}")
            st.caption(
                f"{aoi_cfg['kind']} · H3 res {resolution_of(aoi_id)} · "
                f"{n_cells:,} assessed cells"
            )

            # Source/receptor ranking — only meaningful for AOIs that span
            # multiple districts (airshed / watershed / corridor). Cities
            # are usually a single emission/receiver zone so the split is
            # noisier than it is useful.
            if aoi_cfg["kind"] in ("airshed", "watershed", "corridor"):
                _render_source_receptor(aoi_id)
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
