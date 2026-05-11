"""Map panel — H3 hexagon overlay of domain risk levels with on-demand cell analysis.

Uses pydeck H3HexagonLayer to render H3 cells coloured by compound risk.
Clicking a hex selects it and shows:
  - Geographic location (lat/lon, land-use class)
  - Per-domain risk badges from the latest assessments
  - Latest signal readings (AQI, wind, temperature, etc.)
  - Latest AI insight, if one exists
  - "Analyse this cell" button → queues an async H3 Expert Agent run
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from airos.network.dashboard.pydeck_utils import clean_h3_data

# ---------------------------------------------------------------------------
# Risk colour palette  (RGBA lists for pydeck)
# ---------------------------------------------------------------------------

_RISK_RGBA = {
    "severe":   [180,  35,  24, 200],
    "high":     [196,  82,  10, 200],
    "moderate": [202, 138,   4, 180],
    "low":      [ 22, 163,  74, 160],
    "unknown":  [156, 163, 175, 120],
}
_RISK_EMOJI = {
    "severe": "🔴", "high": "🟠", "moderate": "🟡",
    "low": "🟢", "unknown": "⚪",
}
_RISK_ORDER = {"severe": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}

_RISK_COLOR_CSS = {
    "severe":   "#ef4444",
    "high":     "#f97316",
    "moderate": "#ca8a04",
    "low":      "#16a34a",
    "unknown":  "#6b7280",
}

# City default view-states
_CITY_VIEWS = {
    "bangalore": {"latitude": 12.9716, "longitude": 77.5946, "zoom": 11},
    "hyderabad": {"latitude": 17.3850, "longitude": 78.4867, "zoom": 11},
    "mumbai":    {"latitude": 19.0760, "longitude": 72.8777, "zoom": 11},
    "delhi":     {"latitude": 28.6139, "longitude": 77.2090, "zoom": 11},
    "chennai":   {"latitude": 13.0827, "longitude": 80.2707, "zoom": 11},
    "pune":      {"latitude": 18.5204, "longitude": 73.8567, "zoom": 11},
}
_DEFAULT_VIEW = {"latitude": 20.5937, "longitude": 78.9629, "zoom": 5}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_assessment_cells(city_id: str, days_back: int) -> pd.DataFrame:
    """Load H3 cells for a single city with worst recent risk + top metric + latest insight."""
    try:
        from airos.drivers.store.store import H3KnowledgeStore
        df = H3KnowledgeStore.get().fetchdf(f"""
            WITH cell_risk AS (
                -- Worst risk level seen per cell in the window
                SELECT
                    h3_id, city_id,
                    max(CASE risk_level
                        WHEN 'severe'   THEN 4
                        WHEN 'high'     THEN 3
                        WHEN 'moderate' THEN 2
                        WHEN 'low'      THEN 1
                        ELSE 0 END)  AS risk_score,
                    GROUP_CONCAT(DISTINCT domain) AS domains,
                    count(DISTINCT domain)         AS domain_count
                FROM h3_assessments
                WHERE city_id  = ?
                  AND day_bucket >= date('now', '-{days_back} days')
                GROUP BY h3_id, city_id
            ),
            top_assess AS (
                -- Primary metric from the highest-risk domain per cell
                SELECT h3_id, city_id,
                       domain          AS top_domain,
                       primary_index   AS top_index,
                       primary_value   AS top_value,
                       dominant_issue
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY h3_id, city_id
                               ORDER BY CASE risk_level
                                   WHEN 'severe'   THEN 4
                                   WHEN 'high'     THEN 3
                                   WHEN 'moderate' THEN 2
                                   WHEN 'low'      THEN 1
                                   ELSE 0 END DESC
                           ) AS rn
                    FROM h3_assessments
                    WHERE city_id  = ?
                      AND day_bucket >= date('now', '-{days_back} days')
                ) WHERE rn = 1
            ),
            latest_insight AS (
                SELECT h3_id, city_id, finding, confidence, insight_id, created_at
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY h3_id, city_id
                               ORDER BY created_at DESC
                           ) AS rn
                    FROM h3_insights
                    WHERE city_id = ?
                ) WHERE rn = 1
            )
            SELECT
                cr.h3_id,
                cr.city_id,
                cr.risk_score,
                cr.domains,
                cr.domain_count,
                ta.top_domain,
                ta.top_index,
                ta.top_value,
                ta.dominant_issue,
                m.centroid_lat  AS lat,
                m.centroid_lon  AS lon,
                m.area_name,
                m.land_use_class,
                li.finding,
                li.confidence,
                li.insight_id,
                li.created_at   AS insight_at
            FROM cell_risk cr
            LEFT JOIN top_assess ta
                ON cr.h3_id = ta.h3_id AND cr.city_id = ta.city_id
            LEFT JOIN h3_metadata m
                ON cr.h3_id = m.h3_id  AND cr.city_id = m.city_id
            LEFT JOIN latest_insight li
                ON cr.h3_id = li.h3_id AND cr.city_id = li.city_id
        """, [city_id, city_id, city_id])
        return df
    except Exception as exc:
        st.error(f"Map data load failed: {exc}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Colour + tooltip helpers
# ---------------------------------------------------------------------------

_SCORE_LABEL = {4: "severe", 3: "high", 2: "moderate", 1: "low", 0: "unknown"}


def _make_tooltip_html(r) -> str:
    """Build HTML tooltip shown on cell hover.  Values must not contain single-quotes."""
    rl      = str(r.get("risk_level", "unknown"))
    color   = _RISK_COLOR_CSS.get(rl, "#6b7280")
    emoji   = _RISK_EMOJI.get(rl, "⚪")

    # Area name (suburb / neighbourhood from Nominatim)
    _an = r.get("area_name")
    area_name = "" if (not _an or not pd.notna(_an)) else str(_an).strip()

    # Coordinates + area name line
    if pd.notna(r.get("lat")) and pd.notna(r.get("lon")):
        coord_str = f"{float(r['lat']):.4f}°N, {float(r['lon']):.4f}°E"
        if area_name:
            loc_line = (
                f"<div style='color:#e2e8f0;font-size:12px;font-weight:600;margin-top:3px'>"
                f"📍 {area_name}</div>"
                f"<div style='color:#94a3b8;font-size:10px;margin-top:1px'>"
                f"{coord_str}</div>"
            )
        else:
            loc_line = (
                f"<div style='color:#94a3b8;font-size:11px;margin-top:3px'>"
                f"📍 {coord_str}</div>"
            )
    else:
        loc_line = ""

    # Key metric — primary_index: value from the worst-risk domain
    metric_line = ""
    top_idx = r.get("top_index")
    top_val = r.get("top_value")
    if top_idx and top_val is not None and pd.notna(top_val):
        try:
            metric_line = (
                f"<div style='font-size:15px;font-weight:700;margin-top:2px'>"
                f"{top_idx}: {float(top_val):.1f}"
                f"</div>"
            )
        except Exception:
            pass

    # Domains covered
    domains = str(r.get("domains") or "—").replace(",", " · ")

    # Insight status
    if r.get("insight_id"):
        ins_line = (
            "<div style='color:#86efac;font-size:11px;margin-top:4px'>"
            "✓ Insight available — click for details"
            "</div>"
        )
    else:
        ins_line = (
            "<div style='color:#fbbf24;font-size:11px;margin-top:4px'>"
            "Click to view · Analyse this cell"
            "</div>"
        )

    return (
        f"<div style='min-width:190px;line-height:1.4'>"
        f"<div style='color:{color};font-size:14px;font-weight:700'>{emoji} {rl.upper()}</div>"
        f"{metric_line}"
        f"{loc_line}"
        f"<div style='color:#cbd5e1;font-size:11px;margin-top:3px'>{domains}</div>"
        f"{ins_line}"
        f"</div>"
    )


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["risk_level"]   = df["risk_score"].map(_SCORE_LABEL).fillna("unknown")
    df["fill_color"]   = df["risk_level"].map(_RISK_RGBA).apply(
        lambda c: c if isinstance(c, list) else _RISK_RGBA["unknown"]
    )
    df["line_color"]   = [[255, 255, 255, 60]] * len(df)
    df["tooltip_html"] = df.apply(_make_tooltip_html, axis=1)

    # NaN sanitisation is handled by clean_h3_data() at layer-build time.
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_ago(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return str(dt)[:16]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    if s < 60:     return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} min ago"
    if s < 86400:
        h = s // 3600
        return f"{h} hr ago"
    d = s // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


# ---------------------------------------------------------------------------
# Cell detail panel
# ---------------------------------------------------------------------------

def _render_selected_cell(h3_id: str, city_id: str) -> None:
    """Render rich cell detail: location, per-domain risk, signals, insight, analyse button."""
    from airos.drivers.store.store import H3KnowledgeStore
    from airos.drivers.store.writer import submit_analysis_request
    from airos.drivers.store.reader import get_request_status

    s = H3KnowledgeStore.get()

    # ── 1. Metadata / location ─────────────────────────────────────────────
    try:
        meta_df = s.fetchdf(
            "SELECT centroid_lat, centroid_lon, area_name, land_use_class "
            "FROM h3_metadata WHERE h3_id = ? AND city_id = ?",
            [h3_id, city_id],
        )
        lat = lon = land_use = area_name_cell = None
        if not meta_df.empty:
            lat           = meta_df.iloc[0].get("centroid_lat")
            lon           = meta_df.iloc[0].get("centroid_lon")
            land_use      = meta_df.iloc[0].get("land_use_class")
            _an = meta_df.iloc[0].get("area_name")
            area_name_cell = (None if (not _an or not pd.notna(_an))
                              else str(_an).strip() or None)

        parts = []
        if area_name_cell:
            parts.append(f"📍 {area_name_cell}")
        elif land_use:
            parts.append(f"🏙️ {land_use}")
        if lat is not None and lon is not None:
            coord_str = f"{float(lat):.4f}°N, {float(lon):.4f}°E"
            if area_name_cell:
                parts.append(f"({coord_str})")
            else:
                parts.append(f"📍 {coord_str}")
        loc_line = "  ·  ".join(parts) if parts else "📍 Location unknown"
        st.markdown(
            f"<div style='color:#94a3b8;font-size:0.8em;margin-bottom:10px;'>{loc_line}</div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass

    # ── 2. Per-domain risk badges ──────────────────────────────────────────
    try:
        assess_df = s.fetchdf(
            """
            SELECT domain, risk_level, primary_index, primary_value, assessed_at
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY domain ORDER BY assessed_at DESC) AS rn
                FROM h3_assessments
                WHERE h3_id = ? AND city_id = ?
            ) WHERE rn = 1
            ORDER BY domain
            """,
            [h3_id, city_id],
        )
        if not assess_df.empty:
            badge_html = ""
            for _, row in assess_df.iterrows():
                domain = str(row["domain"])
                risk   = str(row.get("risk_level", "unknown"))
                color  = _RISK_COLOR_CSS.get(risk, "#6b7280")
                emoji  = _RISK_EMOJI.get(risk, "⚪")
                val_str = ""
                if row.get("primary_index") and row.get("primary_value") is not None:
                    try:
                        val_str = f" {row['primary_index']}={float(row['primary_value']):.1f}"
                    except Exception:
                        pass
                badge_html += (
                    f'<span style="background:{color}22;color:{color};'
                    f'border:1px solid {color}55;padding:3px 10px;border-radius:12px;'
                    f'font-size:0.78em;margin:2px;display:inline-block;">'
                    f'{emoji} {domain.upper()}{val_str}</span>'
                )
            st.markdown(
                f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;">'
                f'{badge_html}</div>',
                unsafe_allow_html=True,
            )
    except Exception as exc:
        st.caption(f"Could not load domain risk: {exc}")

    # ── 3. Latest signals (collapsed) ─────────────────────────────────────
    try:
        signals_df = s.fetchdf(
            """
            SELECT domain, signal, value, unit, observed_at
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY domain, signal ORDER BY observed_at DESC) AS rn
                FROM h3_signals
                WHERE h3_id = ? AND city_id = ?
                  AND signal NOT IN ('DATA_CONFIDENCE', 'NEAREST_OBS_KM')
                  AND observed_at >= datetime('now', '-3 days')
            ) WHERE rn = 1
            ORDER BY domain, signal
            """,
            [h3_id, city_id],
        )
        if not signals_df.empty:
            with st.expander("📊 Latest signals", expanded=False):
                for domain, grp in signals_df.groupby("domain"):
                    lines = []
                    for _, row in grp.iterrows():
                        try:
                            val = f"{float(row['value']):.3g}"
                        except Exception:
                            val = str(row["value"])
                        unit   = row.get("unit") or ""
                        obs_at = str(row.get("observed_at", ""))[:16].replace("T", " ")
                        lines.append(f"  `{row['signal']}` = **{val} {unit}** _{obs_at}_")
                    st.markdown(f"**{domain}**")
                    st.markdown("\n\n".join(lines))
    except Exception:
        pass

    # ── 4. Latest insight ─────────────────────────────────────────────────
    st.markdown("---")
    try:
        insight_df = s.fetchdf(
            """
            SELECT insight_id, finding, confidence, domains_involved, created_at
            FROM h3_insights
            WHERE h3_id = ? AND city_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [h3_id, city_id],
        )
        if not insight_df.empty:
            ins       = insight_df.iloc[0]
            conf      = ins.get("confidence")
            conf_str  = f"  ·  {float(conf):.0%} confidence" if conf else ""
            ago       = _time_ago(ins.get("created_at"))
            doms      = ins.get("domains_involved") or ""
            dom_str   = f"  ·  {doms}" if doms else ""
            st.markdown(
                f"**🧠 Latest insight** "
                f"<span style='color:#64748b;font-size:0.8em'>{ago}{conf_str}{dom_str}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"> {ins['finding']}")
        else:
            st.info("No AI insight yet for this cell.")
    except Exception as exc:
        st.caption(f"Could not load insight: {exc}")

    # ── 5. Analysis request queue button ──────────────────────────────────
    try:
        req    = get_request_status(h3_id, city_id)
        status = req.get("status", "")

        if status == "pending":
            req_ago = _time_ago(req.get("requested_at"))
            st.warning(f"⏳ Analysis queued {req_ago} — will run on next scheduler sweep (≤ 15 min).")
        elif status == "running":
            st.warning("⚙️ Analysis in progress…")
        elif status == "failed":
            err = req.get("error_msg") or "unknown error"
            st.error(f"❌ Last analysis failed: {err}")
            if st.button("🔬 Retry analysis", key=f"analyse_{h3_id}"):
                ok, msg = submit_analysis_request(h3_id, city_id)
                (st.success if ok else st.warning)(msg)
                st.rerun()
        else:
            # No active request or cooldown elapsed
            help_txt = (
                "Queue an AI analysis of all signals for this cell. "
                "The scheduler picks it up within 15 minutes. "
                "A 6-hour cooldown applies after each completed analysis."
            )
            if st.button("🔬 Analyse this cell", key=f"analyse_{h3_id}", help=help_txt):
                ok, msg = submit_analysis_request(h3_id, city_id)
                (st.success if ok else st.warning)(msg)
                st.rerun()
    except Exception as exc:
        st.caption(f"Analysis queue unavailable: {exc}")


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

def _render_legend() -> None:
    items = [
        ("severe",   "Severe compound risk"),
        ("high",     "High risk"),
        ("moderate", "Moderate risk"),
        ("low",      "Low / monitored"),
        ("unknown",  "No recent assessment"),
    ]
    chips = " &nbsp; ".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;">'
        f'<span style="width:12px;height:12px;border-radius:2px;'
        f'background:rgb({",".join(str(x) for x in _RISK_RGBA[r][:3])});'
        f'display:inline-block;"></span>'
        f'<span style="font-size:12px;color:rgba(0,0,0,0.6);">{label}</span></span>'
        for r, label in items
    )
    st.markdown(chips, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_map_panel() -> None:
    try:
        import pydeck as pdk
    except ImportError:
        st.error("pydeck is not installed. Run: pip install pydeck")
        return

    from airos.os.city_config import CITIES as _CITY_REGISTRY

    # ── Pre-widget: resolve any pending selection changes ─────────────────
    # Streamlit rule: session_state[widget_key] can only be written BEFORE
    # that widget is instantiated.  Clear / pydeck-click both store a
    # *side-channel* key that is resolved here, at the top of the run,
    # before any widget with key="map_sel_h3" is rendered.
    _pending = st.session_state.pop("_map_sel_next", None)
    if _pending is not None:
        st.session_state["map_sel_h3"] = _pending

    # ── City + filter controls ────────────────────────────────────────────
    mc1, mc2, mc3, mc4 = st.columns([3, 2, 2, 2])
    with mc1:
        # City is always required — no "All cities" option to avoid mixing cells
        city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
        city_label   = st.selectbox(
            "City", list(city_options.keys()), key="map_city",
            label_visibility="collapsed",
        )
        city_id = city_options[city_label]
    with mc2:
        days_back = st.selectbox(
            "Window", [3, 7, 14, 30], index=1,
            format_func=lambda d: f"Last {d}d", key="map_days",
            label_visibility="collapsed",
        )
    with mc3:
        min_risk = st.selectbox(
            "Min risk", ["all", "low", "moderate", "high", "severe"],
            index=0,
            format_func=lambda r: "All risk levels" if r == "all" else r.capitalize(),
            key="map_min_risk",
            label_visibility="collapsed",
        )
    with mc4:
        insights_only = st.toggle(
            "Insights only",
            value=True,
            key="map_insights_only",
            help=(
                "ON — show only cells where the AI agent has produced an insight "
                "(matches the Inbox view).\n\n"
                "OFF — show all assessed cells across the city."
            ),
        )

    # ── Load + filter ─────────────────────────────────────────────────────
    df = _load_assessment_cells(city_id, days_back)
    if df.empty:
        st.info(
            f"No assessment data for **{city_label}** in the last {days_back} days. "
            "Run:\n```\npython main.py --step ingest-h3\n```"
        )
        return

    df = _enrich(df)

    # Safety: drop any rows with null/empty h3_id — pydeck H3HexagonLayer
    # will crash the browser canvas if it receives invalid cell IDs.
    df = df[df["h3_id"].notna() & (df["h3_id"].astype(str).str.strip() != "")]

    # Insights-only filter — mirrors the inbox panel view
    if insights_only:
        df = df[df["insight_id"].notna()]
        if df.empty:
            st.info(
                f"No AI insights for **{city_label}** in the last {days_back} days.  \n"
                "Toggle **Insights only** off to see all assessed cells, "
                "or run the agent to generate insights."
            )
            return

    min_score = _RISK_ORDER.get(min_risk, 0)
    if min_risk != "all":
        df = df[df["risk_score"] >= min_score]

    if df.empty:
        st.info(f"No cells with risk ≥ {min_risk} in the last {days_back} days.")
        return

    # ── Summary bar ───────────────────────────────────────────────────────
    _render_legend()
    sev  = int((df["risk_level"] == "severe").sum())
    high = int((df["risk_level"] == "high").sum())
    mod  = int((df["risk_level"] == "moderate").sum())
    ins  = int(df["insight_id"].notna().sum())
    mode_label = "insights" if insights_only else "assessed cells"
    st.caption(
        f"**{city_label}** · {len(df)} {mode_label} · "
        f"{'🔴 ' + str(sev) + ' severe · ' if sev else ''}"
        f"{'🟠 ' + str(high) + ' high · ' if high else ''}"
        f"{'🟡 ' + str(mod) + ' moderate · ' if mod else ''}"
        f"{ins} with insight"
    )

    # ── View-state: always city-specific ──────────────────────────────────
    vs_cfg = _CITY_VIEWS.get(city_id, _DEFAULT_VIEW)
    view_state = pdk.ViewState(
        latitude=vs_cfg["latitude"],
        longitude=vs_cfg["longitude"],
        zoom=vs_cfg["zoom"],
        pitch=0,
    )

    # ── H3 layer ─────────────────────────────────────────────────────────
    hex_layer = pdk.Layer(
        "H3HexagonLayer",
        data=clean_h3_data(df),
        get_hexagon="h3_id",
        get_fill_color="fill_color",
        get_line_color="line_color",
        line_width_min_pixels=1,
        auto_highlight=True,
        highlight_color=[255, 255, 255, 80],
        pickable=True,
        extruded=False,
        coverage=0.88,
    )

    # HTML tooltip — uses the pre-built tooltip_html column
    tooltip = {
        "html": "{tooltip_html}",
        "style": {
            "backgroundColor": "rgba(10,15,30,0.92)",
            "color":           "white",
            "padding":         "10px 14px",
            "borderRadius":    "8px",
            "boxShadow":       "0 4px 16px rgba(0,0,0,0.5)",
            "maxWidth":        "280px",
            "fontFamily":      "system-ui,sans-serif",
        },
    }

    chart = pdk.Deck(
        layers=[hex_layer],
        initial_view_state=view_state,
        tooltip=tooltip,
        map_style="light",
    )

    # Render map — capture click selection
    selected = st.pydeck_chart(
        chart, on_select="rerun", selection_mode="single-object",
        use_container_width=True, height=500,
    )

    # ── Cell selector dropdown ────────────────────────────────────────────
    # Build labels using coordinates + risk + key metric (no raw H3 IDs)
    st.markdown("")
    col_pick, col_clear = st.columns([5, 1])
    with col_pick:
        cell_options = df["h3_id"].tolist()
        cell_labels: dict[str, str] = {}
        for _, r in df.iterrows():
            rl   = r["risk_level"]
            icon = _RISK_EMOJI.get(rl, "⚪")
            # Location priority: area_name > land_use_class > lat/lon
            _an = r.get("area_name")
            loc = "" if (not _an or not pd.notna(_an)) else str(_an).strip()
            if not loc:
                loc = str(r.get("land_use_class") or "").strip()
            if not loc and pd.notna(r.get("lat")) and pd.notna(r.get("lon")):
                loc = f"{float(r['lat']):.3f}°N {float(r['lon']):.3f}°E"
            # Key metric
            metric = ""
            if r.get("top_index") and r.get("top_value") is not None:
                try:
                    metric = f"  {r['top_index']}={float(r['top_value']):.1f}"
                except Exception:
                    pass
            domains  = str(r.get("domains") or "").replace(",", "·")
            ins_flag = "✓" if r.get("insight_id") else "○"
            cell_labels[r["h3_id"]] = (
                f"{icon} {rl.upper()}{metric}"
                + (f"  — {loc}" if loc else "")
                + f"  [{domains}] {ins_flag}"
            )

        sel_h3 = st.selectbox(
            "Select cell to inspect",
            options=[""] + cell_options,
            format_func=lambda x: "↑ Click a cell on the map, or choose here…"
                                   if x == "" else cell_labels.get(x, x),
            key="map_sel_h3",
            label_visibility="collapsed",
        )
    with col_clear:
        st.markdown("<div style='margin-top:8px;'>", unsafe_allow_html=True)
        if st.button("✕", key="map_clear_sel", help="Clear selection"):
            # Write to side-channel; resolved at top of next run BEFORE the widget
            st.session_state["_map_sel_next"] = ""
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # Sync pydeck click → selectbox (also via side-channel)
    if selected and hasattr(selected, "selection") and selected.selection:
        sel_objects = getattr(selected.selection, "objects", {})
        if sel_objects:
            for layer_rows in sel_objects.values():
                if layer_rows:
                    clicked_h3 = layer_rows[0].get("h3_id")
                    if clicked_h3 and clicked_h3 != sel_h3:
                        st.session_state["_map_sel_next"] = clicked_h3
                        st.rerun()

    # ── Cell detail panel ─────────────────────────────────────────────────
    if sel_h3:
        st.divider()
        row_match = df[df["h3_id"] == sel_h3]

        if not row_match.empty:
            r     = row_match.iloc[0]
            rl    = r["risk_level"]
            icon  = _RISK_EMOJI.get(rl, "⚪")
            color = _RISK_COLOR_CSS.get(rl, "#6b7280")
            # Location header — area_name > land_use_class > coordinates
            _an = r.get("area_name")
            area_name = "" if (not _an or not pd.notna(_an)) else str(_an).strip()
            land_use  = str(r.get("land_use_class") or "").strip()
            coord = ""
            if pd.notna(r.get("lat")) and pd.notna(r.get("lon")):
                coord = f"{float(r['lat']):.4f}°N, {float(r['lon']):.4f}°E"
            # Primary label for the header
            primary_loc = area_name or land_use or coord
            # Secondary: show coord if we have a name
            secondary   = f"  ({coord})" if coord and primary_loc and primary_loc != coord else ""
            metric_hdr = ""
            if r.get("top_index") and r.get("top_value") is not None:
                try:
                    metric_hdr = f"  ·  {r['top_index']} {float(r['top_value']):.1f}"
                except Exception:
                    pass
            st.markdown(
                f"<span style='color:{color};font-size:1.05em;font-weight:700'>"
                f"{icon} {rl.upper()}</span>"
                f"<span style='color:#64748b;font-size:0.85em'>{metric_hdr}</span>"
                f"<br><span style='color:#94a3b8;font-size:0.8em'>"
                f"{'📍 ' + primary_loc if primary_loc else ''}"
                f"{secondary}"
                f"&nbsp;&nbsp;{city_label}</span>",
                unsafe_allow_html=True,
            )

        _render_selected_cell(sel_h3, city_id)
