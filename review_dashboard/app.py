from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# Ensure `urban_platform` is importable regardless of Streamlit cwd.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent  # repo root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from urban_platform.sdk import UrbanPlatformClient
from urban_platform.common.provenance_summary import build_provenance_summary

from review_dashboard.components.audit_panel import render_audit_panel
from review_dashboard.components.evidence_tabs import render_evidence_tabs
from review_dashboard.components.filters import render_filters
from review_dashboard.components.map_view import render_map
from review_dashboard.components.packet_summary import render_packet_summary
from review_dashboard.components.flood_panel import render_flood_panel
from review_dashboard.components.property_buildings_panel import render_property_buildings_panel
from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_empty_state,
    render_section_title,
    render_technical_json_expander,
)


st.set_page_config(page_title="AirOS Review Console", layout="wide")


def _horizon_label(metrics: dict) -> str:
    # Avoid exposing raw target_col like pm25_t_plus_12h
    tc = str(metrics.get("target_col") or "")
    if "t_plus_" in tc and tc.endswith("h"):
        try:
            h = int(tc.split("t_plus_")[1].split("h")[0])
            return f"{h} hours"
        except Exception:
            pass
    return "—"


def _confidence_label(prov: dict) -> str:
    # coarse, stakeholder-safe summary
    try:
        low = prov.get("percent_low_confidence")
        if low is None:
            return "Unknown"
        low = float(low)
        if low <= 20:
            return "High"
        if low <= 50:
            return "Medium"
        return "Low"
    except Exception:
        return "Unknown"


def _banner(provenance_summary: dict, *, has_degraded_sensors: bool):
    synth = float(provenance_summary.get("percent_cells_synthetic", 0.0) or 0.0)
    interp = float(provenance_summary.get("percent_cells_interpolated", 0.0) or 0.0)
    if synth > 0:
        st.error("WARNING: Synthetic AQ data used. Do not use for decisions.")
    if interp > 80:
        st.warning(
            "Most grid cells do not have direct sensor readings. Values are estimated from nearby stations and should be reviewed before action."
        )
    if has_degraded_sensors:
        st.warning("Some sensors may be stale, degraded, or offline. Check sensor reliability before relying on the forecast.")


def _queue_df(packets: list[dict]) -> pd.DataFrame:
    rows = []
    for idx, p in enumerate(packets):
        pred = p.get("prediction") or {}
        conf = p.get("confidence") or {}
        prov_pkt = p.get("provenance") or {}
        rows.append(
            {
                "packet_id": p.get("packet_id"),
                "Area": f"Area {idx + 1}",
                "Forecast category": pred.get("pm25_category_india"),
                "Forecast PM2.5": pred.get("forecast_pm25_mean"),
                "Confidence": p.get("confidence_level"),
                "Suggested handling": p.get("actionability_level"),
                "Main concern": (p.get("risk_of_error") or [""])[0] if p.get("risk_of_error") else "",
                "_confidence_score": conf.get("confidence_score"),
                "_h3_id": p.get("h3_id"),
                "_aq_source_type": prov_pkt.get("aq_source_type"),
                "_suggested_next_step": p.get("recommended_action"),
            }
        )
    return pd.DataFrame(rows)


def _render_system_sidebar(client: UrbanPlatformClient, *, audit: dict, metrics: dict) -> None:
    with st.sidebar:
        st.title("AirOS Review Console")
        st.caption("Local-first review console for multiple use cases.")
        st.caption("UI layout follows `docs/UI_GUIDELINES.md`.")
        with st.expander("System Data Quality", expanded=False):
            render_audit_panel(audit, metrics)

        with st.expander("Technical: Data Contracts", expanded=False):
            cr = client.get_conformance_report()
            if not cr:
                st.caption("No conformance report yet. Run `python main.py --step conformance` or enable conformance in `config.yaml`.")
                return
            rows = []
            for name, art in (cr.get("artifacts") or {}).items():
                rows.append(
                    {
                        "Artifact": name,
                        "Overall": art.get("status"),
                        "Core review contract": str(art.get("core_schema_status") or "n/a"),
                        "Air-quality profile": str(art.get("profile_schema_status") or "n/a"),
                        "Schema key": art.get("schema"),
                        "Errors": int(art.get("error_count") or 0),
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption(f"Validated at: {cr.get('validated_at', '—')}")


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

    cols = [c for c in ["timestamp", "severity", "event_type", "spatial_unit_id", "recommended_action", "source_packet_id", "status"] if c in df.columns]
    if not cols:
        st.dataframe(df.sort_values("timestamp", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.dataframe(df[cols].sort_values("timestamp", ascending=False), hide_index=True, use_container_width=True)


def _render_crowd(client: UrbanPlatformClient) -> tuple[pd.DataFrame | None, list[dict]]:
    """Returns (observations_df_or_none, preview_rows_for_technical_panel)."""
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
        show = [c for c in ["entity_id", "timestamp", "value", "unit", "quality_flag", "source"] if c in df.columns]
        out = df[show].sort_values("timestamp", ascending=False)
        st.dataframe(out, hide_index=True, use_container_width=True)
        return obs, out.head(50).to_dict(orient="records")
    tail = df.tail(50)
    st.dataframe(tail, hide_index=True, use_container_width=True)
    return obs, tail.to_dict(orient="records")


def main():
    # Always anchor the SDK at the repo root so the dashboard works regardless of Streamlit's cwd.
    client = UrbanPlatformClient(base_path=str(PROJECT_ROOT))
    metrics = client.get_metrics()
    audit = client.get_data_audit()
    reliability = client.get_source_reliability()
    prov = build_provenance_summary(metrics, audit)
    events = client.get_events()

    _render_system_sidebar(client, audit=audit, metrics=metrics)

    t_air, t_flood, t_property, t_heat, t_crowd, t_events = st.tabs(
        ["Air Pollution", "Flood", "Property & Buildings", "Heat", "Crowd", "Events"]
    )

    with t_air:
        has_degraded = False
        try:
            rel = audit.get("source_reliability_summary") or {}
            has_degraded = int(rel.get("degraded_count", 0) or 0) + int(rel.get("suspect_count", 0) or 0) + int(rel.get("offline_count", 0) or 0) > 0
        except Exception:
            has_degraded = False

        render_domain_header(
            title="Air Pollution Review",
            caption="Grid-level PM2.5 review with provenance, confidence, and reviewer accountability.",
            primary_alert=(
                "Outputs support human review only. Do not treat forecasts or suggested next steps as operational orders."
            ),
            primary_alert_kind="info",
        )

        try:
            rel = audit.get("source_reliability_summary") or {}
            active = int(audit.get("number_of_real_aq_stations", 0) or 0)
            degraded = int(rel.get("degraded_count", 0) or 0) + int(rel.get("suspect_count", 0) or 0) + int(rel.get("offline_count", 0) or 0)
            sensors_label = f"{active} / {degraded}"
        except Exception:
            sensors_label = "—"

        render_context_metrics(
            ("Forecast horizon", _horizon_label(metrics)),
            ("Data confidence", _confidence_label(prov)),
            ("Cells interpolated", f"{float(prov.get('percent_cells_interpolated') or 0.0):.1f}%"),
            ("Sensors active / degraded", sensors_label),
        )
        _banner(prov, has_degraded_sensors=has_degraded)

        filters = render_filters()
        packets = client.get_decision_packets(
            category=filters["category"],
            min_confidence=filters["min_confidence"],
            recommendation_allowed=filters["recommendation_allowed"],
            actionability_level=filters["actionability_level"],
            confidence_level=filters["confidence_level"],
        )
        if filters["aq_source_type"]:
            packets = [p for p in packets if str((p.get("provenance") or {}).get("aq_source_type", "")).lower() == filters["aq_source_type"]]

        left, right = st.columns([0.62, 0.38], gap="large")
        st.session_state.setdefault("selected_packet_id", None)
        st.session_state.setdefault("selected_area_label", None)

        with left:
            tab_list, tab_map = st.tabs(["List View", "Map View"])
            dfq = _queue_df(packets)
            if dfq.empty:
                st.info("No areas match the current filters.")
            else:
                try:
                    cats = dfq["Forecast category"].astype(str).str.lower()
                    if len(cats) and (cats == "good").all():
                        st.info(
                            "No high-risk air-quality areas detected in this run. Areas are still listed for review because "
                            "data confidence, interpolation, or sensor reliability may require attention."
                        )
                except Exception:
                    pass

                sort_by = st.selectbox("Sort by", options=["Highest forecast", "Lowest confidence"], index=0)
                if sort_by == "Lowest confidence":
                    dfq = dfq.sort_values("_confidence_score", ascending=True)
                else:
                    dfq = dfq.sort_values("Forecast PM2.5", ascending=False)

                packet_to_area = {r["packet_id"]: r["Area"] for r in dfq.to_dict(orient="records")}
                area_to_packet = {r["Area"]: r["packet_id"] for r in dfq.to_dict(orient="records")}
                if st.session_state["selected_packet_id"] not in packet_to_area:
                    st.session_state["selected_packet_id"] = str(dfq["packet_id"].iloc[0])
                st.session_state["selected_area_label"] = packet_to_area.get(st.session_state["selected_packet_id"])

                with tab_list:
                    render_section_title("Areas Needing Review")
                    show_cols = ["Area", "Forecast category", "Forecast PM2.5", "Confidence", "Suggested handling", "Main concern"]
                    try:
                        evt = st.dataframe(
                            dfq[show_cols],
                            width="stretch",
                            hide_index=True,
                            on_select="rerun",
                            selection_mode="single-row",
                        )
                        sel_rows = (evt.get("selection") or {}).get("rows") if isinstance(evt, dict) else None
                        if sel_rows:
                            ridx = int(sel_rows[0])
                            pkt = str(dfq.iloc[ridx]["packet_id"])
                            st.session_state["selected_packet_id"] = pkt
                            st.session_state["selected_area_label"] = str(dfq.iloc[ridx]["Area"])
                    except Exception:
                        selected_area = st.selectbox(
                            "Select Area",
                            options=dfq["Area"].astype(str).tolist(),
                            index=int(dfq["Area"].astype(str).tolist().index(st.session_state["selected_area_label"])),
                        )
                        st.session_state["selected_packet_id"] = area_to_packet.get(str(selected_area))
                        st.session_state["selected_area_label"] = str(selected_area)
                        st.dataframe(dfq[show_cols], width="stretch", hide_index=True)

                with tab_map:
                    render_section_title("Map View")
                    with st.expander("Map layers", expanded=False):
                        st.caption("Turn layers on/off to inspect the evidence behind each area.")
                        st.session_state.setdefault("map_layers", {"areas": True, "selected": True, "aq_sensors": True})
                        ml = st.session_state["map_layers"]

                        st.markdown("**Polygon coloring mode (choose one)**")
                        mode_options = [
                            ("Forecast category", "areas"),
                            ("Confidence", "confidence"),
                            ("Uncertainty band", "uncertainty"),
                            ("AQ data type (observed/interpolated/synthetic)", "aq_data_type"),
                            ("Road density", "road_density"),
                            ("Built-up ratio", "built_up_ratio"),
                            ("Green area", "green_area"),
                            ("Industrial/commercial area", "industrial_commercial"),
                            ("Low-confidence cells", "low_confidence_cells"),
                            ("High-uncertainty cells", "high_uncertainty_cells"),
                        ]
                        current = st.session_state.get("map_color_mode")
                        if current is None:
                            if ml.get("confidence"):
                                current = "confidence"
                            elif ml.get("uncertainty"):
                                current = "uncertainty"
                            elif ml.get("road_density"):
                                current = "road_density"
                            elif ml.get("built_up_ratio"):
                                current = "built_up_ratio"
                            elif ml.get("green_area"):
                                current = "green_area"
                            elif ml.get("industrial_commercial"):
                                current = "industrial_commercial"
                            elif ml.get("low_confidence_cells"):
                                current = "low_confidence_cells"
                            elif ml.get("high_uncertainty_cells"):
                                current = "high_uncertainty_cells"
                            elif ml.get("observed_cells") or ml.get("interpolated_cells") or ml.get("synthetic_cells"):
                                current = "aq_data_type"
                            else:
                                current = "areas"
                        sel_label = st.selectbox(
                            "Color polygons by",
                            options=[l for (l, _k) in mode_options],
                            index=int([k for (_l, k) in mode_options].index(current)),
                        )
                        sel_key = dict(mode_options)[sel_label]
                        st.session_state["map_color_mode"] = sel_key

                        for k in [
                            "areas",
                            "confidence",
                            "uncertainty",
                            "observed_cells",
                            "interpolated_cells",
                            "synthetic_cells",
                            "road_density",
                            "built_up_ratio",
                            "green_area",
                            "industrial_commercial",
                            "low_confidence_cells",
                            "high_uncertainty_cells",
                        ]:
                            ml[k] = False
                        if sel_key == "aq_data_type":
                            ml["observed_cells"] = True
                            ml["interpolated_cells"] = True
                            ml["synthetic_cells"] = True
                        else:
                            ml[sel_key] = True

                        st.markdown("**Evidence layers**")
                        ml["selected"] = st.checkbox("Selected area outline", value=bool(ml.get("selected", True)))
                        ml["aq_sensors"] = st.checkbox("AQ sensors (markers)", value=bool(ml.get("aq_sensors", True)))
                        ml["sensor_reliability"] = st.checkbox("Color sensors by reliability", value=bool(ml.get("sensor_reliability", False)))

                        st.markdown("**Planning**")
                        ml["sensor_siting"] = st.checkbox("Sensor siting candidates", value=bool(ml.get("sensor_siting", False)))
                        st.session_state["high_uncertainty_threshold"] = st.slider(
                            "High-uncertainty threshold (band)", 10.0, 200.0, float(st.session_state.get("high_uncertainty_threshold", 50.0)), 5.0
                        )
                        st.session_state["max_cells_for_map"] = int(
                            st.number_input("Max cells to render", min_value=50, max_value=2000, value=int(st.session_state.get("max_cells_for_map", 400)), step=50)
                        )

                    features_df = None
                    if st.session_state["map_layers"].get("road_density") or st.session_state["map_layers"].get("built_up_ratio") or st.session_state["map_layers"].get("green_area"):
                        features_df = client.get_features()

                    selected_packet = client.get_decision_packet(st.session_state["selected_packet_id"]) if st.session_state["selected_packet_id"] else None
                    before = st.session_state.get("selected_packet_id")
                    render_map(
                        packets,
                        selected_packet,
                        features_df=features_df,
                        sensor_siting_gdf=None,
                    )
                    after = st.session_state.get("selected_packet_id")
                    if after and after != before:
                        st.session_state["selected_area_label"] = packet_to_area.get(after)
                        st.rerun()

        selected = client.get_decision_packet(st.session_state["selected_packet_id"]) if st.session_state["selected_packet_id"] else None
        with right:
            if not selected:
                st.info("Select an area to view details.")
            else:
                area_label = st.session_state.get("selected_area_label") or "Selected Area"
                t_sum, t_evd, t_dec, t_log = st.tabs(["Review Summary", "Supporting Evidence", "Reviewer Decision", "Audit Log"])

                with t_sum:
                    with st.container(height=780):
                        render_packet_summary(selected, title=f"{area_label}")

                with t_evd:
                    with st.container(height=780):
                        render_evidence_tabs(selected, reliability_df=reliability)

                with t_dec:
                    with st.container(height=780):
                        render_section_title("Reviewer decision")
                        st.caption(
                            "Choose what should happen next. The system provides evidence and a suggested next step, "
                            "but the reviewer remains accountable for the decision."
                        )
                        if "action_log" not in st.session_state:
                            st.session_state.action_log = []
                        note = st.text_area("Reviewer note (required)", value="", height=80)
                        action = st.selectbox(
                            "Next step",
                            options=[
                                "Send for field verification",
                                "Issue public advisory",
                                "Create inspection task",
                                "Escalate to responsible agency",
                                "No action required",
                            ],
                        )
                        if st.button("Record action"):
                            if not note.strip():
                                st.error("Reviewer note is required.")
                            else:
                                st.session_state.action_log.append(
                                    {
                                        "packet_id": selected.get("packet_id"),
                                        "selected_action": action,
                                        "reviewer_note": note.strip(),
                                        "timestamp": str(datetime.now(timezone.utc)),
                                    }
                                )
                                st.success("Action recorded (session only).")

                with t_log:
                    with st.container(height=780):
                        render_section_title("Audit log (session)")
                        st.dataframe(pd.DataFrame(st.session_state.get("action_log", [])), width="stretch", hide_index=True)

        render_technical_json_expander(
            title="Technical: Raw reviewer context",
            payload={
                "filters": filters,
                "selected_packet_id": st.session_state.get("selected_packet_id"),
                "selected_decision_packet": selected,
                "provenance_summary": prov,
            },
        )

    with t_flood:
        render_flood_panel()

    with t_property:
        render_property_buildings_panel()

    with t_heat:
        render_domain_header(
            title="Heat Risk Review",
            caption="Placeholder tab until heat risk consumer contracts and payloads are wired.",
            primary_alert=None,
        )
        render_empty_state(
            "Heat risk review is not implemented in this build.",
            hint="Follow `docs/UI_GUIDELINES.md` and extend specs before adding live heat data.",
        )
        render_technical_json_expander(title="Technical: Placeholder", payload={"status": "not_implemented"})

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

    with t_events:
        render_domain_header(
            title="Events / Tasks queue",
            caption="System-generated events linked to decision packets and recommended actions.",
            primary_alert=None,
        )
        _render_events(events)
        ev_preview = []
        if events is not None and not events.empty:
            prev = events.sort_values("timestamp", ascending=False).head(40) if "timestamp" in events.columns else events.head(40)
            ev_preview = prev.to_dict(orient="records")
        render_technical_json_expander(
            title="Technical: Events preview",
            payload={"preview_rows": ev_preview, "total_rows": 0 if events is None or events.empty else int(len(events))},
        )


if __name__ == "__main__":
    main()

