from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from review_dashboard.ui_shell import (
    render_browse_detail_layout,
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
        title="Program Reporting & Fund Release Review",
        caption="Review city-reported program progress and financial utilization for the selected reporting period.",
        primary_alert=(
            "**Review support only.** AirOS supports review only. It does not authorize fund release."
        ),
        primary_alert_kind="warning",
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

    # Summary metrics + executive cards
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

    # Compact city cards (mobile-friendly quick scan)
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

    # Financial progress
    render_section_title("Financial progress")
    fin_rows = summary.get("city_financial_rows") or []
    fin_df = pd.DataFrame(fin_rows) if isinstance(fin_rows, list) else pd.DataFrame()
    if not fin_df.empty:
        show = ["city_id", "amount_approved", "amount_released", "amount_spent", "utilization_pct", "fund_release_review_status"]
        show = [c for c in show if c in fin_df.columns]
        if show:
            fin_df = fin_df[show]
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

    # Program progress
    render_section_title("Program progress")
    prog_rows = summary.get("city_progress_rows") or []
    prog_df = pd.DataFrame(prog_rows) if isinstance(prog_rows, list) else pd.DataFrame()
    if not prog_df.empty:
        prog_df["Flags"] = prog_df.get("flags").apply(
            lambda xs: ", ".join([str(x) for x in xs]) if isinstance(xs, list) else ""
        )
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

    # Needs attention
    render_section_title("Needs attention")
    flagged = summary.get("flagged_cities") or []
    if isinstance(flagged, list) and flagged:
        st.dataframe(pd.DataFrame(flagged), hide_index=True, use_container_width=True)
    else:
        st.caption("No flagged cities in this summary.")

    # Action items
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

    # Do not use this dashboard for
    render_section_title("Do not use this dashboard for")
    blocked = summary.get("blocked_uses")
    if not isinstance(blocked, list) or not blocked:
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

    # Technical details (collapsed)
    render_technical_json_expander(title="Technical details: state_program_summary.json", payload=summary, expanded=False)
    render_technical_json_expander(title="Technical details: fund_release_review_packets.json", payload=packets, expanded=False)

