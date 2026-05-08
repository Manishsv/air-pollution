from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

# Load .env before any connector imports read os.environ
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from urban_platform.sdk.client import UrbanPlatformClient

from review_dashboard.components.audit_panel import render_audit_panel
from review_dashboard.components.flood_panel import render_flood_panel
from review_dashboard.components.property_buildings_panel import render_property_buildings_panel
from review_dashboard.components.program_reporting_panel import render_program_reporting_panel
from review_dashboard.components.cross_domain_panel import render_cross_domain_panel
from review_dashboard.components.ward_panel import render_ward_panel
from review_dashboard.components.ward_decisions_panel import render_ward_decisions_panel
from review_dashboard.components.runtime_trace_panel import render_runtime_trace_panel
from review_dashboard.components.heat_panel import render_heat_panel
from review_dashboard.components.air_panel import render_air_panel
from review_dashboard.components.fire_panel import render_fire_panel
from review_dashboard.components.waste_panel import render_waste_panel
from review_dashboard.components.water_panel import render_water_panel
from review_dashboard.components.construction_panel import render_construction_panel
from review_dashboard.components.green_panel import render_green_panel
from review_dashboard.components.noise_panel import render_noise_panel
from review_dashboard.components.agent_panel import render_agent_panel
from review_dashboard.design_system import apply_airos_design_system
from review_dashboard.ui_shell import (
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)


st.set_page_config(page_title="AirOS Review Console", layout="wide")
apply_airos_design_system()


def _render_system_sidebar(client: UrbanPlatformClient, *, audit: dict, metrics: dict) -> None:
    with st.sidebar:
        st.title("AirOS Review Console")
        st.caption("Local-first review console for multiple use cases.")
        with st.expander("System Data Quality", expanded=False):
            render_audit_panel(audit, metrics)
        with st.expander("Technical: Data Contracts", expanded=False):
            cr = client.get_conformance_report()
            if not cr:
                st.caption("No conformance report yet. Run `python main.py --step conformance` to generate.")
                return
            rows = []
            for name, art in (cr.get("artifacts") or {}).items():
                rows.append({
                    "Artifact": name,
                    "Overall": art.get("status"),
                    "Core review contract": str(art.get("core_schema_status") or "n/a"),
                    "Air-quality profile": str(art.get("profile_schema_status") or "n/a"),
                    "Schema key": art.get("schema"),
                    "Errors": int(art.get("error_count") or 0),
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption(f"Validated at: {cr.get('validated_at', '—')}")

        with st.expander("H3 Knowledge Store", expanded=False):
            try:
                from urban_platform.h3_knowledge.reader import get_store_stats
                stats = get_store_stats()
                if stats:
                    st.dataframe(
                        pd.DataFrame(
                            [{"Table": k, "Rows": v} for k, v in stats.items()]
                        ),
                        hide_index=True, use_container_width=True,
                    )
                    total = sum(stats.values())
                    st.caption(f"Total records: {total:,}  |  DB: data/h3/knowledge.duckdb")
                else:
                    st.caption("Store empty — browse a domain tab to populate it.")
            except Exception as _e:
                st.caption(f"Knowledge store unavailable: {_e}")


def _render_events(events: pd.DataFrame) -> None:
    render_section_title("Events / Tasks Queue")
    if events is None or events.empty:
        st.caption("No events yet. Run `python main.py` to generate decision packets and events.")
        return
    etypes = sorted(events["event_type"].astype(str).unique().tolist()) if "event_type" in events.columns else []
    sev = sorted(events["severity"].astype(str).unique().tolist()) if "severity" in events.columns else []
    c1, c2 = st.columns(2)
    with c1:
        et = st.selectbox("Event type", options=["(all)"] + etypes, index=0, key="events_type")
    with c2:
        sv = st.selectbox("Severity", options=["(all)"] + sev, index=0, key="events_sev")
    df = events.copy()
    if et != "(all)" and "event_type" in df.columns:
        df = df[df["event_type"].astype(str) == et]
    if sv != "(all)" and "severity" in df.columns:
        df = df[df["severity"].astype(str) == sv]
    cols = [c for c in ["timestamp", "severity", "event_type", "spatial_unit_id",
                        "recommended_action", "source_packet_id", "status"] if c in df.columns]
    sort_col = "timestamp" if "timestamp" in df.columns else None
    display = df[cols] if cols else df
    st.dataframe(
        display.sort_values(sort_col, ascending=False) if sort_col else display,
        hide_index=True, use_container_width=True,
    )


def _render_crowd(client: UrbanPlatformClient) -> tuple[pd.DataFrame | None, list[dict]]:
    render_section_title("Latest observations")
    obs = client.get_observations(variable="people_count")
    if obs is None or obs.empty:
        st.caption("No `people_count` observations found yet. Run the camera publisher + ingest, then refresh.")
        return None, []
    df = obs.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if "entity_id" in df.columns:
        df = df.sort_values("timestamp").groupby("entity_id", as_index=False).tail(1)
        show = [c for c in ["entity_id", "timestamp", "value", "unit", "quality_flag", "source"]
                if c in df.columns]
        out = df[show].sort_values("timestamp", ascending=False)
        st.dataframe(out, hide_index=True, use_container_width=True)
        return obs, out.head(50).to_dict(orient="records")
    tail = df.tail(50)
    st.dataframe(tail, hide_index=True, use_container_width=True)
    return obs, tail.to_dict(orient="records")


def main():
    client = UrbanPlatformClient(base_path=str(PROJECT_ROOT))
    metrics = client.get_metrics()
    audit = client.get_data_audit()
    events = client.get_events()

    _render_system_sidebar(client, audit=audit, metrics=metrics)

    t_aq, t_fire, t_waste, t_water, t_construction, t_green, t_noise, t_flood, t_heat, t_cross, t_ward, t_decisions, t_property, t_program, t_trace, t_crowd, t_events, t_agent = st.tabs([
        "Air Quality", "Fire", "Waste", "Water Quality", "Construction & Dust",
        "Green Cover", "Noise", "Flood", "Heat", "Cross-Domain", "Ward QoL",
        "Ward Decisions", "Property & Buildings", "Program Reporting", "Runtime Trace",
        "Crowd", "Events", "🤖 H3 Agent",
    ])

    with t_aq:
        render_air_panel()

    with t_fire:
        render_fire_panel()

    with t_waste:
        render_waste_panel()

    with t_water:
        render_water_panel()

    with t_construction:
        render_construction_panel()

    with t_green:
        render_green_panel()

    with t_noise:
        render_noise_panel()

    with t_flood:
        render_flood_panel()

    with t_heat:
        render_heat_panel()

    with t_cross:
        render_cross_domain_panel()

    with t_ward:
        render_ward_panel()

    with t_decisions:
        render_ward_decisions_panel()

    with t_property:
        render_property_buildings_panel()

    with t_program:
        render_program_reporting_panel()

    with t_trace:
        render_runtime_trace_panel()

    with t_crowd:
        render_domain_header(
            title="Crowd / People count",
            caption="Latest ingested `people_count` observations for spatial units (demo or live ingest).",
            primary_alert="Counts are operational signals, not identity. Use only for capacity and safety review workflows.",
            primary_alert_kind="info",
        )
        _obs_df, crowd_preview = _render_crowd(client)
        render_technical_json_expander(
            title="Technical: people_count preview",
            payload={
                "row_count": 0 if _obs_df is None or _obs_df.empty else int(len(_obs_df)),
                "preview_rows": crowd_preview,
            },
        )

    with t_agent:
        render_agent_panel()

    with t_events:
        render_domain_header(
            title="Events / Tasks queue",
            caption="System-generated events linked to decision packets and recommended actions.",
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
                "total_rows": 0 if events is None or events.empty else int(len(events)),
            },
        )


if __name__ == "__main__":
    main()
