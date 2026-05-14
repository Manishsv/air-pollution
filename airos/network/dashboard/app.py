from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

# app.py lives at airos/network/dashboard/app.py — repo root is 3 levels up
_APP_FILE = Path(__file__).resolve()
PROJECT_ROOT = _APP_FILE.parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before any connector imports read os.environ
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

import pandas as pd
import streamlit as st

from airos.os.sdk.client import AirOSClient

# ── Stakeholder overview ──────────────────────────────────────────────────
from airos.network.dashboard.components.overview_panel import render_overview_panel

# ── Primary views ─────────────────────────────────────────────────────────
from airos.network.dashboard.components.citymap_panel import render_citymap_panel
from airos.network.dashboard.components.inbox_panel import render_inbox_panel

# ── Raw Data Explorer (source-centric) ────────────────────────────────────
from airos.network.dashboard.components.raw_data_panel import render_raw_data_panel

# ── Domain signal panels (no decision packets, no H3 sliders) ─────────────
from airos.network.dashboard.components.air_panel import render_air_panel
from airos.network.dashboard.components.flood_panel import render_flood_panel
from airos.network.dashboard.components.heat_panel import render_heat_panel
from airos.network.dashboard.components.water_panel import render_water_panel
from airos.network.dashboard.components.fire_panel import render_fire_panel
from airos.network.dashboard.components.waste_panel import render_waste_panel
from airos.network.dashboard.components.construction_panel import render_construction_panel
from airos.network.dashboard.components.green_panel import render_green_panel
from airos.network.dashboard.components.noise_panel import render_noise_panel

# ── Infrastructure & programme panels ────────────────────────────────────
from airos.network.dashboard.components.terrain_panel import render_terrain_panel
from airos.network.dashboard.components.nightlights_panel import render_nightlights_panel
from airos.network.dashboard.components.infrastructure_panel import render_infrastructure_panel


# ── Operations panels ─────────────────────────────────────────────────────
from airos.network.dashboard.components.audit_panel import render_audit_panel
from airos.network.dashboard.components.data_audit_panel import render_data_audit_panel
from airos.network.dashboard.components.data_sources_panel import render_data_sources_panel
from airos.network.dashboard.components.sensor_coverage_panel import render_sensor_coverage_panel
from airos.network.dashboard.components.runtime_trace_panel import render_runtime_trace_panel

from airos.network.dashboard.design_system import apply_airos_design_system
from airos.network.dashboard.ui_shell import (
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)


st.set_page_config(page_title="AirOS Review Console", layout="wide")
apply_airos_design_system()


# ---------------------------------------------------------------------------
# Cached data loaders — prevent re-reading files/DB on every Streamlit rerender
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_metrics(base_path: str) -> dict:
    try:
        return AirOSClient(base_path=base_path).get_metrics()
    except Exception:
        return {}

@st.cache_data(ttl=60, show_spinner=False)
def _load_audit(base_path: str) -> dict:
    try:
        return AirOSClient(base_path=base_path).get_data_audit()
    except Exception:
        return {}

@st.cache_data(ttl=60, show_spinner=False)
def _load_events(base_path: str) -> pd.DataFrame:
    try:
        return AirOSClient(base_path=base_path).get_events()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def _load_conformance(base_path: str) -> dict:
    try:
        return AirOSClient(base_path=base_path).get_conformance_report()
    except Exception:
        return {}

@st.cache_data(ttl=60, show_spinner=False)
def _load_store_stats() -> dict:
    try:
        from airos.os.sdk import store
        return store.get_stats() or {}
    except Exception:
        return {}

@st.cache_data(ttl=30, show_spinner=False)
def _load_analysis_queue() -> pd.DataFrame:
    try:
        from airos.os.sdk import store
        return store.get_analysis_queue()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=30, show_spinner=False)
def _load_scheduler_status() -> dict:
    try:
        from airos.os.scheduler import read_status
        return read_status() or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar(*, audit: dict, metrics: dict, base_path: str) -> None:
    with st.sidebar:
        st.markdown(
            '<div style="font-size:18px;font-weight:600;margin-bottom:2px;">AirOS</div>'
            '<div style="font-size:12px;color:rgba(0,0,0,0.45);margin-bottom:16px;">'
            'Urban Intelligence Console</div>',
            unsafe_allow_html=True,
        )

        with st.expander("System data quality", expanded=False):
            render_audit_panel(audit, metrics)

        with st.expander("Data contracts", expanded=False):
            cr = _load_conformance(base_path)
            if not cr:
                st.caption("No conformance report. Run `python main.py --step conformance`.")
            else:
                rows = []
                for name, art in (cr.get("artifacts") or {}).items():
                    rows.append({
                        "Artifact": name,
                        "Status":   art.get("status"),
                        "Errors":   int(art.get("error_count") or 0),
                    })
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(f"Validated: {cr.get('validated_at', '—')}")

        with st.expander("LLM provider", expanded=False):
            from airos.agents.llm_config import load_config as _lc, PROVIDER_PRESETS
            _cfg = _lc()
            st.markdown(f"**{_cfg.label}**")
            st.caption(f"Model: `{_cfg.model}`")
            st.caption(f"URL: `{_cfg.base_url}`")
            st.caption(
                PROVIDER_PRESETS.get(_cfg.provider, {}).get("notes", "")
                or "Set LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY in .env"
            )

        with st.expander("Web search", expanded=False):
            from airos.agents.web_search import (
                load_web_search_config as _lwsc, PROVIDER_PRESETS as _WS_PRESETS,
            )
            _wsc = _lwsc()
            if _wsc.enabled:
                st.markdown(f"✅ **{_wsc.label}**")
                st.caption("Agents can search recent news to validate findings.")
            else:
                st.markdown("⚫ **Disabled**")
                st.caption(
                    "Set `WEB_SEARCH_PROVIDER` in .env to enable. "
                    "Options: `duckduckgo` (no key needed), `tavily`, `brave`, `serpapi`."
                )
            with st.container():
                for name, preset in _WS_PRESETS.items():
                    if name == "none":
                        continue
                    key_note = "no API key required" if not preset.get("requires_key") else f"needs `WEB_SEARCH_API_KEY`"
                    st.caption(f"**{name}** — {preset['label']} ({key_note})")

        with st.expander("H3 knowledge store", expanded=False):
            stats = _load_store_stats()
            if stats:
                st.dataframe(
                    pd.DataFrame([{"Table": k, "Rows": v} for k, v in stats.items()]),
                    hide_index=True, use_container_width=True,
                )
                st.caption(f"Total: {sum(stats.values()):,} records")
                st.caption("Run `python main.py --step ingest-h3` to refresh.")
            else:
                st.caption("Store empty. Run `python main.py --step ingest-h3`.")

        with st.expander("Analysis queue", expanded=False):
            q_df = _load_analysis_queue()
            if q_df.empty:
                st.caption("No analysis requests yet.")
            else:
                st.dataframe(q_df, hide_index=True, use_container_width=True)
                pending = q_df.loc[q_df["status"] == "pending", "count"].sum()
                if pending:
                    st.caption(f"⏳ {int(pending)} request(s) queued — scheduler picks up ≤ 3/sweep.")

        with st.expander("Scheduler status", expanded=False):
            sc = _load_scheduler_status()
            if sc:
                state = sc.get("state", "unknown")
                icon  = {"idle": "🟢", "sweeping": "🔵", "stopped": "🔴"}.get(state, "⚪")
                st.markdown(f"{icon} **{state.upper()}**")
                if sc.get("last_sweep_at"):
                    st.caption(f"Last sweep: {sc['last_sweep_at'][:16].replace('T',' ')} UTC")
                if sc.get("next_sweep_at"):
                    st.caption(f"Next sweep: {sc['next_sweep_at'][:16].replace('T',' ')} UTC")
                rows    = sc.get("last_sweep_rows", 0)
                insights = sc.get("last_sweep_insights", 0)
                analysis = sc.get("last_analysis_completed", 0)
                st.caption(f"Last sweep: {rows} rows · {insights} insights · {analysis} analysis jobs")
                st.caption(f"Sweep #{sc.get('sweep_count', 0)} · interval {sc.get('sweep_interval_sec', 900)}s")
            else:
                st.caption("Scheduler not running. Start with `python main.py --step scheduler`.")


# ---------------------------------------------------------------------------
# Events helper (used in Data Explorer)
# ---------------------------------------------------------------------------

def _render_events(events: pd.DataFrame) -> None:
    render_section_title("Events / Tasks queue")
    if events is None or events.empty:
        st.caption("No events. Run `python main.py` to generate decision packets.")
        return
    etypes = sorted(events["event_type"].astype(str).unique().tolist()) if "event_type" in events.columns else []
    sev    = sorted(events["severity"].astype(str).unique().tolist()) if "severity" in events.columns else []
    c1, c2 = st.columns(2)
    with c1:
        et = st.selectbox("Event type", ["(all)"] + etypes, index=0, key="events_type")
    with c2:
        sv = st.selectbox("Severity", ["(all)"] + sev, index=0, key="events_sev")
    df = events.copy()
    if et != "(all)" and "event_type" in df.columns:
        df = df[df["event_type"].astype(str) == et]
    if sv != "(all)" and "severity" in df.columns:
        df = df[df["severity"].astype(str) == sv]
    cols = [c for c in ["timestamp","severity","event_type","spatial_unit_id",
                         "recommended_action","source_packet_id","status"] if c in df.columns]
    sort_col = "timestamp" if "timestamp" in df.columns else None
    display  = df[cols] if cols else df
    st.dataframe(
        display.sort_values(sort_col, ascending=False) if sort_col else display,
        hide_index=True, use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    base_path = str(PROJECT_ROOT)
    metrics   = _load_metrics(base_path)
    audit     = _load_audit(base_path)
    events    = _load_events(base_path)

    _render_sidebar(audit=audit, metrics=metrics, base_path=base_path)

    # ── Primary navigation ────────────────────────────────────────────────
    # 🗺️ Map is the default landing view (situational awareness — the
    # full-screen H3 map with assessment-domain overlays, methodology
    # §11 design principle of "see the place, then the alerts"). Inbox
    # remains a sibling tab for operator triage.
    t_map, t_overview, t_inbox, t_domains, t_ops = st.tabs([
        "🗺️ Map",
        "🏙️ Overview",
        "📬 Inbox",
        "📊 Domains",
        "🔧 Operations",
    ])

    # ── Map (full-screen situational awareness — default landing view) ────
    with t_map:
        render_citymap_panel()

    # ── Overview (stakeholder views) ──────────────────────────────────────
    with t_overview:
        render_overview_panel()

    # ── Inbox (list + map views — view toggle lives inside the panel
    #          so it can share a single unified filter row with Sort) ───────
    with t_inbox:
        render_inbox_panel()

    # ── Domains (signal maps per risk domain) ────────────────────────────
    with t_domains:
        # Selectbox navigation: only the selected domain panel renders.
        # Using st.tabs here would render all 14 panels simultaneously on every rerun.
        _DOMAIN_PANELS = {
            "🌬️ Air Quality":      render_air_panel,
            "💧 Flood":             render_flood_panel,
            "🌡️ Heat":              render_heat_panel,
            "🏞️ Water Quality":     render_water_panel,
            "🔥 Fire":              render_fire_panel,
            "🗑️ Waste":             render_waste_panel,
            "🏗️ Construction":      render_construction_panel,
            "🌿 Green Cover":       render_green_panel,
            "🔊 Noise":             render_noise_panel,
            "🏔️ Terrain":            render_terrain_panel,
            "💡 Night Lights":       render_nightlights_panel,
            "🏙️ Infrastructure":    render_infrastructure_panel,
        }
        domain_choice = st.selectbox(
            "Domain", list(_DOMAIN_PANELS.keys()), key="domain_panel_selector",
            label_visibility="collapsed",
        )
        _DOMAIN_PANELS[domain_choice]()

    # ── Operations ────────────────────────────────────────────────────────
    with t_ops:
        # Selectbox navigation: only the selected panel renders — avoids running
        # all sub-panels simultaneously (which is what st.tabs does).
        _OPS_PANELS = {
            "🔍 Data Audit":      "audit",
            "🔌 Data Sources":    "sources",
            "📡 Sensor Coverage": "sensors",
            "🖥️ Runtime Trace":   "trace",
            "📋 Events":          "events",
            "🔬 Raw Data":        "raw",
        }
        ops_choice = st.selectbox(
            "View", list(_OPS_PANELS.keys()), key="ops_panel_selector",
            label_visibility="collapsed",
        )
        ops_view = _OPS_PANELS[ops_choice]

        if ops_view == "audit":
            from airos.os.city_config import CITIES as _CITIES
            _audit_city = st.selectbox(
                "City", list(_CITIES.keys()), key="audit_city_sel",
                label_visibility="collapsed",
            ) if len(_CITIES) > 1 else list(_CITIES.keys())[0]
            render_data_audit_panel(city_id=_audit_city)
        elif ops_view == "sources":
            render_data_sources_panel()
        elif ops_view == "sensors":
            render_sensor_coverage_panel()
        elif ops_view == "trace":
            render_runtime_trace_panel()
        elif ops_view == "events":
            render_domain_header(
                title="Events / Tasks queue",
                caption="System-generated events linked to decision packets.",
                primary_alert=None,
            )
            _render_events(events)
            ev_preview = []
            if events is not None and not events.empty:
                prev = (events.sort_values("timestamp", ascending=False).head(40)
                        if "timestamp" in events.columns else events.head(40))
                ev_preview = prev.to_dict(orient="records")
            render_technical_json_expander(
                title="Technical: Events preview",
                payload={
                    "preview_rows": ev_preview,
                    "total_rows":   0 if events is None or events.empty else int(len(events)),
                },
            )
        elif ops_view == "raw":
            render_raw_data_panel()


if __name__ == "__main__":
    main()
