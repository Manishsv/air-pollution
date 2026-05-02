from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file

from review_dashboard.ui_shell import (
    render_browse_detail_layout,
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)

from review_dashboard.formatters import (
    evidence_inputs_to_rows,
    humanize_snake_sentence,
    humanize_warning_id,
    provenance_sources_rows,
    safety_gates_to_rows,
)

from urban_platform.connectors.flood.ingest_file import (
    ingest_drainage_asset_feed_json,
    ingest_flood_incident_feed_json,
    ingest_rainfall_observation_feed_json,
)
from urban_platform.processing.flood.features import build_flood_feature_rows
from urban_platform.applications.flood.dashboard_payload import build_flood_risk_dashboard_payload
from urban_platform.applications.flood.decision_packets import build_flood_decision_packets
from urban_platform.applications.flood.field_tasks import build_flood_field_verification_tasks


@dataclass(frozen=True)
class FloodDemoArtifacts:
    rainfall_obs: pd.DataFrame
    incident_events: pd.DataFrame
    drainage_entities: pd.DataFrame
    feature_rows: pd.DataFrame
    dashboard_payload: dict[str, Any]
    decision_packets: list[dict[str, Any]]
    field_tasks: list[dict[str, Any]]


def _ex(path: str) -> Path:
    return (SPEC_ROOT / "examples" / "flood" / path).resolve()


def build_demo_flood_artifacts(*, generated_at: str = "2026-05-01T18:30:00Z", city_id: str = "demo_city") -> FloodDemoArtifacts:
    """
    Build contract-shaped flood artifacts for a demo dashboard panel.

    This is intentionally read-only and uses the existing spec fixtures:
    - provider sample JSON feeds
    - feature scaffolding
    - consumer payload builders
    """
    rainfall_obs, _ = ingest_rainfall_observation_feed_json(json_path=_ex("rainfall_observation.sample.json"))
    incident_events, _ = ingest_flood_incident_feed_json(json_path=_ex("flood_incident.sample.json"))
    drainage_entities, _ = ingest_drainage_asset_feed_json(json_path=_ex("drainage_asset.sample.json"))

    feature_rows, _ = build_flood_feature_rows(
        rainfall_obs=rainfall_obs,
        incident_events=incident_events,
        drainage_entities=drainage_entities,
        generated_at=generated_at,
    )

    dashboard_payload = build_flood_risk_dashboard_payload(feature_rows, generated_at=generated_at, city_id=city_id)
    decision_packets = build_flood_decision_packets(feature_rows, generated_at=generated_at, city_id=city_id)
    field_tasks = build_flood_field_verification_tasks(decision_packets, generated_at=generated_at, assigned_role="ward_engineer")

    return FloodDemoArtifacts(
        rainfall_obs=rainfall_obs,
        incident_events=incident_events,
        drainage_entities=drainage_entities,
        feature_rows=feature_rows,
        dashboard_payload=dashboard_payload,
        decision_packets=decision_packets,
        field_tasks=field_tasks,
    )


def render_flood_panel() -> None:
    render_domain_header(
        title="Flood Risk Review",
        caption=(
            "Read-only situational view built from flood specification fixtures. "
            "Risk labels are conservative placeholders until elevation and drainage models are integrated."
        ),
        primary_alert=(
            "**Decision support only.** This is not an emergency order. Field verification and human protocol "
            "are required before operational response."
        ),
        primary_alert_kind="error",
    )

    artifacts = build_demo_flood_artifacts()

    v_dash = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()))
    v_pkt = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve()))
    v_task = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve()))
    v_dash.validate(artifacts.dashboard_payload)
    for p in artifacts.decision_packets:
        v_pkt.validate(p)
    for t in artifacts.field_tasks:
        v_task.validate(t)

    payload = artifacts.dashboard_payload
    packets = artifacts.decision_packets or []
    tasks = artifacts.field_tasks or []

    rs = payload.get("risk_summary") or {}
    render_context_metrics(
        ("Overall risk (placeholder)", str(rs.get("overall_risk_level") or "—")),
        ("Time window", str(rs.get("time_window") or "—")),
        ("Synthetic data used", str((payload.get("data_quality_summary") or {}).get("synthetic_data_used"))),
        ("Sources", str(len((payload.get("provenance_summary") or {}).get("sources") or []))),
    )

    def _browse() -> None:
        render_section_title("Data quality")
        dqs = payload.get("data_quality_summary") or {}
        st.markdown(f"- **Synthetic data used:** {dqs.get('synthetic_data_used')}")
        if dqs.get("confidence_note"):
            st.markdown(f"- **Confidence note:** {dqs.get('confidence_note')}")

        render_section_title("Active warnings")
        for w in payload.get("active_warnings") or []:
            if not isinstance(w, dict):
                continue
            wid = humanize_warning_id(str(w.get("warning_id") or ""))
            msg = str(w.get("message") or "").strip()
            sev = str(w.get("severity") or "medium").lower()
            line = f"**{wid}** — {msg}" if wid else msg
            if sev == "high":
                st.error(line)
            elif sev == "medium":
                st.warning(line)
            else:
                st.info(line)

        render_section_title("Provenance")
        prov_rows = provenance_sources_rows(payload.get("provenance_summary"))
        if not prov_rows:
            st.info("No sources listed in the provenance summary.")
        else:
            st.dataframe(pd.DataFrame(prov_rows), hide_index=True, use_container_width=True)

        render_section_title("Risk areas (placeholder categories)")
        ra_rows = []
        for a in payload.get("risk_areas") or []:
            if not isinstance(a, dict):
                continue
            unc = a.get("uncertainty") or {}
            ra_rows.append(
                {
                    "Area": str(a.get("area_id") or "—"),
                    "Risk level": str(a.get("risk_level") or "—"),
                    "Confidence score": a.get("confidence_score"),
                    "Uncertainty note": str(unc.get("notes") or ""),
                }
            )
        if not ra_rows:
            st.caption("No risk areas in this payload.")
        else:
            st.dataframe(pd.DataFrame(ra_rows), hide_index=True, use_container_width=True)

        render_section_title("Review queue (candidates)")
        q = payload.get("recommended_review_queue") or []
        if not q:
            st.caption("No review queue entries.")
        else:
            qrows = []
            for item in q:
                if not isinstance(item, dict):
                    continue
                qrows.append(
                    {
                        "Packet ID": str(item.get("packet_id") or ""),
                        "Priority": str(item.get("priority") or ""),
                        "Reason": str(item.get("reason") or ""),
                    }
                )
            st.dataframe(pd.DataFrame(qrows), hide_index=True, use_container_width=True)

    def _detail() -> None:
        render_section_title("Browse queue and drill-down")
        st.caption("Select a packet to inspect evidence, gates, and blocked uses.")

        if not packets:
            st.warning("No decision packets were generated.")
            return

        rows = []
        for p in packets:
            ra = p.get("risk_assessment") or {}
            conf = p.get("confidence") or {}
            rows.append(
                {
                    "Packet ID": str(p.get("packet_id") or ""),
                    "Area": str(p.get("area_id") or p.get("h3_id") or "—"),
                    "Risk level": str(ra.get("risk_level") or "—"),
                    "Field verification required": "Yes" if p.get("field_verification_required") is True else "No",
                    "Recommendation allowed": "Yes" if conf.get("recommendation_allowed") is True else "No",
                    "Recommended action": str(p.get("recommended_action") or "")[:220],
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        ids = [str(p.get("packet_id")) for p in packets if p.get("packet_id")]
        sel = st.selectbox("Select a packet for details", options=ids, index=0, key="flood_selected_packet")
        selected = next((p for p in packets if str(p.get("packet_id")) == sel), None)
        if selected:
            ra = selected.get("risk_assessment") or {}
            st.markdown("#### Risk assessment")
            st.markdown(f"- **Risk level:** {ra.get('risk_level')}")
            st.markdown(f"- **Time window:** {ra.get('time_window')}")
            st.markdown(f"- **Primary driver:** {ra.get('primary_driver')}")

            st.markdown("#### Evidence")
            ev_rows = evidence_inputs_to_rows(selected.get("evidence"))
            if not ev_rows:
                st.caption("No structured evidence rows.")
            else:
                st.dataframe(pd.DataFrame(ev_rows), hide_index=True, use_container_width=True)

            rg = selected.get("review_guidance") or {}
            st.markdown("#### Review prompts")
            for q in rg.get("review_prompts") or []:
                st.markdown(f"- {q}")
            st.markdown("#### When not to act")
            for q in rg.get("when_not_to_act") or []:
                st.markdown(f"- {q}")

            st.markdown("#### Safety gates")
            gdf = pd.DataFrame(safety_gates_to_rows(selected.get("safety_gates")))
            if gdf.empty:
                st.caption("No safety gates listed.")
            else:
                st.dataframe(gdf, hide_index=True, use_container_width=True)

            st.markdown("#### Blocked uses")
            for bu in selected.get("blocked_uses") or []:
                st.markdown(f"- {humanize_snake_sentence(str(bu))}")

            unc = selected.get("uncertainty") or {}
            if unc:
                st.markdown("#### Uncertainty")
                st.markdown(str(unc.get("notes") or unc))

        render_section_title("Field verification tasks")
        if not tasks:
            st.info("No field verification tasks generated yet.")
        else:
            trows = []
            for t in tasks:
                trows.append(
                    {
                        "Task ID": str(t.get("task_id") or ""),
                        "Source packet": str(t.get("source_packet_id") or ""),
                        "Domain": str(t.get("domain_id") or ""),
                        "Priority": str(t.get("priority") or ""),
                        "Status": str(t.get("status") or ""),
                        "Assigned role": str(t.get("assigned_role") or ""),
                        "Created at": str(t.get("created_at") or ""),
                    }
                )
            st.dataframe(pd.DataFrame(trows), hide_index=True, use_container_width=True)

    st.divider()
    render_browse_detail_layout(browse=_browse, detail=_detail)

    render_technical_json_expander(
        title="Technical: Raw contract payload",
        payload={"dashboard_payload": payload, "decision_packets": packets, "field_verification_tasks": tasks},
    )
