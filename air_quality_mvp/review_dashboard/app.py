from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

# Ensure `urban_platform` is importable regardless of Streamlit cwd.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent  # air_quality_mvp/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from urban_platform.sdk import UrbanPlatformClient
from urban_platform.common.provenance_summary import build_provenance_summary

from review_dashboard.components.audit_panel import render_audit_panel
from review_dashboard.components.evidence_tabs import render_evidence_tabs
from review_dashboard.components.filters import render_filters
from review_dashboard.components.map_view import render_map
from review_dashboard.components.packet_summary import render_packet_summary


st.set_page_config(page_title="Air Quality Review Console", layout="wide")


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


def render_crowd_tab(client: UrbanPlatformClient) -> None:
    st.title("Crowd Monitor")
    st.caption("Edge-derived people counts (no video stored). Shows latest 5-second window count per device.")

    df = client.get_observations(variable="people_count")
    if df is None or df.empty:
        st.info("No people_count observations found yet. Run the edge publisher + ingestion routine first.")
        return

    # Normalize timestamp and drop invalid rows
    df = df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df[df["timestamp"].notna()]

    if df.empty or "entity_id" not in df.columns:
        st.info("No valid crowd observations found yet.")
        return

    # Latest per entity_id
    latest = (
        df.sort_values("timestamp", ascending=True)
        .groupby(df["entity_id"].astype(str), as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    latest = latest.rename(columns={"timestamp": "latest_timestamp", "value": "latest_people_count"})
    cols = [c for c in ["entity_id", "latest_people_count", "latest_timestamp", "quality_flag", "source"] if c in latest.columns]

    c1, c2 = st.columns(2)
    c1.metric("Devices reporting", int(latest["entity_id"].nunique()))
    c2.metric("Total latest count", float(pd.to_numeric(latest.get("latest_people_count"), errors="coerce").fillna(0).sum()))

    st.subheader("Latest people count by device")
    st.dataframe(latest[cols].sort_values("entity_id"), hide_index=True, use_container_width=True)


def render_heat_tab() -> None:
    st.title("Heat (placeholder)")
    st.caption("This tab is reserved for a future heat use case (provider contracts → platform objects → consumer outputs).")
    st.info("Not implemented yet.")


def render_air_pollution_tab(client: UrbanPlatformClient) -> None:
    metrics = client.get_metrics()
    audit = client.get_data_audit()
    reliability = client.get_source_reliability()
    prov = build_provenance_summary(metrics, audit)

    st.title("Air Quality Review Console")
    st.caption("Review forecasted PM2.5 conditions, data confidence, and suggested field actions.")

    # Sidebar: System Data Quality (instead of a large bottom panel)
    with st.sidebar:
        with st.expander("System Data Quality", expanded=False):
            render_audit_panel(audit, metrics)

        with st.expander("Technical: Data Contracts", expanded=False):
            cr = client.get_conformance_report()
            if not cr:
                st.caption("No conformance report yet. Run the pipeline with `conformance.enabled` in config.")
            else:
                rows = []
                for name, art in (cr.get("artifacts") or {}).items():
                    core_l = str(art.get("core_schema_status") or "n/a")
                    prof_l = str(art.get("profile_schema_status") or "n/a")
                    rows.append(
                        {
                            "Artifact": name,
                            "Overall": art.get("status"),
                            "Core review contract": core_l,
                            "Air-quality profile": prof_l,
                            "Schema key": art.get("schema"),
                            "Errors": int(art.get("error_count") or 0),
                        }
                    )
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(f"Validated at: {cr.get('validated_at', '—')}")

    # Plain-language banners
    has_degraded = False
    try:
        rel = audit.get("source_reliability_summary") or {}
        has_degraded = int(rel.get("degraded_count", 0) or 0) + int(rel.get("suspect_count", 0) or 0) + int(rel.get("offline_count", 0) or 0) > 0
    except Exception:
        has_degraded = False
    _banner(prov, has_degraded_sensors=has_degraded)

    # Top 4 cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Forecast horizon", _horizon_label(metrics))
    c2.metric("Data confidence", _confidence_label(prov))
    c3.metric("Cells interpolated", f"{float(prov.get('percent_cells_interpolated') or 0.0):.1f}%")
    try:
        rel = audit.get("source_reliability_summary") or {}
        # "Active" sensors should reflect real AQ sensors, not reliability scoring rows.
        active = int(audit.get("number_of_real_aq_stations", 0) or 0)
        degraded = int(rel.get("degraded_count", 0) or 0) + int(rel.get("suspect_count", 0) or 0) + int(rel.get("offline_count", 0) or 0)
        c4.metric("Sensors active / degraded", f"{active} / {degraded}")
    except Exception:
        c4.metric("Sensors active / degraded", "—")

    filters = render_filters()

    packets = client.get_decision_packets(
        category=filters["category"],
        min_confidence=filters["min_confidence"],
        recommendation_allowed=filters["recommendation_allowed"],
        actionability_level=filters["actionability_level"],
        confidence_level=filters["confidence_level"],
    )

    # additional filter by aq_source_type (in-memory)
    if filters["aq_source_type"]:
        packets = [p for p in packets if str((p.get("provenance") or {}).get("aq_source_type", "")).lower() == filters["aq_source_type"]]

    # Layout: give more space to the map/list via tabs
    main, right = st.columns([0.62, 0.38], gap="large")

    st.session_state.setdefault("selected_packet_id", None)
    st.session_state.setdefault("selected_area_label", None)

    with main:
        tab_list, tab_map = st.tabs(["List View", "Map View"])

        dfq = _queue_df(packets)
        if dfq.empty:
            st.info("No areas match the current filters.")
        else:
            # Empty-state guidance if everything is Good
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

            # Keep selection stable across reruns
            packet_to_area = {r["packet_id"]: r["Area"] for r in dfq.to_dict(orient="records")}
            area_to_packet = {r["Area"]: r["packet_id"] for r in dfq.to_dict(orient="records")}
            if st.session_state["selected_packet_id"] not in packet_to_area:
                # default to first visible
                st.session_state["selected_packet_id"] = str(dfq["packet_id"].iloc[0])
            st.session_state["selected_area_label"] = packet_to_area.get(st.session_state["selected_packet_id"])

            with tab_list:
                st.subheader("Areas Needing Review")
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
                    # Fallback for older Streamlit versions: keep a simple dropdown.
                    selected_area = st.selectbox(
                        "Select Area",
                        options=dfq["Area"].astype(str).tolist(),
                        index=int(dfq["Area"].astype(str).tolist().index(st.session_state["selected_area_label"])),
                    )
                    st.session_state["selected_packet_id"] = area_to_packet.get(str(selected_area))
                    st.session_state["selected_area_label"] = str(selected_area)
                    st.dataframe(dfq[show_cols], width="stretch", hide_index=True)

            with tab_map:
                st.subheader("Map View")
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
                        # best-effort infer current mode from stored toggles
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
                    label_by_key = {k: l for (l, k) in mode_options}
                    sel_label = st.selectbox(
                        "Color polygons by",
                        options=[l for (l, _k) in mode_options],
                        index=int([k for (_l, k) in mode_options].index(current)),
                    )
                    sel_key = dict(mode_options)[sel_label]
                    st.session_state["map_color_mode"] = sel_key

                    # Reset all polygon fill overlays, then enable only the chosen one.
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
                        # Enable all three so LayerControl shows them, but they share the same legend section.
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
                        "High-uncertainty threshold (band)",
                        10.0,
                        200.0,
                        float(st.session_state.get("high_uncertainty_threshold", 50.0)),
                        5.0,
                    )
                    st.session_state["max_cells_for_map"] = int(
                        st.number_input(
                            "Max cells to render",
                            min_value=50,
                            max_value=2000,
                            value=int(st.session_state.get("max_cells_for_map", 400)),
                            step=50,
                        )
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
                    st.markdown("### Reviewer decision")
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
                    st.subheader("Audit log (session)")
                    st.dataframe(pd.DataFrame(st.session_state.get("action_log", [])), width="stretch", hide_index=True)


def main():
    client = UrbanPlatformClient(base_path=".")
    use_case_tabs = st.tabs(["Air Pollution", "Heat", "Crowd"])
    with use_case_tabs[0]:
        render_air_pollution_tab(client)
    with use_case_tabs[1]:
        render_heat_tab()
    with use_case_tabs[2]:
        render_crowd_tab(client)


if __name__ == "__main__":
    main()

