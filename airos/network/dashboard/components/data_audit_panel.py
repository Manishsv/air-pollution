"""Data Audit panel — shows open audit issues from H3DataAuditor.

Reads from the audit_issues table in the SQLite knowledge store.
Issues are written by:  python main.py --step audit --cities <city>
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from airos.drivers.store.schema import DB_PATH
from airos.network.dashboard.ui_shell import render_section_title

_SEV_ICON = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
_SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEV_COLOR = {"error": "#ff4b4b", "warning": "#ffa500", "info": "#4b9eff"}


def _load_issues(city_id: str) -> pd.DataFrame:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        df = pd.read_sql_query(
            """
            SELECT issue_id, domain, check_name, severity, message,
                   detail_json, detected_at, resolved_at
            FROM audit_issues
            WHERE city_id = ?
            ORDER BY
                CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                detected_at DESC
            """,
            conn, params=(city_id,),
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def _last_run_at(city_id: str) -> str | None:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT MAX(detected_at) FROM audit_issues WHERE city_id = ?",
            (city_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _age_label(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        minutes = int((datetime.now(timezone.utc) - t).total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except Exception:
        return ts


def render_data_audit_panel(city_id: str = "bangalore") -> None:
    all_issues = _load_issues(city_id)
    open_issues = all_issues[all_issues["resolved_at"].isna()] if not all_issues.empty else pd.DataFrame()
    resolved   = all_issues[all_issues["resolved_at"].notna()] if not all_issues.empty else pd.DataFrame()

    last_run = _last_run_at(city_id)

    # ── Header row ────────────────────────────────────────────────────────
    header_col, btn_col = st.columns([6, 1])
    with header_col:
        render_section_title("Data Audit")
    with btn_col:
        run_audit = st.button("▶ Run", key="run_audit_btn",
                              help="Run data auditor now (may take ~10s)")

    if run_audit:
        with st.spinner("Running audit …"):
            try:
                from airos.os.auditor.h3_auditor import H3DataAuditor
                H3DataAuditor().run([city_id])
                st.success("Audit complete — refreshing …")
                st.rerun()
            except Exception as exc:
                st.error(f"Audit failed: {exc}")
        return

    # ── Summary metrics ───────────────────────────────────────────────────
    n_errors   = int((open_issues["severity"] == "error").sum())   if not open_issues.empty else 0
    n_warnings = int((open_issues["severity"] == "warning").sum()) if not open_issues.empty else 0
    n_info     = int((open_issues["severity"] == "info").sum())    if not open_issues.empty else 0
    n_resolved = len(resolved)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Errors",    n_errors,   delta=None)
    c2.metric("Warnings",  n_warnings, delta=None)
    c3.metric("Info",      n_info,     delta=None)
    c4.metric("Resolved",  n_resolved, delta=None)
    c5.metric("Last run",  _age_label(last_run))

    if open_issues.empty:
        st.success("No open issues — all checks passed.")
        if not resolved.empty:
            with st.expander(f"Resolved issues ({n_resolved})", expanded=False):
                _render_issue_table(resolved, show_resolved=True)
        return

    # ── Domain breakdown ──────────────────────────────────────────────────
    render_section_title("Open issues by domain")
    domain_summary = (
        open_issues.groupby(["domain", "severity"])
        .size()
        .reset_index(name="count")
    )

    domains = open_issues["domain"].unique().tolist()
    domains.sort()
    if "" in domains:
        domains.remove("")
        domains.insert(0, "")

    for domain in domains:
        dom_issues = open_issues[open_issues["domain"] == domain]
        n_e = int((dom_issues["severity"] == "error").sum())
        n_w = int((dom_issues["severity"] == "warning").sum())
        badge_parts = []
        if n_e:
            badge_parts.append(f"❌ {n_e}")
        if n_w:
            badge_parts.append(f"⚠️ {n_w}")
        label = domain if domain else "(system)"
        badge = "  ".join(badge_parts)
        with st.expander(f"**{label}** — {badge}", expanded=(n_e > 0)):
            _render_issue_table(dom_issues)

    # ── Resolved history ──────────────────────────────────────────────────
    if not resolved.empty:
        with st.expander(f"Resolved issues ({n_resolved})", expanded=False):
            _render_issue_table(resolved, show_resolved=True)

    st.caption(
        "Run `python main.py --step audit --cities <city>` to refresh, "
        "or click **▶ Run** above."
    )


def _render_issue_table(df: pd.DataFrame, show_resolved: bool = False) -> None:
    for _, row in df.iterrows():
        sev = row["severity"]
        icon = _SEV_ICON.get(sev, "•")
        check = row["check_name"].replace("_", " ")
        msg = row["message"]
        detected = _age_label(row.get("detected_at"))

        col_icon, col_body, col_age = st.columns([0.5, 8, 1.5])
        with col_icon:
            st.markdown(f"<div style='padding-top:4px;font-size:16px'>{icon}</div>",
                        unsafe_allow_html=True)
        with col_body:
            st.markdown(
                f"<div style='font-size:13px;line-height:1.4'>"
                f"<span style='color:#888;font-size:11px'>{check}</span><br>"
                f"{msg}"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_age:
            if show_resolved and pd.notna(row.get("resolved_at")):
                st.caption(f"✅ {_age_label(row['resolved_at'])}")
            else:
                st.caption(detected)

        # Detail expander
        detail_raw = row.get("detail_json")
        if detail_raw:
            try:
                detail = json.loads(detail_raw)
                if detail:
                    with st.expander("detail", expanded=False):
                        st.json(detail)
            except Exception:
                pass
