from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file

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


def _render_warnings(payload: dict[str, Any]) -> None:
    warns = payload.get("active_warnings") or []
    if not warns:
        return
    for w in warns:
        wid = str((w or {}).get("warning_id") or "warning")
        sev = str((w or {}).get("severity") or "medium").lower()
        msg = str((w or {}).get("message") or "")
        if sev == "high":
            st.error(f"{wid}: {msg}")
        elif sev == "medium":
            st.warning(f"{wid}: {msg}")
        else:
            st.info(f"{wid}: {msg}")


def render_flood_panel() -> None:
    st.subheader("Flood (read-only MVP)")
    st.caption("Decision support only. Verification-first. No operational orders are generated here.")

    artifacts = build_demo_flood_artifacts()

    # Validate payloads at render-time (developer-facing; safe and fast for fixtures).
    v_dash = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()))
    v_pkt = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve()))
    v_task = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve()))
    v_dash.validate(artifacts.dashboard_payload)
    for p in artifacts.decision_packets:
        v_pkt.validate(p)
    for t in artifacts.field_tasks:
        v_task.validate(t)

    payload = artifacts.dashboard_payload

    _render_warnings(payload)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Overall risk (placeholder)", str((payload.get("risk_summary") or {}).get("overall_risk_level") or "—"))
    with c2:
        st.metric("Synthetic data used", str((payload.get("data_quality_summary") or {}).get("synthetic_data_used")))
    with c3:
        st.metric("Sources", str(len((payload.get("provenance_summary") or {}).get("sources") or [])))

    st.markdown("### Risk summary")
    st.json(payload.get("risk_summary") or {})

    st.markdown("### Data quality summary")
    st.json(payload.get("data_quality_summary") or {})

    st.markdown("### Provenance summary")
    st.json(payload.get("provenance_summary") or {})

    st.markdown("### Review queue (candidates)")
    st.dataframe(pd.DataFrame(payload.get("recommended_review_queue") or []), hide_index=True, use_container_width=True)

    st.markdown("### Risk areas")
    st.dataframe(pd.DataFrame(payload.get("risk_areas") or []), hide_index=True, use_container_width=True)

    st.markdown("### Decision packets (contract-shaped)")
    st.json(artifacts.decision_packets)

    st.markdown("### Field verification tasks (contract-shaped)")
    st.dataframe(pd.DataFrame(artifacts.field_tasks), hide_index=True, use_container_width=True)

