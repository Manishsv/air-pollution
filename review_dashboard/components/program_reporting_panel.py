from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_empty_state,
    render_section_title,
    render_technical_json_expander,
)


_DEMO_WARNINGS: list[str] = [
    "fixture/demo data only",
    "review support only",
    "no automatic fund release",
    "authorized finance process required",
]


@dataclass(frozen=True)
class ProgramReportingDemoOutputs:
    output_dir: Path
    state_summary: dict[str, Any] | None
    review_packets: list[dict[str, Any]]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_program_reporting_demo_outputs(
    *,
    base_output_dir: Path | None = None,
) -> ProgramReportingDemoOutputs | None:
    """
    Read fixture demo outputs from data/outputs/deployments/program_reporting_state_demo.

    - Prefers state_program_summary.json + fund_release_review_packets.json
    - Falls back to single fund_release_review_packet.json
    """
    root = base_output_dir or (Path("data") / "outputs" / "deployments" / "program_reporting_state_demo")
    out_dir = root.resolve()
    if not out_dir.exists():
        return None

    state_summary: dict[str, Any] | None = None
    packets: list[dict[str, Any]] = []

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

    return ProgramReportingDemoOutputs(output_dir=out_dir, state_summary=state_summary, review_packets=packets)


def render_program_reporting_panel() -> None:
    render_domain_header(
        title="Program Reporting and Fund Release Review",
        caption="Read-only Phase 1 fixture demo: multi-city monitoring summary + per-city review packets.",
        primary_alert=(
            "**Review support only.** This panel never authorizes fund release, penalties, or public disclosure. "
            "An authorized finance process outside AirOS remains required."
        ),
        primary_alert_kind="error",
    )

    demo = load_program_reporting_demo_outputs()
    if demo is None:
        render_empty_state(
            "Program Reporting demo outputs not found.",
            hint="Run: python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo",
        )
        return

    summary = demo.state_summary or {}
    packets = demo.review_packets or []

    warnings = summary.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        warnings = list(_DEMO_WARNINGS)

    render_section_title("Safety warnings (always-on for this demo)")
    for w in warnings:
        st.warning(str(w))

    # Summary metrics
    program_id = str(summary.get("program_id") or (packets[0].get("program_id") if packets else "—") or "—")
    reporting_period = str(summary.get("reporting_period") or (packets[0].get("reporting_period") if packets else "—") or "—")
    city_count = int(summary.get("city_count") or len(packets) or 0)
    generated_at = str(summary.get("generated_at") or "—")

    render_context_metrics(
        ("program_id", program_id),
        ("reporting_period", reporting_period),
        ("city_count", city_count),
        ("generated_at", generated_at),
    )

    render_section_title("Counts")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**review_status_counts**")
        st.json(summary.get("review_status_counts") or {})
    with c2:
        st.markdown("**fund_release_review_status_counts**")
        st.json(summary.get("fund_release_review_status_counts") or {})

    render_section_title("Queues")
    st.markdown("**cities_ready_for_authorized_review**")
    st.write(summary.get("cities_ready_for_authorized_review") or [])
    st.markdown("**cities_needing_clarification**")
    st.write(summary.get("cities_needing_clarification") or [])

    render_section_title("Flagged cities")
    flagged = summary.get("flagged_cities") or []
    if isinstance(flagged, list) and flagged:
        st.dataframe(pd.DataFrame(flagged), hide_index=True, use_container_width=True)
    else:
        st.caption("No flagged cities in this summary.")

    render_section_title("Review packets")
    rows = []
    for p in packets:
        rows.append(
            {
                "city_id": p.get("city_id"),
                "review_status": p.get("review_status"),
                "fund_release_review_status": p.get("fund_release_review_status"),
                "flags": ", ".join([str(x) for x in (p.get("flags") or [])]),
                "confidence": p.get("confidence"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No review packets found.")

    render_section_title("Blocked uses")
    blocked = summary.get("blocked_uses")
    if not isinstance(blocked, list) or not blocked:
        # fallback: union from packets
        seen: set[str] = set()
        blocked = []
        for p in packets:
            for bu in p.get("blocked_uses") or []:
                s = str(bu).strip()
                if s and s not in seen:
                    seen.add(s)
                    blocked.append(s)
    for b in blocked:
        st.markdown(f"- {b}")

    render_technical_json_expander(title="Technical: state_program_summary.json", payload=summary, expanded=False)
    render_technical_json_expander(title="Technical: fund_release_review_packets.json", payload=packets, expanded=False)

