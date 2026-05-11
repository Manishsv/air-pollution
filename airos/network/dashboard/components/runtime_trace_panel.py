from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from airos.network.dashboard.ui_shell import (
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

API_LOAD_FAILURE_PREFACE = "Could not load runtime trace from AirOS Core API."

FILE_MODE_GUIDANCE = """Runtime Trace is available when the dashboard is connected to AirOS Core API.

Enable API mode:

```bash
AIROS_DASHBOARD_DATA_MODE=api \\
AIROS_API_BASE_URL=http://127.0.0.1:8000 \\
streamlit run review_dashboard/app.py
```
"""

API_EMPTY_GUIDE_MD = """No runtime trace data was returned yet.

Steps:

1. **Start Core API:**
   ```bash
   AIROS_STORE_DIR=data/store/api uvicorn airos.network.api.app:app --reload --host 127.0.0.1 --port 8000
   ```
2. **POST** records to `/records/{contract_key}`
3. **Run** an allowlisted application via `/applications/{application_id}/runs`
4. Return to this tab and reload.

This is traceability evidence (what ran, what validated, what was stored), not approval evidence.
"""


FetchEndpointFn = Callable[[str, str], Tuple[Optional[List[Any]], Optional[int], Optional[str]]]


@dataclass(frozen=True)
class RuntimeTraceLoadResult:
    mode: str
    api_base_url: Optional[str]
    runs: List[Dict[str, Any]]
    receipts: List[Dict[str, Any]]
    audit_events: List[Dict[str, Any]]
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


def _fetch_endpoint_via_http(
    base_url: str,
    path: str,
    *,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> Tuple[Optional[List[Any]], Optional[int], Optional[str]]:
    """GET {base_url}{path} returning (json_list_or_none, status_or_none, error_message_or_none)."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    url = f"{base_url}{path}"
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
FETCH_ENDPOINT: FetchEndpointFn = _fetch_endpoint_via_http


def load_runtime_trace_data(*, fetch_endpoint: Optional[FetchEndpointFn] = None) -> RuntimeTraceLoadResult:
    mode = _dashboard_data_mode()
    if mode != "api":
        return RuntimeTraceLoadResult(
            mode="file",
            api_base_url=None,
            runs=[],
            receipts=[],
            audit_events=[],
            api_warning=None,
            api_empty_guide=False,
        )

    base = _api_base_url()
    fetch = fetch_endpoint or FETCH_ENDPOINT

    runs_raw, stat_r, err_r = fetch(base, "/runs")
    rec_raw, stat_v, err_v = fetch(base, "/validation-receipts")
    aud_raw, stat_a, err_a = fetch(base, "/audit-events")

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

    _warn_line("Runs", stat_r, err_r)
    _warn_line("Validation receipts", stat_v, err_v)
    _warn_line("Audit events", stat_a, err_a)

    runs = [x for x in (runs_raw or []) if isinstance(x, dict)] if isinstance(runs_raw, list) else []
    receipts = [x for x in (rec_raw or []) if isinstance(x, dict)] if isinstance(rec_raw, list) else []
    audit_events = [x for x in (aud_raw or []) if isinstance(x, dict)] if isinstance(aud_raw, list) else []

    any_ok = (
        (err_r is None and isinstance(stat_r, int) and stat_r < 400)
        or (err_v is None and isinstance(stat_v, int) and stat_v < 400)
        or (err_a is None and isinstance(stat_a, int) and stat_a < 400)
    )
    any_payloads = bool(runs or receipts or audit_events)
    api_empty_guide = bool(any_ok and not any_payloads and not warns)

    api_warning = None
    if warns:
        api_warning = API_LOAD_FAILURE_PREFACE + " " + " | ".join(warns)

    return RuntimeTraceLoadResult(
        mode="api",
        api_base_url=base,
        runs=runs,
        receipts=receipts,
        audit_events=audit_events,
        api_warning=api_warning,
        api_empty_guide=api_empty_guide,
    )


def _count_invalid_receipts(receipts: List[Dict[str, Any]]) -> int:
    n = 0
    for r in receipts:
        if str(r.get("status") or "").lower() == "invalid":
            n += 1
            continue
        try:
            if int(r.get("error_count") or 0) > 0:
                n += 1
        except Exception:
            continue
    return n


def render_runtime_trace_panel() -> None:
    render_domain_header(
        title="Runtime Trace",
        caption="Shows recent AirOS runs, validation receipts, and audit events. This is traceability evidence, not approval evidence.",
        primary_alert=(
            "**Traceability only.** Runs and validation receipts indicate what executed and what validated against schemas. "
            "They do not imply approval, authorization, or any final government decision."
        ),
        primary_alert_kind="info",
    )

    load = load_runtime_trace_data()
    if load.mode != "api":
        render_empty_state(
            "Runtime Trace is available when the dashboard is connected to AirOS Core API.",
            hint="Set AIROS_DASHBOARD_DATA_MODE=api and AIROS_API_BASE_URL, then restart Streamlit.",
        )
        render_technical_json_expander(title="How to enable Runtime Trace (API mode)", payload={"guide": FILE_MODE_GUIDANCE})
        return

    if load.api_warning:
        st.warning(load.api_warning)

    if load.api_empty_guide:
        render_empty_state("No runtime trace data found yet.", hint="Generate at least one run through the Core API, then reload.")
        render_technical_json_expander(title="How to generate runtime trace data", payload={"guide": API_EMPTY_GUIDE_MD})
        return

    invalid_count = _count_invalid_receipts(load.receipts)
    completed_runs = len([r for r in load.runs if str(r.get("status") or "").lower() == "completed"])

    render_context_metrics(
        ("Runs", len(load.runs)),
        ("Validation receipts", len(load.receipts)),
        ("Audit events", len(load.audit_events)),
        ("Failed validations", invalid_count),
        ("Completed runs", completed_runs),
    )

    render_section_title("Recent runs")
    if not load.runs:
        st.caption("No runs returned yet.")
    else:
        rows = []
        for r in load.runs:
            rows.append(
                {
                    "run_id": r.get("run_id"),
                    "application_id": r.get("application_id"),
                    "deployment_id": r.get("deployment_id"),
                    "status": r.get("status"),
                    "started_at": r.get("started_at"),
                    "completed_at": r.get("completed_at"),
                    "records_processed": r.get("records_processed"),
                    "outputs_generated": r.get("outputs_generated"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    render_section_title("Validation receipts")
    if not load.receipts:
        st.caption("No validation receipts returned yet.")
    else:
        rows = []
        for r in load.receipts:
            rows.append(
                {
                    "receipt_id": r.get("receipt_id"),
                    "contract_key": r.get("contract_key"),
                    "validation_target_type": r.get("validation_target_type"),
                    "validation_target_id": r.get("validation_target_id"),
                    "status": r.get("status"),
                    "error_count": r.get("error_count"),
                    "validated_at": r.get("validated_at"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        invalid = [r for r in load.receipts if str(r.get("status") or "").lower() == "invalid" or int(r.get("error_count") or 0) > 0]
        if invalid:
            st.divider()
            render_section_title("Needs attention (invalid validations)")
            st.error(
                "Some payloads failed schema validation. This is not an approval/rejection decision—"
                "it indicates the payload did not match its contract shape and needs correction."
            )
            nrows = []
            for r in invalid[:25]:
                errs = r.get("errors") or []
                first = ""
                if isinstance(errs, list) and errs:
                    first = str(errs[0])[:240]
                nrows.append(
                    {
                        "receipt_id": r.get("receipt_id"),
                        "contract_key": r.get("contract_key"),
                        "target": f"{r.get('validation_target_type')}:{r.get('validation_target_id')}",
                        "errors": first,
                    }
                )
            st.dataframe(pd.DataFrame(nrows), hide_index=True, use_container_width=True)

    render_section_title("Audit events")
    if not load.audit_events:
        st.caption("No audit events returned yet.")
    else:
        rows = []
        for e in load.audit_events[:200]:
            rows.append(
                {
                    "occurred_at": e.get("occurred_at"),
                    "action": e.get("action"),
                    "actor": e.get("actor"),
                    "resource_type": e.get("resource_type"),
                    "resource_id": e.get("resource_id"),
                    "deployment_id": e.get("deployment_id"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.divider()
    render_technical_json_expander(title="Technical: Raw runs", payload=load.runs, expanded=False)
    render_technical_json_expander(title="Technical: Raw validation receipts", payload=load.receipts, expanded=False)
    render_technical_json_expander(title="Technical: Raw audit events", payload=load.audit_events, expanded=False)

