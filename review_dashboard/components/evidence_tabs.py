from __future__ import annotations

import pandas as pd
import streamlit as st


def _df(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records) if records else pd.DataFrame()


def _kv(label: str, value) -> None:
    st.markdown(f"**{label}**  \n{value if value not in [None, ''] else '—'}")


def render_evidence_tabs(packet: dict, *, reliability_df: pd.DataFrame | None = None):
    pred = packet.get("prediction") or {}
    prov = packet.get("provenance") or {}
    ev = packet.get("evidence") or {}
    audit = packet.get("audit_context") or {}
    src_rel = packet.get("source_reliability_summary") or {}
    prov_sum = packet.get("provenance_summary") or {}

    tabs = st.tabs(["Forecast", "Data Sources", "Nearby Sensors", "Weather", "Area Characteristics", "Recent Conditions", "Sensor Reliability", "Technical Details", "Review Checklist"])

    with tabs[0]:
        _kv("Forecast PM2.5 (mean)", pred.get("forecast_pm25_mean"))
        _kv("Category", pred.get("pm25_category_india"))
        _kv("Forecast range (P10 / P50 / P90)", f"{pred.get('forecast_pm25_p10')} / {pred.get('forecast_pm25_p50')} / {pred.get('forecast_pm25_p90')}")
        _kv("Uncertainty band", pred.get("uncertainty_band"))
        mvp = audit.get("model_vs_persistence_summary")
        if mvp:
            st.info(str(mvp))

    with tabs[1]:
        st.markdown("**Run-level provenance summary**")
        if prov_sum:
            st.dataframe(_df([prov_sum]), width="stretch", hide_index=True)
        st.markdown("**Area-level data sources**")
        _kv("Air-quality data type", prov.get("aq_source_type"))
        _kv("Weather data type", prov.get("weather_source_type"))
        _kv("Interpolation method", prov.get("interpolation_method"))
        _kv("Nearest sensor distance (km)", prov.get("nearest_station_distance_km"))
        _kv("Sensors used for estimate", prov.get("station_count_used"))
        wf = prov.get("warning_flags")
        if wf:
            st.warning(str(wf))

    with tabs[2]:
        note = ev.get("nearby_station_note", "")
        if note:
            st.info(note)
        st.dataframe(_df(ev.get("nearby_station_records") or []), width="stretch")

    with tabs[3]:
        st.dataframe(_df(ev.get("weather_records") or []), width="stretch")

    with tabs[4]:
        st.dataframe(_df(ev.get("static_features") or []), width="stretch")

    with tabs[5]:
        st.dataframe(_df(ev.get("dynamic_features") or []), width="stretch")

    with tabs[6]:
        if src_rel:
            st.markdown("**Summary (from this run)**")
            st.dataframe(_df([src_rel]), width="stretch", hide_index=True)
        if reliability_df is None or reliability_df.empty:
            st.info("No source reliability data available.")
        else:
            cols = [
                "entity_id",
                "variable",
                "status",
                "reliability_score",
                "completeness_ratio",
                "stale_hours",
                "flatline_detected",
                "impossible_value_detected",
                "spike_detected",
                "peer_disagreement_score",
                "reliability_issues",
            ]
            show = reliability_df.copy()
            keep = [c for c in cols if c in show.columns]
            st.dataframe(show[keep].sort_values(["status", "reliability_score"], ascending=[True, True]), width="stretch", hide_index=True)

    with tabs[7]:
        with st.expander("Technical identifiers", expanded=False):
            st.write(
                {
                    "packet_id": packet.get("packet_id"),
                    "event_id": packet.get("event_id"),
                    "h3_id": packet.get("h3_id"),
                    "timestamp": packet.get("timestamp"),
                }
            )

        with st.expander("Raw review record", expanded=False):
            st.json(packet)

    with tabs[8]:
        rg = packet.get("review_guidance") or {}
        if not rg:
            st.info("No review checklist available.")
        else:
            qs = rg.get("questions_to_ask") or []
            if qs:
                st.markdown("**Questions to ask**")
                for q in qs:
                    st.write(f"- {q}")
            steps = rg.get("verification_steps") or []
            if steps:
                st.markdown("**Verification steps**")
                for s in steps:
                    st.write(f"- {s}")
            dna = rg.get("do_not_act_if") or []
            if dna:
                st.markdown("**Do not act if**")
                for d in dna:
                    st.write(f"- {d}")

