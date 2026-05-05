from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_empty_state,
    render_section_title,
    render_technical_json_expander,
)

ENV_DASHBOARD_DATA_MODE = "AIROS_DASHBOARD_DATA_MODE"
ENV_API_BASE_URL = "AIROS_API_BASE_URL"

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
HTTP_TIMEOUT_SECONDS = 3.0

API_LOAD_FAILURE_PREFACE = "Could not load Program Reporting data from AirOS Core API."

API_EMPTY_GUIDE_MD = """**API mode** is enabled, but no Program Reporting outputs were returned from the Core API yet.

Steps:

1. **Start Core API:**
   ```bash
   AIROS_STORE_DIR=data/store/api uvicorn urban_platform.api.app:app --reload --host 127.0.0.1 --port 8000
   ```

2. **POST** both city submission fixtures to `{base}/records/consumer_city_program_submission`

3. **Run** `{base}/applications/program_reporting_review_packet/runs` with deployment/program/period JSON

Then reload this page.
"""


FetchOutputsFn = Callable[[str, str], Tuple[Optional[List[Any]], Optional[int], Optional[str]]]


@dataclass(frozen=True)
class ProgramReportingDemoOutputs:
    """Normalized payload for dashboard rendering (file or API)."""

    output_dir: Optional[Path]
    state_summary: Optional[Dict[str, Any]]
    review_packets: List[Dict[str, Any]]
    data_source: str = "file"
    api_base_url: Optional[str] = None


@dataclass(frozen=True)
class ProgramReportingDashboardLoadResult:
    mode: str
    outputs: Optional[ProgramReportingDemoOutputs]
    api_warning: Optional[str]
    api_empty_guide: bool


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_output_item_to_payload(item: Any) -> Optional[Dict[str, Any]]:
    """
    `/outputs` may return StoredOutput-shaped dicts (`payload` nested) or raw payloads.

    - If nested ``payload`` is a dict, return it (unwrap StoredOutput serialization).
    - If the dict looks like a StoredOutput envelope without usable payload (has ``output_id`` /
      ``contract_key``), skip.
    - Otherwise return the dict itself (bare review packet / state summary payloads).
    """
    if not isinstance(item, dict):
        return None
    inner = item.get("payload")
    if isinstance(inner, dict):
        return dict(inner)
    if item.get("output_id") is not None or item.get("contract_key") is not None:
        return None
    return dict(item)


def normalize_outputs_to_review_packets(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    packets: List[Dict[str, Any]] = []
    for it in rows:
        md = normalize_output_item_to_payload(it)
        if md is None:
            continue
        if md.get("city_financial_rows") is not None and md.get("packet_id") is None:
            continue
        if md.get("packet_id") or md.get("submission_id"):
            packets.append(md)
        elif md.get("city_id") is not None and (
            md.get("review_status") is not None or md.get("fund_release_review_status") is not None
        ):
            packets.append(md)
    return packets


def pick_latest_state_summary(rows: Sequence[Any]) -> Optional[Dict[str, Any]]:
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
        if cand.get("city_financial_rows") is not None or cand.get("city_count") is not None:
            keyed.append((ga, cand))
    if not keyed:
        return None
    keyed.sort(key=lambda x: x[0])
    return keyed[-1][1]


def _fetch_outputs_via_http(base_url: str, contract_key: str, *, timeout: float = HTTP_TIMEOUT_SECONDS) -> Tuple[
    Optional[List[Any]], Optional[int], Optional[str]
]:
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


def load_program_reporting_demo_outputs(*, base_output_dir: Optional[Path] = None) -> Optional[ProgramReportingDemoOutputs]:
    """
    Read fixture demo outputs from data/outputs/deployments/program_reporting_state_demo.

    - Prefers state_program_summary.json + fund_release_review_packets.json
    - Falls back to single fund_release_review_packet.json
    """
    root = base_output_dir or (Path("data") / "outputs" / "deployments" / "program_reporting_state_demo")
    out_dir = root.resolve()
    if not out_dir.exists():
        return None

    state_summary: Optional[Dict[str, Any]] = None
    packets: List[Dict[str, Any]] = []

    p_state = out_dir / "state_program_summary.json"
    if p_state.is_file():
        raw = _read_json(p_state)
        if isinstance(raw, dict):
            state_summary = raw

    p_plural = out_dir / "fund_release_review_packets.json"
    if p_plural.is_file():
        raw = _read_json(p_plural)
        if isinstance(raw, list):
            packets = [x for x in raw if isinstance(x, dict)]

    if not packets:
        p_single = out_dir / "fund_release_review_packet.json"
        if p_single.is_file():
            raw = _read_json(p_single)
            if isinstance(raw, dict):
                packets = [raw]

    if not state_summary and not packets:
        return None

    return ProgramReportingDemoOutputs(
        output_dir=out_dir,
        state_summary=state_summary,
        review_packets=packets,
        data_source="file",
    )


def load_program_reporting_dashboard_data(
    *,
    base_output_dir: Optional[Path] = None,
    fetch_outputs: Optional[FetchOutputsFn] = None,
) -> ProgramReportingDashboardLoadResult:
    mode = _dashboard_data_mode()
    if mode != "api":
        demo = load_program_reporting_demo_outputs(base_output_dir=base_output_dir)
        return ProgramReportingDashboardLoadResult(
            mode="file",
            outputs=demo,
            api_warning=None,
            api_empty_guide=False,
        )

    base = _api_base_url()
    fetch = fetch_outputs or FETCH_OUTPUTS
    summaries_raw, stat_s, err_s = fetch(base, "internal_program_reporting_state_summary_demo")
    packets_raw, stat_p, err_p = fetch(base, "consumer_fund_release_review_packet")

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

    _warn_line("State summary outputs", stat_s, err_s)
    _warn_line("Review packet outputs", stat_p, err_p)

    if err_s or err_p or (stat_s is not None and stat_s >= 400) or (stat_p is not None and stat_p >= 400):
        combined = "; ".join(warns) if warns else "Unknown HTTP error."
        return ProgramReportingDashboardLoadResult(
            mode="api",
            outputs=None,
            api_warning=f"{API_LOAD_FAILURE_PREFACE} ({combined})",
            api_empty_guide=True,
        )

    summary_list = summaries_raw if isinstance(summaries_raw, list) else []
    packet_list = packets_raw if isinstance(packets_raw, list) else []

    state_summary = pick_latest_state_summary(summary_list)
    review_packets = normalize_outputs_to_review_packets(packet_list)

    if not state_summary and not review_packets:
        return ProgramReportingDashboardLoadResult(
            mode="api",
            outputs=None,
            api_warning=None,
            api_empty_guide=True,
        )

    demo = ProgramReportingDemoOutputs(
        output_dir=None,
        state_summary=state_summary,
        review_packets=review_packets,
        data_source="api",
        api_base_url=base,
    )
    return ProgramReportingDashboardLoadResult(mode="api", outputs=demo, api_warning=None, api_empty_guide=False)


def render_program_reporting_panel() -> None:
    render_domain_header(
        title="Program Reporting & Fund Release Review",
        caption="Review city-reported program progress and financial utilization for the selected reporting period.",
        primary_alert=(
            "**Review support only.** AirOS supports review only. It does not authorize fund release."
        ),
        primary_alert_kind="warning",
    )

    load = load_program_reporting_dashboard_data()
    if load.api_warning:
        st.warning(load.api_warning)

    demo = load.outputs
    empty_api = load.api_empty_guide and load.mode == "api"

    if demo is None or (demo.state_summary is None and not demo.review_packets):
        if empty_api:
            guide = API_EMPTY_GUIDE_MD.format(base=_api_base_url())
            render_empty_state(
                "Program Reporting (API mode): no outputs were found from the Core API.",
                hint=None,
            )
            st.markdown(guide)
        else:
            render_empty_state(
                "Program Reporting demo outputs not found.",
                hint="Run: python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo",
            )
        return

    summary = demo.state_summary or {}
    packets = demo.review_packets or []

    if demo.data_source == "api":
        src = demo.api_base_url or _api_base_url()
        st.caption(f"**Data source:** Core API ({src})")

    program_id = str(summary.get("program_id") or (packets[0].get("program_id") if packets else "—") or "—")
    reporting_period = str(
        summary.get("reporting_period") or (packets[0].get("reporting_period") if packets else "—") or "—"
    )
    generated_at = str(summary.get("generated_at") or "—")
    city_count = int(summary.get("city_count") or len(packets) or 0)
    ready = summary.get("cities_ready_for_authorized_review") or []
    needs = summary.get("cities_needing_clarification") or []
    financial_totals = summary.get("financial_totals") or {}

    amount_released_total = float(financial_totals.get("amount_released_total") or 0.0)
    amount_spent_total = float(financial_totals.get("amount_spent_total") or 0.0)
    utilization_total = float(financial_totals.get("utilization_pct") or 0.0)

    render_context_metrics(
        ("Cities reported", city_count),
        ("Ready for authorized review", len(ready) if isinstance(ready, list) else 0),
        ("Needs clarification", len(needs) if isinstance(needs, list) else 0),
        ("Total amount released", f"{amount_released_total:,.0f}"),
        ("Total amount spent", f"{amount_spent_total:,.0f}"),
        ("Overall utilization", f"{utilization_total:.1f}%"),
    )
    st.caption(f"Program: `{program_id}` · Reporting period: `{reporting_period}` · Generated at: {generated_at}")

    render_section_title("Cities (quick scan)")
    card_rows = []
    for p in packets:
        card_rows.append(
            {
                "City": str(p.get("city_id") or "—"),
                "Review status": str(p.get("review_status") or "—"),
                "Financial review status": str(p.get("fund_release_review_status") or "—"),
                "Flags": ", ".join([str(x) for x in (p.get("flags") or [])]),
                "Confidence": p.get("confidence"),
            }
        )
    cdf = pd.DataFrame(card_rows)
    if not cdf.empty:
        st.dataframe(cdf, hide_index=True, use_container_width=True)
    else:
        st.caption("No city packets found.")

    render_section_title("Financial progress")
    fin_rows = summary.get("city_financial_rows") or []
    fin_df = pd.DataFrame(fin_rows) if isinstance(fin_rows, list) else pd.DataFrame()
    if not fin_df.empty:
        show_cols = ["city_id", "amount_approved", "amount_released", "amount_spent", "utilization_pct", "fund_release_review_status"]
        show_cols = [c for c in show_cols if c in fin_df.columns]
        if show_cols:
            fin_df = fin_df[show_cols]
        fin_df = fin_df.rename(
            columns={
                "city_id": "City",
                "amount_approved": "Approved",
                "amount_released": "Released",
                "amount_spent": "Spent",
                "utilization_pct": "Utilization",
                "fund_release_review_status": "Review status",
            }
        )
        st.dataframe(fin_df, hide_index=True, use_container_width=True)
    else:
        st.info("No financial progress rows available in this summary.")

    render_section_title("Program progress")
    prog_rows = summary.get("city_progress_rows") or []
    prog_df = pd.DataFrame(prog_rows) if isinstance(prog_rows, list) else pd.DataFrame()
    if not prog_df.empty:
        if "flags" in prog_df.columns:

            def _fmt_flags(xs: Any) -> str:
                return ", ".join([str(x) for x in xs]) if isinstance(xs, list) else ""

            prog_df = prog_df.copy()
            prog_df["Flags"] = prog_df["flags"].apply(_fmt_flags)
        else:
            prog_df = prog_df.copy()
            prog_df["Flags"] = ""
        show = [
            "city_id",
            "projects_total",
            "projects_completed",
            "projects_in_progress",
            "projects_delayed",
            "overall_progress_pct",
            "Flags",
        ]
        show = [c for c in show if c in prog_df.columns]
        prog_df = prog_df[show].rename(
            columns={
                "city_id": "City",
                "projects_total": "Total projects",
                "projects_completed": "Completed",
                "projects_in_progress": "In progress",
                "projects_delayed": "Delayed",
                "overall_progress_pct": "Progress %",
            }
        )
        st.dataframe(prog_df, hide_index=True, use_container_width=True)
    else:
        st.info("No program progress rows available in this summary.")

    render_section_title("Needs attention")
    flagged = summary.get("flagged_cities") or []
    if isinstance(flagged, list) and flagged:
        st.dataframe(pd.DataFrame(flagged), hide_index=True, use_container_width=True)
    else:
        st.caption("No flagged cities in this summary.")

    render_section_title("Action items")
    actions = summary.get("action_items") or []
    act_df = pd.DataFrame(actions) if isinstance(actions, list) else pd.DataFrame()
    if not act_df.empty:
        show = ["action_label", "responsible_role", "city_id", "status", "reason"]
        show = [c for c in show if c in act_df.columns]
        act_df = act_df[show].rename(
            columns={
                "action_label": "Action",
                "responsible_role": "Responsible role",
                "city_id": "City",
                "status": "Status",
                "reason": "Reason",
            }
        )
        st.dataframe(act_df, hide_index=True, use_container_width=True)
    else:
        st.caption("No action items generated.")

    render_section_title("Do not use this dashboard for")
    blocked = summary.get("blocked_uses")
    if not isinstance(blocked, list) or not blocked:
        seen: set[str] = set()
        blocked_list: List[str] = []
        for p in packets:
            for bu in p.get("blocked_uses") or []:
                s = str(bu).strip()
                if s and s not in seen:
                    seen.add(s)
                    blocked_list.append(s)
        blocked = blocked_list
    for b in blocked:
        st.markdown(f"- {b}")

    tech_summary_title = (
        "Technical details: Core API payloads (normalized state summary)"
        if demo.data_source == "api"
        else "Technical details: state_program_summary.json"
    )
    tech_packets_title = (
        "Technical details: Core API payloads (normalized review packets)"
        if demo.data_source == "api"
        else "Technical details: fund_release_review_packets.json"
    )
    render_technical_json_expander(title=tech_summary_title, payload=summary, expanded=False)
    render_technical_json_expander(title=tech_packets_title, payload=packets, expanded=False)
