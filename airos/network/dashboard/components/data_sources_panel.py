"""Data Sources panel — live status of all ingest pipelines per city.

Shows:
  • Source registry: domain → provider, API key requirement, fallback mode
  • API key status: which keys are configured vs missing
  • Status matrix: domain × city — last pull time, rows written, ok/partial/error
  • Staleness highlights: cells older than 6 h amber, older than 24 h red
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from airos.os.city_config import CITIES as _CITY_REGISTRY


# ---------------------------------------------------------------------------
# Source registry — static metadata per domain
# ---------------------------------------------------------------------------

_SOURCES = {
    # acquisition_mode:
    #   "sensor_list"  — source provides fixed sensor locations; we ingest from those
    #                    points and IDW-interpolate outward. DATA_CONFIDENCE degrades
    #                    with distance. Sensor siting recommendations apply.
    #   "query_driven" — we choose the query points (H3 cell centroids). DATA_CONFIDENCE
    #                    = 1.0 everywhere. Sensor siting does NOT apply; coverage can be
    #                    improved by changing the sampling resolution in the connector.
    "air": {
        "provider":         "CPCB AQI API",
        "url":              "https://api.cpcbccr.com/",
        "api_key_env":      "CPCB_API_KEY",
        "fallback":         "synthetic (no live data)",
        "acquisition_mode": "sensor_list",
        "notes":            "Real-time AQI readings from fixed CPCB monitoring stations. "
                            "IDW interpolation from station lat/lngs to H3 cells.",
    },
    "fire": {
        "provider":         "NASA FIRMS",
        "url":              "https://firms.modaps.eosdis.nasa.gov/",
        "api_key_env":      "FIRMS_API_KEY",
        "fallback":         "none — skipped if no key",
        "acquisition_mode": "query_driven",
        "notes":            "VIIRS/MODIS thermal anomaly detections. Satellite pixels "
                            "directly assigned to H3 cells at native resolution.",
    },
    "heat": {
        "provider":         "Open-Meteo",
        "url":              "https://api.open-meteo.com/",
        "api_key_env":      None,
        "fallback":         "computed from Open-Meteo (free, no key needed)",
        "acquisition_mode": "query_driven",
        "notes":            "Queried at each H3 cell centroid. Land surface temperature "
                            "+ forecast data. Free API, no key required.",
    },
    "flood": {
        "provider":         "OpenMeteo (rainfall) + OSM (drains)",
        "url":              "https://api.open-meteo.com/",
        "api_key_env":      None,
        "fallback":         "synthetic rainfall model",
        "acquisition_mode": "query_driven",
        "notes":            "Rainfall queried per H3 centroid (OpenMeteo, no key). "
                            "Drain capacity from OSM polygon geometry — quarterly ingest.",
    },
    "water": {
        "provider":         "Google Earth Engine",
        "url":              "https://earthengine.google.com/",
        "api_key_env":      "GEE_PROJECT",
        "fallback":         "none — skipped if no key",
        "acquisition_mode": "query_driven",
        "notes":            "JRC surface water + NDWI from Sentinel-2. Satellite pixels "
                            "sampled at H3 cell centroids.",
    },
    "waste": {
        "provider":         "NASA FIRMS (proxy)",
        "url":              "https://firms.modaps.eosdis.nasa.gov/",
        "api_key_env":      "FIRMS_API_KEY",
        "fallback":         "none — skipped if no key",
        "acquisition_mode": "query_driven",
        "notes":            "Thermal proxy for open waste burning. Satellite pixels "
                            "directly assigned to H3 cells.",
    },
    "construction": {
        "provider":         "Google Earth Engine",
        "url":              "https://earthengine.google.com/",
        "api_key_env":      "GEE_PROJECT",
        "fallback":         "none — skipped if no key",
        "acquisition_mode": "query_driven",
        "notes":            "SAR/optical change detection. Satellite raster sampled "
                            "per H3 cell — no interpolation needed.",
    },
    "green": {
        "provider":         "Google Earth Engine",
        "url":              "https://earthengine.google.com/",
        "api_key_env":      "GEE_PROJECT",
        "fallback":         "none — skipped if no key",
        "acquisition_mode": "query_driven",
        "notes":            "NDVI from Sentinel-2 / Landsat. Pixel-to-cell direct "
                            "assignment at H3 res 8.",
    },
    "noise": {
        "provider":         "OpenStreetMap + computed",
        "url":              "https://www.openstreetmap.org/",
        "api_key_env":      None,
        "fallback":         "computed from OSM road/rail network",
        "acquisition_mode": "query_driven",
        "notes":            "Road traffic + rail proximity noise model. Computed "
                            "analytically per H3 cell from OSM geometry — no physical sensors.",
    },
    "weather": {
        "provider":         "Open-Meteo Forecast API",
        "url":              "https://api.open-meteo.com/",
        "api_key_env":      None,
        "fallback":         "none needed — always available",
        "acquisition_mode": "query_driven",
        "notes":            "Wind, humidity, pressure, temperature — queried per H3 cell "
                            "centroid. Free, no key required.",
    },
}

_DOMAIN_ORDER = ["air", "weather", "heat", "flood", "fire", "waste", "water",
                 "construction", "green", "noise"]

# Derived from the central city registry — single source of truth.
_CITY_DISPLAY: dict[str, str] = {k: v["display_name"] for k, v in _CITY_REGISTRY.items()}

# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

_STATUS_ICON = {
    "ok":      "🟢",
    "partial": "🟡",
    "error":   "🔴",
    "never":   "⚪",
}

_STATUS_CSS = {
    "ok":      "color:#1a7f37;font-weight:500",
    "partial": "color:#8a6d00;font-weight:500",
    "error":   "color:#b42318;font-weight:500",
    "never":   "color:#6b7280",
}


def _parse_ts(ts) -> Optional[datetime]:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _age_str(ts) -> str:
    dt = _parse_ts(ts)
    if not dt:
        return "never"
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:    return "just now"
    if s < 3600:  return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _staleness_style(ts) -> str:
    dt = _parse_ts(ts)
    if not dt:
        return "color:#6b7280"
    hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if hours > 24:  return "color:#b42318"
    if hours > 6:   return "color:#8a6d00"
    return "color:#1a7f37"


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_ingest_log() -> pd.DataFrame:
    try:
        from airos.drivers.store.store import H3KnowledgeStore
        return H3KnowledgeStore.get().fetchdf(
            "SELECT city_id, domain, last_ingested_at, rows_written, status, error_msg "
            "FROM h3_ingest_log ORDER BY city_id, domain"
        )
    except Exception as exc:
        st.warning(f"Could not load ingest log: {exc}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sub-components
# ---------------------------------------------------------------------------

def _render_api_key_status() -> None:
    """Compact 2-column grid of API key presence."""
    keys_needed = sorted({
        s["api_key_env"]
        for s in _SOURCES.values()
        if s["api_key_env"]
    })

    rows = []
    for k in keys_needed:
        val = os.environ.get(k, "")
        configured = bool(val and val.strip() and val != "your_key_here")
        rows.append({
            "env_var": k,
            "configured": configured,
            "domains": ", ".join(
                d for d, s in _SOURCES.items() if s.get("api_key_env") == k
            ),
        })

    configured_n = sum(1 for r in rows if r["configured"])
    st.caption(
        f"{configured_n}/{len(rows)} API keys configured — "
        "set them in `.env` to enable live data"
    )

    cols = st.columns(min(len(rows), 3))
    for i, row in enumerate(rows):
        with cols[i % len(cols)]:
            icon = "🟢" if row["configured"] else "🔴"
            st.markdown(
                f'<div style="border:0.5px solid rgba(0,0,0,0.12);border-radius:8px;'
                f'padding:10px 14px;margin-bottom:8px;">'
                f'<div style="font-size:12px;font-weight:500;">{icon} '
                f'<code style="font-size:11px">{row["env_var"]}</code></div>'
                f'<div style="font-size:11px;color:rgba(0,0,0,0.5);margin-top:3px;">'
                f'{row["domains"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_status_matrix(log_df: pd.DataFrame, cities: list[str]) -> None:
    """Domain × City status matrix — compact table with colour coding."""
    if log_df.empty:
        st.info("No ingest runs recorded yet. Start the scheduler to begin pulling data.")
        return

    # Build pivot: rows = domains, cols = cities
    # Each cell: icon + age
    city_labels = [_CITY_DISPLAY.get(c, c) for c in cities]

    _TH = ('text-align:left;padding:6px 10px;border-bottom:0.5px solid rgba(0,0,0,0.15);'
           'color:rgba(0,0,0,0.5);font-weight:500;')
    header_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
        '<thead><tr>'
        f'<th style="{_TH}min-width:120px;">Domain</th>'
        f'<th style="{_TH}min-width:140px;">Source</th>'
        f'<th style="{_TH}min-width:110px;">Acquisition</th>'
    )
    for city in city_labels:
        header_html += (
            f'<th style="text-align:center;padding:6px 8px;'
            f'border-bottom:0.5px solid rgba(0,0,0,0.15);'
            f'color:rgba(0,0,0,0.5);font-weight:500;min-width:90px;">{city}</th>'
        )
    header_html += "</tr></thead><tbody>"

    # Index log by (city_id, domain)
    log_idx: dict[tuple, dict] = {}
    for _, row in log_df.iterrows():
        log_idx[(row["city_id"], row["domain"])] = row.to_dict()

    rows_html = ""
    for i, domain in enumerate(_DOMAIN_ORDER):
        src = _SOURCES.get(domain, {})
        bg = "rgba(0,0,0,0.02)" if i % 2 == 0 else "transparent"
        row_html = (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 10px;font-weight:500;white-space:nowrap;">'
            f'{domain.title()}</td>'
            f'<td style="padding:7px 10px;color:rgba(0,0,0,0.6);white-space:nowrap;'
            f'font-size:11px;">{src.get("provider","—")}'
        )
        # show "no key" indicator inline
        key_env = src.get("api_key_env")
        if key_env:
            has_key = bool(os.environ.get(key_env, "").strip())
            row_html += (
                f' <span style="color:{"#1a7f37" if has_key else "#b42318"};'
                f'font-size:10px;">{"✓" if has_key else "⚠ no key"}</span>'
            )
        row_html += "</td>"

        # Acquisition mode badge
        acq = src.get("acquisition_mode", "")
        if acq == "sensor_list":
            acq_html = (
                '<span style="background:#fff3cd;color:#856404;padding:2px 6px;'
                'border-radius:3px;font-size:10px;font-weight:600;" '
                'title="Fixed sensor locations — IDW interpolation. '
                'DATA_CONFIDENCE degrades with distance. '
                'Sensor siting recommendations apply.">'
                '📡 Sensor list</span>'
            )
        elif acq == "query_driven":
            acq_html = (
                '<span style="background:#d1e7dd;color:#0a3622;padding:2px 6px;'
                'border-radius:3px;font-size:10px;font-weight:600;" '
                'title="We query at H3 cell centroids — no interpolation. '
                'DATA_CONFIDENCE = 1.0. '
                'No physical sensors to place.">'
                '🌐 Query-driven</span>'
            )
        else:
            acq_html = '<span style="color:#9ca3af;font-size:10px;">—</span>'
        row_html += f'<td style="padding:7px 10px;">{acq_html}</td>'

        for city_id in cities:
            entry = log_idx.get((city_id, domain))
            if not entry:
                cell = '<span style="color:#9ca3af">—</span>'
            else:
                status = str(entry.get("status") or "ok")
                ts     = entry.get("last_ingested_at")
                rows_w = int(entry.get("rows_written") or 0)
                icon   = _STATUS_ICON.get(status, "⚪")
                age    = _age_str(ts)
                stale_css = _staleness_style(ts)
                rows_txt = f"{rows_w:,}r" if rows_w > 0 else "0r"
                err_tip  = str(entry.get("error_msg") or "")[:60]
                tip_attr = f'title="{err_tip}"' if err_tip else ""
                cell = (
                    f'<span {tip_attr}>'
                    f'{icon} '
                    f'<span style="{stale_css};font-size:11px;">{age}</span>'
                    f'<br><span style="color:rgba(0,0,0,0.4);font-size:10px;">{rows_txt}</span>'
                    f'</span>'
                )
            row_html += (
                f'<td style="padding:7px 8px;text-align:center;'
                f'vertical-align:middle;">{cell}</td>'
            )

        row_html += "</tr>"
        rows_html += row_html

    table_html = header_html + rows_html + "</tbody></table>"

    # Legend
    legend = (
        '<div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap;">'
        + "".join(
            f'<span style="font-size:11px;color:rgba(0,0,0,0.6);">'
            f'{_STATUS_ICON[s]} {label}</span>'
            for s, label in [
                ("ok",      "Live data"),
                ("partial", "Degraded / fallback"),
                ("error",   "Error"),
                ("never",   "Never run"),
            ]
        )
        + '<span style="font-size:11px;color:#1a7f37;">● &lt;6h</span>'
        + '<span style="font-size:11px;color:#8a6d00;">● 6-24h</span>'
        + '<span style="font-size:11px;color:#b42318;">● &gt;24h stale</span>'
        + "</div>"
    )

    st.markdown(legend, unsafe_allow_html=True)
    st.markdown(
        f'<div style="overflow-x:auto;">{table_html}</div>',
        unsafe_allow_html=True,
    )


def _render_domain_detail(log_df: pd.DataFrame) -> None:
    """Expandable per-domain detail with error messages."""
    if log_df.empty:
        return
    with st.expander("Per-domain details & error messages", expanded=False):
        domain_sel = st.selectbox(
            "Domain",
            _DOMAIN_ORDER,
            format_func=lambda d: f"{d.title()} — {_SOURCES.get(d, {}).get('provider', '')}",
            key="ds_domain_sel",
        )
        src = _SOURCES.get(domain_sel, {})
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Provider:** {src.get('provider','—')}")
            st.markdown(f"**Notes:** {src.get('notes','—')}")
            st.markdown(f"**Fallback:** {src.get('fallback','—')}")
        with c2:
            key_env = src.get("api_key_env")
            if key_env:
                has_key = bool(os.environ.get(key_env, "").strip())
                st.markdown(
                    f"**API key env:** `{key_env}` "
                    f"{'🟢 configured' if has_key else '🔴 missing'}"
                )
            else:
                st.markdown("**API key:** not required")
            if src.get("url"):
                st.markdown(f"**Docs:** {src.get('url')}")

        subset = log_df[log_df["domain"] == domain_sel].copy()
        if subset.empty:
            st.caption("No ingest runs recorded for this domain.")
            return

        subset = subset[["city_id", "status", "last_ingested_at", "rows_written", "error_msg"]].copy()
        subset["city_id"] = subset["city_id"].map(
            lambda c: _CITY_DISPLAY.get(c, c)
        )
        subset["last_ingested_at"] = subset["last_ingested_at"].apply(_age_str)
        subset["rows_written"] = subset["rows_written"].fillna(0).astype(int)
        subset.columns = ["City", "Status", "Last Pull", "Rows", "Error"]
        st.dataframe(subset, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Scheduler status card
# ---------------------------------------------------------------------------

def _render_scheduler_status() -> None:
    from airos.os.scheduler import read_status

    s = read_status()
    if not s:
        st.warning(
            "**Batch scheduler is not running.**  \n"
            "Data is only refreshed when someone manually runs the ingest step.  \n"
            "Start the scheduler with: `python main.py --step scheduler`",
            icon="⚠️",
        )
        return

    state      = s.get("state", "unknown")
    icon       = {"idle": "🟢", "sweeping": "🔄", "starting": "🟡",
                  "stopped": "🔴"}.get(state, "⚪")
    last_sweep = _age_str(s.get("last_sweep_at"))
    next_sweep = _age_str(s.get("next_sweep_at"))  # shows negative = "in Xm"
    sweep_n    = s.get("sweep_count", 0)
    rows_last  = s.get("last_sweep_rows", 0)
    insights   = s.get("last_sweep_insights", 0)
    analysis   = s.get("last_analysis_completed", 0)
    interval   = s.get("sweep_interval_sec", 900)

    # "next sweep" is in the future — show time remaining
    try:
        from datetime import timedelta
        nxt = datetime.fromisoformat(
            s["next_sweep_at"].replace("Z", "+00:00")
        ) if "next_sweep_at" in s else None
        if nxt:
            remaining = int((nxt - datetime.now(timezone.utc)).total_seconds())
            next_label = (f"in {remaining//60}m {remaining%60}s"
                          if remaining > 0 else "imminent")
        else:
            next_label = "—"
    except Exception:
        next_label = "—"

    agent_status  = "enabled" if s.get("agent_enabled", True) else "disabled"
    analysis_txt  = f" &nbsp;·&nbsp; {analysis} analysis jobs" if analysis else ""

    st.markdown(
        f'<div style="border:0.5px solid rgba(0,0,0,0.12);border-radius:8px;'
        f'padding:12px 16px;margin-bottom:4px;display:flex;gap:32px;flex-wrap:wrap;">'
        f'<span style="font-size:13px;">{icon} <strong>Scheduler</strong> — {state}</span>'
        f'<span style="font-size:12px;color:rgba(0,0,0,0.55);">Sweep #{sweep_n} &nbsp;·&nbsp; '
        f'last {last_sweep} &nbsp;·&nbsp; next {next_label}</span>'
        f'<span style="font-size:12px;color:rgba(0,0,0,0.55);">'
        f'{rows_last:,} rows &nbsp;·&nbsp; {insights} insights{analysis_txt} last sweep</span>'
        f'<span style="font-size:12px;color:rgba(0,0,0,0.55);">'
        f'Interval {interval//60}m &nbsp;·&nbsp; Agent {agent_status}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_data_sources_panel() -> None:
    # ── Header ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:15px;font-weight:500;margin-bottom:2px;">'
        'Data Sources</div>'
        '<div style="font-size:12px;color:rgba(0,0,0,0.5);margin-bottom:14px;">'
        'Ingest pipeline status per domain and city. '
        'Scheduler: <code>python main.py --step scheduler</code>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Scheduler health ─────────────────────────────────────────────────────
    _render_scheduler_status()

    log_df = _load_ingest_log()

    # ── Summary metrics ──────────────────────────────────────────────────────
    if not log_df.empty:
        total   = len(log_df)
        ok_n    = int((log_df["status"] == "ok").sum())
        partial = int((log_df["status"] == "partial").sum())
        err_n   = int((log_df["status"] == "error").sum())
        latest  = log_df["last_ingested_at"].dropna()
        last_ts = _age_str(latest.max()) if len(latest) else "never"

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("🟢 Live",     ok_n,    help="Domains with live data this run")
        mc2.metric("🟡 Partial",  partial, help="Degraded — using fallback/synthetic")
        mc3.metric("🔴 Errors",   err_n,   help="Domains that errored last run")
        mc4.metric("Last run",    last_ts, help="Most recent ingest timestamp")

    st.divider()

    # ── API key status ────────────────────────────────────────────────────
    st.markdown("**API keys**")
    _render_api_key_status()

    st.divider()

    # ── City filter ───────────────────────────────────────────────────────
    all_cities = sorted(_CITY_DISPLAY.keys())
    if not log_df.empty:
        present = log_df["city_id"].unique().tolist()
        all_cities = [c for c in all_cities if c in present] or all_cities

    city_filter = st.multiselect(
        "Cities",
        options=all_cities,
        default=all_cities,
        format_func=lambda c: _CITY_DISPLAY.get(c, c),
        key="ds_city_filter",
        label_visibility="collapsed",
        placeholder="Filter cities…",
    )
    cities = city_filter or all_cities

    # ── Status matrix ─────────────────────────────────────────────────────
    st.markdown("**Pipeline status matrix**")
    _render_status_matrix(log_df, cities)

    # ── Per-domain detail ─────────────────────────────────────────────────
    st.markdown("")
    _render_domain_detail(log_df)
