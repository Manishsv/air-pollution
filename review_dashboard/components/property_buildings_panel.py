from __future__ import annotations

import json
from dataclasses import dataclass
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
    humanize_internal_flag,
    humanize_snake_sentence,
    humanize_warning_id,
    provenance_sources_rows,
    safety_gates_to_rows,
)

from urban_platform.processing.property_buildings.features import build_property_buildings_feature_rows
from urban_platform.applications.property_buildings.dashboard_payload import (
    build_property_building_dashboard_payload,
)
from urban_platform.applications.property_buildings.review_packets import (
    build_property_building_review_packets,
)
from urban_platform.applications.property_buildings.field_tasks import (
    build_property_buildings_field_verification_tasks,
)


@dataclass(frozen=True)
class PropertyBuildingsDemoArtifacts:
    feature_rows: pd.DataFrame
    dashboard_payload: dict[str, Any]
    review_packets: list[dict[str, Any]]
    field_tasks: list[dict[str, Any]]


def _fixture_demo_row(*, fixture_name: str, area_id: str) -> dict[str, Any]:
    path = (SPEC_ROOT / "examples" / "property_buildings" / fixture_name).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "ward_id": area_id,
        "source": str(data.get("provider_id") or "fixture"),
        "provenance": {"license": str(data.get("license") or "demo_only"), "synthetic": True},
    }


def build_demo_property_buildings_artifacts(
    *,
    generated_at: str = "2026-05-01T18:30:00Z",
    area_id: str = "ward_12",
) -> PropertyBuildingsDemoArtifacts:
    """
    Build contract-shaped property/buildings artifacts for a read-only demo panel.

    Uses spec fixtures only (no live connectors). Verification-first; no matching.
    """
    feature_rows, _ = build_property_buildings_feature_rows(
        property_registry=pd.DataFrame([_fixture_demo_row(fixture_name="property_registry.sample.json", area_id=area_id)]),
        building_footprints=pd.DataFrame([_fixture_demo_row(fixture_name="building_footprint.sample.json", area_id=area_id)]),
        building_permits=pd.DataFrame([_fixture_demo_row(fixture_name="building_permit.sample.json", area_id=area_id)]),
        land_use=pd.DataFrame([_fixture_demo_row(fixture_name="land_use.sample.json", area_id=area_id)]),
        generated_at=generated_at,
    )

    dashboard_payload = build_property_building_dashboard_payload(
        feature_rows, generated_at=generated_at, area_id=area_id
    )
    review_packets = build_property_building_review_packets(
        feature_rows, generated_at=generated_at, area_id=area_id
    )
    field_tasks = build_property_buildings_field_verification_tasks(
        review_packets, generated_at=generated_at, assigned_role="field_inspector"
    )

    return PropertyBuildingsDemoArtifacts(
        feature_rows=feature_rows,
        dashboard_payload=dashboard_payload,
        review_packets=review_packets,
        field_tasks=field_tasks,
    )


def _collect_feature_warning_flags(feature_rows: pd.DataFrame) -> list[str]:
    flags: list[str] = []
    if feature_rows is None or feature_rows.empty or "warning_flags" not in feature_rows.columns:
        return flags
    seen: set[str] = set()
    for wf in feature_rows["warning_flags"].tolist():
        items: list[str] = []
        if isinstance(wf, list):
            items = [str(x) for x in wf if x]
        elif isinstance(wf, str) and wf:
            items = [wf]
        for it in items:
            if it not in seen:
                seen.add(it)
                flags.append(it)
    return flags


def _aggregate_blocked_uses(packets: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in packets or []:
        for bu in p.get("blocked_uses") or []:
            s = str(bu).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def render_property_buildings_panel() -> None:
    render_domain_header(
        title="Property & Buildings Review",
        caption=(
            "Verification-first review of property registry, building footprint, permit, and land-use signals. "
            "This tab uses specification fixtures for local demonstration."
        ),
        primary_alert=(
            "**Outputs are review candidates only.** They are not tax assessments, penalties, demolition orders, "
            "or enforcement actions."
        ),
        primary_alert_kind="error",
    )

    artifacts = build_demo_property_buildings_artifacts()

    v_dash = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "property_building_dashboard.v1.schema.json").resolve())
    )
    v_pkt = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "property_building_review_packet.v1.schema.json").resolve())
    )
    v_task = validator_for_schema_file(
        str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve())
    )
    v_dash.validate(artifacts.dashboard_payload)
    for p in artifacts.review_packets:
        v_pkt.validate(p)
    for t in artifacts.field_tasks:
        v_task.validate(t)

    payload = artifacts.dashboard_payload
    packets = artifacts.review_packets or []
    tasks = artifacts.field_tasks or []

    cov = payload.get("coverage_summary") or {}
    render_context_metrics(
        ("Property registry records", int(cov.get("property_registry_records") or 0)),
        ("Building footprint records", int(cov.get("building_footprint_records") or 0)),
        ("Building permit records", int(cov.get("building_permit_records") or 0)),
        ("Land-use records", int(cov.get("land_use_records") or 0)),
    )

    def _browse() -> None:
        render_section_title("Data quality and safety")
        dqs = payload.get("data_quality_summary") or {}
        synthetic = bool(dqs.get("synthetic_data_used"))
        st.markdown(f"- **Synthetic or demo data used:** {'Yes' if synthetic else 'No'}")

        rec_allowed_any = any(bool((p.get("confidence") or {}).get("recommendation_allowed")) for p in packets)
        st.markdown(f"- **Automated recommendation allowed:** {'Yes' if rec_allowed_any else 'No'}")

        st.markdown("**Active warnings**")
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

        ff = _collect_feature_warning_flags(artifacts.feature_rows)
        if ff:
            st.markdown("**Scaffolding flags**")
            for f in ff:
                st.markdown(f"- {humanize_internal_flag(f)}")

        blocked = _aggregate_blocked_uses(packets)
        if blocked:
            st.markdown("**Blocked uses (from review packets)**")
            for b in blocked:
                st.markdown(f"- {humanize_snake_sentence(b)}")

        render_section_title("Mismatch and review readiness")
        ms = payload.get("mismatch_summary") or {}
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Total candidates", int(ms.get("total_candidates") or 0))
        with m2:
            st.metric("High priority", int(ms.get("high_priority") or 0))
        with m3:
            st.metric("Matching status", "Not implemented")
        st.info(
            "**Matching is not implemented yet.** This dashboard currently verifies **data readiness**, "
            "**coverage**, and **provenance** only. It does not assert mismatches between registry, footprints, "
            "permits, or land use."
        )
        if ms.get("notes"):
            st.caption(str(ms.get("notes")))

        render_section_title("Provenance")
        prov_rows = provenance_sources_rows(payload.get("provenance_summary"))
        if not prov_rows:
            st.info("No sources listed in the provenance summary yet.")
        else:
            st.dataframe(pd.DataFrame(prov_rows), hide_index=True, use_container_width=True)

        render_section_title("Map layers and review candidates")
        candidates = payload.get("review_candidates") or []
        if not candidates:
            st.info(
                "No review candidates are shown because **matching is not implemented yet**. "
                "Candidates will appear once parcel ↔ footprint ↔ permit ↔ land-use alignment exists under specification."
            )
        else:
            st.dataframe(pd.DataFrame(candidates), hide_index=True, use_container_width=True)

        layers = payload.get("map_layers") or []
        if not layers:
            st.info("No map layers are available in this payload.")
        else:
            st.caption("Map layers are contract placeholders until spatial matching and styling are implemented.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Layer": str(L.get("title") or L.get("layer_id") or "—"),
                            "Layer ID": str(L.get("layer_id") or ""),
                            "Type": str(L.get("layer_type") or ""),
                        }
                        for L in layers
                        if isinstance(L, dict)
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )

    def _detail() -> None:
        render_section_title("Browse queue and drill-down")
        st.caption("Select a review packet to inspect evidence, prompts, gates, and blocked uses.")

        if not packets:
            st.warning("No review packets were generated.")
        else:
            rows = []
            for p in packets:
                conf = p.get("confidence") or {}
                area = str(p.get("area_id") or p.get("property_id") or p.get("parcel_id") or p.get("building_id") or "—")
                rows.append(
                    {
                        "Packet ID": str(p.get("packet_id") or ""),
                        "Area": area,
                        "Issue type": str(p.get("issue_type") or "—"),
                        "Field verification required": "Yes" if p.get("field_verification_required") is True else "No",
                        "Recommendation allowed": "Yes" if conf.get("recommendation_allowed") is True else "No",
                        "Recommended review action": str(p.get("recommended_review_action") or "")[:200],
                    }
                )
            df_pkt = pd.DataFrame(rows)
            st.dataframe(df_pkt, hide_index=True, use_container_width=True)

            ids = [str(p.get("packet_id")) for p in packets if p.get("packet_id")]
            sel = st.selectbox("Select a packet for details", options=ids, index=0, key="pb_selected_packet")
            selected = next((p for p in packets if str(p.get("packet_id")) == sel), None)
            if selected:
                st.markdown("#### Evidence")
                ev_rows = evidence_inputs_to_rows(selected.get("evidence"))
                if not ev_rows:
                    st.caption("No structured evidence rows.")
                else:
                    st.dataframe(pd.DataFrame(ev_rows), hide_index=True, use_container_width=True)

                rg = selected.get("review_guidance") or {}
                prompts = rg.get("review_prompts") or []
                wna = rg.get("when_not_to_act") or []
                st.markdown("#### Review prompts")
                if isinstance(prompts, list) and prompts:
                    for q in prompts:
                        st.markdown(f"- {q}")
                else:
                    st.caption("None.")

                st.markdown("#### When not to act")
                if isinstance(wna, list) and wna:
                    for q in wna:
                        st.markdown(f"- {q}")
                else:
                    st.caption("None.")

                st.markdown("#### Safety gates")
                gdf = pd.DataFrame(safety_gates_to_rows(selected.get("safety_gates")))
                if gdf.empty:
                    st.caption("No safety gates listed.")
                else:
                    st.dataframe(gdf, hide_index=True, use_container_width=True)

                st.markdown("#### Blocked uses (this packet)")
                for bu in selected.get("blocked_uses") or []:
                    st.markdown(f"- {humanize_snake_sentence(str(bu))}")

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
        payload={
            "dashboard_payload": payload,
            "review_packets": packets,
            "field_verification_tasks": tasks,
        },
    )
