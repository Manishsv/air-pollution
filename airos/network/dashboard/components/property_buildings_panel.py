from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from airos.os.specifications.conformance import SPEC_ROOT, validator_for_schema_file

from airos.network.dashboard.ui_shell import (
    render_browse_detail_layout,
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)

from airos.network.dashboard.formatters import (
    evidence_inputs_to_rows,
    humanize_internal_flag,
    humanize_snake_sentence,
    humanize_warning_id,
    provenance_sources_rows,
    safety_gates_to_rows,
)

from airos.drivers.processing.property_buildings.features import build_property_buildings_feature_rows
from airos.apps.property_buildings.dashboard_payload import (
    build_property_building_dashboard_payload,
)
from airos.apps.property_buildings.review_packets import (
    build_property_building_review_packets,
)
from airos.apps.property_buildings.field_tasks import (
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


def _coverage_records_loaded(cov: dict[str, Any]) -> int:
    vals = [
        int(cov.get("property_registry_records") or 0),
        int(cov.get("building_footprint_records") or 0),
        int(cov.get("building_permit_records") or 0),
        int(cov.get("land_use_records") or 0),
    ]
    return sum(max(0, v) for v in vals)


def _field_task_rows(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in tasks or []:
        rows.append(
            {
                "Task": str(t.get("task_id") or "—"),
                "Priority": str(t.get("priority") or "—"),
                "Status": str(t.get("status") or "—"),
                "Assigned role": str(t.get("assigned_role") or "—"),
                "Purpose": str(t.get("purpose") or t.get("task_type") or "Data verification"),
            }
        )
    return rows


def render_property_buildings_panel() -> None:
    render_domain_header(
        title="Property & Buildings Review",
        caption=(
            "Review possible property/building data gaps using registry, footprint, permit, and land-use records. "
            "This demo supports verification planning only."
        ),
        primary_alert=(
            "Review support only. Do not use this dashboard to issue tax demands, penalties, demolition notices, or enforcement actions."
        ),
        primary_alert_kind="error",
        domain="buildings",
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
    candidates = payload.get("review_candidates") or []
    demo_status = "Demo / fixture data"
    records_loaded = _coverage_records_loaded(cov if isinstance(cov, dict) else {})

    render_context_metrics(
        ("Source records loaded", records_loaded),
        ("Review candidates", len(candidates) if isinstance(candidates, list) else 0),
        ("Field verification tasks", len(tasks)),
        ("Demo status", demo_status),
    )

    def _browse() -> None:
        # Progressive disclosure: keep the first screen short.
        dqs = payload.get("data_quality_summary") or {}
        data_mode = "Demo / fixture" if bool(dqs.get("synthetic_data_used")) else "Unknown"

        matching_note = "Matching between parcels, footprints, permits, and land use is not active in this demo."

        render_section_title("Main review status")
        st.info("**No review candidates yet**")
        st.markdown(f"- **Reason:** {matching_note}")
        st.markdown(
            "- **Next step:** review source coverage and the generated field verification task. Do not treat this as proof of non-compliance."
        )

        render_section_title("Needs attention")
        st.markdown("- Matching logic is not active in this demo.")
        st.markdown(f"- Data mode: **{data_mode}**")
        st.markdown("- No review candidates have been generated.")
        st.markdown("- Enforcement and tax actions are blocked.")

        render_section_title("Next human review step")
        st.markdown("1. Confirm source coverage (registry, footprints, permits, land use).")
        st.markdown("2. Review the generated field verification task for verification planning.")
        st.markdown("3. If needed, rerun after matching is implemented in a future phase.")

        render_section_title("Do not use this dashboard for")
        st.markdown("- Automatic tax reassessment")
        st.markdown("- Penalties or enforcement")
        st.markdown("- Demolition notices")
        st.markdown("- Treating mismatch as proof of non-compliance")
        st.markdown("- Publishing sensitive property details")

    def _detail() -> None:
        render_section_title("Field verification tasks")
        if not tasks:
            st.info("No field verification tasks generated yet.")
        else:
            st.caption("This task is for data verification only. It is not an enforcement task.")
            st.dataframe(pd.DataFrame(_field_task_rows(tasks)), hide_index=True, use_container_width=True)

        # Supporting details (collapsed by default)
        with st.expander("Source data coverage", expanded=False):
            cov_rows = [
                {"Source": "Property registry records", "Records loaded": int(cov.get("property_registry_records") or 0)},
                {"Source": "Building footprint records", "Records loaded": int(cov.get("building_footprint_records") or 0)},
                {"Source": "Building permit records", "Records loaded": int(cov.get("building_permit_records") or 0)},
                {"Source": "Land-use records", "Records loaded": int(cov.get("land_use_records") or 0)},
            ]
            st.dataframe(pd.DataFrame(cov_rows), hide_index=True, use_container_width=True)

        with st.expander("Source information", expanded=False):
            prov_rows = provenance_sources_rows(payload.get("provenance_summary"))
            if prov_rows:
                st.dataframe(pd.DataFrame(prov_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No sources listed in the provenance summary yet.")

        with st.expander("Source data coverage (what AirOS used)", expanded=False):
            ev_rows = evidence_inputs_to_rows(payload.get("evidence_inputs"))
            if ev_rows:
                st.dataframe(pd.DataFrame(ev_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No structured evidence inputs listed in this payload.")

        with st.expander("Review safeguards / safety gates", expanded=False):
            if packets and (packets[0].get("safety_gates") or []):
                gdf = pd.DataFrame(safety_gates_to_rows(packets[0].get("safety_gates")))
                st.dataframe(gdf, hide_index=True, use_container_width=True)
            else:
                st.caption("No safety gates listed in the sample review packet.")

        render_technical_json_expander(title="Technical: raw review packet", payload=(packets[0] if packets else {}), expanded=False)
        render_technical_json_expander(title="Technical: source provenance", payload=(payload.get("provenance_summary") or {}), expanded=False)
        render_technical_json_expander(
            title="Technical: contract payload",
            payload={
                "dashboard_payload": payload,
                "review_packets": packets,
                "field_verification_tasks": tasks,
            },
            expanded=False,
        )

    # Avoid fixed two-pane layout when there are no candidates (mobile-friendly).
    if not isinstance(candidates, list) or not candidates:
        _browse()
        st.divider()
        _detail()
    else:
        st.divider()
        render_browse_detail_layout(browse=_browse, detail=_detail)
