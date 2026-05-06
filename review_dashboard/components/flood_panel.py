from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from urban_platform.specifications.conformance import SPEC_ROOT, validator_for_schema_file

from review_dashboard.ui_shell import (
    render_browse_detail_layout,
    render_context_metrics,
    render_domain_header,
    render_empty_state,
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


ENV_DASHBOARD_DATA_MODE = "AIROS_DASHBOARD_DATA_MODE"
ENV_API_BASE_URL = "AIROS_API_BASE_URL"

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
HTTP_TIMEOUT_SECONDS = 3.0

API_LOAD_FAILURE_PREFACE = "Could not load Flood data from AirOS Core API."

API_EMPTY_GUIDE_MD = """**API mode** is enabled, but no Flood outputs were returned from the Core API yet.

Steps:

1. **Start Core API:**
   ```bash
   AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
   ```

2. **POST** Flood fixture records (example sequence):
   - `{base}/records/provider_rainfall_observation_feed?deployment_id=flood_local_demo`
   - `{base}/records/provider_flood_incident_feed?deployment_id=flood_local_demo`
   - `{base}/records/provider_drainage_asset_feed?deployment_id=flood_local_demo`

3. **Run** `{base}/applications/flood_risk_dashboard_payload/runs` with `{"deployment_id":"flood_local_demo"}`

Then reload this page.
"""


FetchOutputsFn = Callable[[str, str], Tuple[Optional[List[Any]], Optional[int], Optional[str]]]


@dataclass(frozen=True)
class FloodDemoArtifacts:
    rainfall_obs: pd.DataFrame
    incident_events: pd.DataFrame
    drainage_entities: pd.DataFrame
    feature_rows: pd.DataFrame
    dashboard_payload: dict[str, Any]
    decision_packets: list[dict[str, Any]]
    field_tasks: list[dict[str, Any]]


@dataclass(frozen=True)
class FloodDashboardLoadResult:
    mode: str
    dashboard_payload: Optional[Dict[str, Any]]
    decision_packets: List[Dict[str, Any]]
    field_tasks: List[Dict[str, Any]]
    api_base_url: Optional[str]
    api_warning: Optional[str]
    api_empty_guide: bool


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


def _dashboard_data_mode() -> str:
    raw = os.environ.get(ENV_DASHBOARD_DATA_MODE, "").strip().lower()
    if not raw:
        return "file"
    return raw


def _api_base_url() -> str:
    raw = os.environ.get(ENV_API_BASE_URL, "").strip()
    if not raw:
        return DEFAULT_API_BASE_URL
    return raw.rstrip("/")


def normalize_output_item_to_payload(item: Any) -> Optional[Dict[str, Any]]:
    """
    `/outputs` may return StoredOutput-shaped dicts (`payload` nested) or raw payloads.

    - If nested ``payload`` is a dict, return it (unwrap StoredOutput serialization).
    - If the dict looks like a StoredOutput envelope without usable payload (has ``output_id`` /
      ``contract_key``), skip.
    - Otherwise return the dict itself.
    """
    if not isinstance(item, dict):
        return None
    inner = item.get("payload")
    if isinstance(inner, dict):
        return dict(inner)
    if item.get("output_id") is not None or item.get("contract_key") is not None:
        return None
    return dict(item)


def pick_latest_dashboard_payload(rows: Sequence[Any]) -> Optional[Dict[str, Any]]:
    keyed: List[Tuple[str, Dict[str, Any]]] = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        ga_outer = it["generated_at"] if isinstance(it.get("generated_at"), str) else ""
        cand = normalize_output_item_to_payload(it)
        if cand is None:
            continue
        gv = cand.get("generated_at")
        ga_inner = gv if isinstance(gv, str) else ""
        ga = ga_outer or ga_inner
        if cand.get("risk_summary") is not None and cand.get("risk_areas") is not None:
            keyed.append((ga, cand))
    if not keyed:
        return None
    keyed.sort(key=lambda x: x[0])
    return keyed[-1][1]


def normalize_outputs_to_packets(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in rows:
        md = normalize_output_item_to_payload(it)
        if md is None:
            continue
        if md.get("packet_id") or (md.get("risk_assessment") is not None and md.get("area_id") is not None):
            out.append(md)
    return out


def normalize_outputs_to_tasks(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in rows:
        md = normalize_output_item_to_payload(it)
        if md is None:
            continue
        if md.get("task_id") or md.get("source_packet_id"):
            out.append(md)
    return out


def _fetch_outputs_via_http(
    base_url: str,
    contract_key: str,
    *,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
    """GET /outputs?contract_key=... returning (json_list_or_none, status_or_none, error_message_or_none)."""
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    safe_ck = quote(str(contract_key), safe="")
    url = f"{base_url}/outputs?contract_key={safe_ck}"
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return None, status, "Invalid JSON in response."
            if isinstance(data, list):
                return data, status, None
            return None, status, "Response JSON was not an array."
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:800]
        except Exception:  # noqa: BLE001
            body = ""
        return None, int(e.code), body or str(e.reason)
    except URLError as e:
        reason = getattr(e, "reason", e)
        return None, None, str(reason)


# Test seam: patched in unit tests instead of hitting the network.
FETCH_OUTPUTS: FetchOutputsFn = _fetch_outputs_via_http


def load_flood_dashboard_data(*, fetch_outputs: Optional[FetchOutputsFn] = None) -> FloodDashboardLoadResult:
    mode = _dashboard_data_mode()
    if mode != "api":
        artifacts = build_demo_flood_artifacts()
        return FloodDashboardLoadResult(
            mode="file",
            dashboard_payload=dict(artifacts.dashboard_payload),
            decision_packets=list(artifacts.decision_packets or []),
            field_tasks=list(artifacts.field_tasks or []),
            api_base_url=None,
            api_warning=None,
            api_empty_guide=False,
        )

    base = _api_base_url()
    fetch = fetch_outputs or FETCH_OUTPUTS
    dash_raw, stat_d, err_d = fetch(base, "consumer_flood_risk_dashboard")
    pkt_raw, stat_p, err_p = fetch(base, "consumer_flood_decision_packet")
    task_raw, stat_t, err_t = fetch(base, "consumer_field_verification_task")

    warns: List[str] = []

    def _warn_line(label: str, status: Optional[int], err_msg: Optional[str]) -> None:
        if err_msg:
            suf = err_msg.strip()
            if status is not None:
                warns.append(f"{label}: HTTP {status} — {suf}")
            else:
                warns.append(f"{label}: {suf}")
        elif isinstance(status, int) and status >= 400:
            warns.append(f"{label}: HTTP {status}")

    _warn_line("Dashboard payload outputs", stat_d, err_d)
    _warn_line("Decision packet outputs", stat_p, err_p)
    _warn_line("Field task outputs", stat_t, err_t)

    dash_payload = pick_latest_dashboard_payload(dash_raw or []) if isinstance(dash_raw, list) else None
    packets = normalize_outputs_to_packets(pkt_raw or []) if isinstance(pkt_raw, list) else []
    tasks = normalize_outputs_to_tasks(task_raw or []) if isinstance(task_raw, list) else []

    any_ok = (
        (err_d is None and isinstance(stat_d, int) and stat_d < 400)
        or (err_p is None and isinstance(stat_p, int) and stat_p < 400)
        or (err_t is None and isinstance(stat_t, int) and stat_t < 400)
    )
    any_payloads = bool(dash_payload or packets or tasks)
    api_empty_guide = bool(any_ok and not any_payloads and not warns)

    api_warning = None
    if warns:
        api_warning = API_LOAD_FAILURE_PREFACE + " " + " | ".join(warns)

    return FloodDashboardLoadResult(
        mode="api",
        dashboard_payload=dash_payload,
        decision_packets=packets,
        field_tasks=tasks,
        api_base_url=base,
        api_warning=api_warning,
        api_empty_guide=api_empty_guide,
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

    v_dash = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_risk_dashboard.v1.schema.json").resolve()))
    v_pkt = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "flood_decision_packet.v1.schema.json").resolve()))
    v_task = validator_for_schema_file(str((SPEC_ROOT / "consumer_contracts" / "field_verification_task.v1.schema.json").resolve()))
    load = load_flood_dashboard_data()

    if load.mode == "api" and load.api_warning:
        st.warning(load.api_warning)

    if load.mode == "api" and load.api_empty_guide:
        base = load.api_base_url or DEFAULT_API_BASE_URL
        render_empty_state(
            "API mode is enabled, but no Flood outputs were found yet.",
            hint="Generate Flood outputs via the Core API, then reload this page.",
        )
        render_technical_json_expander(
            title="How to generate Flood outputs (API mode)",
            payload={"guide": API_EMPTY_GUIDE_MD.format(base=base)},
            expanded=False,
        )
        return

    payload = load.dashboard_payload or {}
    packets = load.decision_packets or []
    tasks = load.field_tasks or []

    # Validate if present; do not crash the panel on empty API states.
    if payload:
        v_dash.validate(payload)
    for p in packets:
        v_pkt.validate(p)
    for t in tasks:
        v_task.validate(t)

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

        tab_list, tab_map = st.tabs(["List View", "Map View"])

        with tab_list:
            render_section_title("Risk areas (review queue)")
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

            render_section_title("Recommended review queue (candidates)")
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

        with tab_map:
            render_section_title("Map View (placeholder)")
            st.info("Map view is not implemented in this flood demo panel yet. Use List View for review.")

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
