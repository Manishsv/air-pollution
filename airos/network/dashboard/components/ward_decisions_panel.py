"""Ward engineer decision support panel.

Surfaces active climate decisions for each ward — sorted by urgency — with
source attribution and recommended action. Implements the ward-level view
from docs/architecture/WARD_DECISION_CATALOGUE.md.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import streamlit as st

from airos.network.dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from airos.os.city_config import CITIES as _CITY_REGISTRY, PANEL_CITIES

# Ward decisions uses the legacy place module which expects a "_demo" suffix.
_PLACE_ID: dict[str, str] = {k: f"{k}_demo" for k in _CITY_REGISTRY}

_URGENCY_COLOR = {
    "immediate":  "#dc3545",
    "within_4h":  "#fd7e14",
    "within_24h": "#ffc107",
    "plan":       "#6c757d",
}

_URGENCY_LABEL = {
    "immediate":  "🔴 Immediate",
    "within_4h":  "🟠 Within 4h",
    "within_24h": "🟡 Within 24h",
    "plan":       "⚪ Plan",
}

_DOMAIN_COLOR = {
    "Air Quality":   "#0d6efd",
    "Flood":         "#0dcaf0",
    "Heat":          "#fd7e14",
    "Cross-Domain":  "#6f42c1",
}


_OUTCOME_LABEL = {
    "pending":    "⏳ Pending",
    "dispatched": "🚗 Dispatched",
    "verified":   "🔍 Verified",
    "resolved":   "✅ Resolved",
}

_OUTCOME_NEXT: dict[str, list[str]] = {
    "pending":    ["dispatched"],
    "dispatched": ["verified"],
    "verified":   ["resolved"],
    "resolved":   [],
}

_URGENCY_SORT = {"immediate": 0, "within_4h": 1, "within_24h": 2, "within_week": 3}


# ── Task data helpers ─────────────────────────────────────────────────────────

def _load_tasks(city_id: str, status_filter: str = "open") -> list[dict]:
    """Load insight-derived packets from h3_packets."""
    from airos.drivers.store.schema import DB_PATH
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        if status_filter == "open":
            where = "outcome_status != 'resolved'"
        elif status_filter == "resolved":
            where = "outcome_status = 'resolved'"
        else:
            where = "1=1"
        rows = conn.execute(f"""
            SELECT packet_id, h3_id, domain, risk_level, confidence_score,
                   outcome_status, created_at, packet_json, evidence_json
            FROM h3_packets
            WHERE city_id = ?
              AND json_extract(packet_json, '$.source') = 'insight'
              AND {where}
            ORDER BY
                CASE risk_level
                    WHEN 'severe' THEN 0 WHEN 'high' THEN 1
                    WHEN 'moderate' THEN 2 ELSE 3 END,
                created_at DESC
        """, (city_id,)).fetchall()
        conn.close()
        tasks = []
        for r in rows:
            payload = {}
            try:
                payload = json.loads(r["packet_json"] or "{}")
            except Exception:
                pass
            tasks.append({
                "packet_id":       r["packet_id"],
                "h3_id":           r["h3_id"],
                "domain":          r["domain"],
                "risk_level":      r["risk_level"],
                "confidence":      r["confidence_score"],
                "outcome_status":  r["outcome_status"],
                "created_at":      r["created_at"],
                "finding":         payload.get("finding", ""),
                "urgency":         payload.get("urgency", "within_24h"),
                "domains_involved": payload.get("domains_involved", r["domain"]),
                "actions":         payload.get("recommended_actions", []),
                "priority_tier":   payload.get("priority_tier", "medium"),
                "cause_hypotheses": payload.get("cause_hypotheses", []),
                "primary_cause":   payload.get("primary_cause", ""),
                "routed_to":       payload.get("routed_to", ""),
                "routing_cc":      payload.get("routing_cc", []),
                "routing_action":  payload.get("routing_action", ""),
            })
        tasks.sort(key=lambda t: (
            _URGENCY_SORT.get(t["urgency"], 9),
            {"severe": 0, "high": 1, "moderate": 2, "low": 3}.get(t["risk_level"], 4),
        ))
        return tasks
    except Exception as exc:
        st.error(f"Error loading tasks: {exc}")
        return []


def _advance_task(task: dict, new_status: str, officer: str, city_id: str) -> None:
    """Update packet outcome_status; write h3_outcomes + close source insight on resolve."""
    from airos.drivers.store.writer import update_packet_outcome, write_outcome
    packet_id = task["packet_id"]
    try:
        update_packet_outcome(packet_id=packet_id, outcome_status=new_status)
    except Exception:
        pass
    if new_status == "resolved":
        try:
            write_outcome(
                packet_id=packet_id,
                h3_id=task["h3_id"],
                city_id=city_id,
                domain=task["domain"],
                outcome_type="resolved",
                finding=f"Marked resolved by {officer}",
                resolved_by=officer,
            )
        except Exception:
            pass
        # Close the source insight so it stops re-promoting
        try:
            from airos.drivers.store.schema import DB_PATH
            conn = sqlite3.connect(str(DB_PATH))
            row = conn.execute(
                "SELECT json_extract(packet_json, '$.source_insight_id') "
                "FROM h3_packets WHERE packet_id = ?", (packet_id,)
            ).fetchone()
            conn.close()
            if row and row[0]:
                from airos.drivers.store.writer import close_insight
                close_insight(
                    insight_id=row[0],
                    outcome_status="confirmed",
                    closed_by=officer,
                )
        except Exception:
            pass


# ── Task rendering ────────────────────────────────────────────────────────────

def _render_tasks_panel(city_id: str) -> None:
    """Render the insight-derived tasks tab."""
    col_filter, col_refresh = st.columns([4, 1])
    with col_filter:
        status_filter = st.radio(
            "Show", ["open", "resolved", "all"],
            horizontal=True, key="tasks_status_filter",
            label_visibility="collapsed",
        )
    with col_refresh:
        if st.button("↻", key="tasks_refresh", help="Refresh tasks"):
            st.rerun()

    tasks = _load_tasks(city_id, status_filter)

    # Summary strip
    n_immediate = sum(1 for t in tasks if t["urgency"] == "immediate")
    n_4h        = sum(1 for t in tasks if t["urgency"] == "within_4h")
    n_pending   = sum(1 for t in tasks if t["outcome_status"] == "pending")
    n_progress  = sum(1 for t in tasks if t["outcome_status"] in ("dispatched", "verified"))
    n_resolved  = sum(1 for t in tasks if t["outcome_status"] == "resolved")

    mc = st.columns(5)
    mc[0].metric("Immediate", n_immediate)
    mc[1].metric("Within 4h",  n_4h)
    mc[2].metric("Pending",    n_pending)
    mc[3].metric("In Progress", n_progress)
    mc[4].metric("Resolved",   n_resolved)

    if not tasks:
        st.info("No tasks match the current filter.")
        return

    officer = st.text_input(
        "Officer ID (required to advance status)",
        key="tasks_officer_id",
        placeholder="e.g. ward_officer_42",
    )

    st.divider()

    for task in tasks:
        urgency    = task["urgency"]
        risk       = task["risk_level"]
        status     = task["outcome_status"]
        domains    = task["domains_involved"]
        urgency_lbl = _URGENCY_LABEL.get(urgency, urgency)
        status_lbl  = _OUTCOME_LABEL.get(status, status)
        risk_icon   = {"severe": "🔴", "high": "🟠", "moderate": "🟡", "low": "🟢"}.get(risk, "⚪")

        header = (
            f"{risk_icon} **{domains}** — {urgency_lbl} — {status_lbl}"
        )

        with st.expander(header, expanded=(urgency in ("immediate", "within_4h") and status == "pending")):
            st.write(task["finding"])

            # Cause hypotheses + routing (air domain)
            hyps = task.get("cause_hypotheses", [])
            routed_to = task.get("routed_to", "")
            routing_action = task.get("routing_action", "")
            routing_cc = task.get("routing_cc", [])
            if hyps or routed_to:
                st.markdown("**Cause analysis & routing:**")
                if routed_to:
                    cc_str = f" · CC: {', '.join(routing_cc)}" if routing_cc else ""
                    st.markdown(f"→ **{routed_to}**{cc_str}")
                    if routing_action:
                        st.markdown(f"  *{routing_action}*")
                if hyps:
                    cols = st.columns(min(len(hyps), 3))
                    for i, h in enumerate(hyps[:3]):
                        cause_label = h["cause"].replace("_", " ").title()
                        conf_pct = int(h["confidence"] * 100)
                        badge_color = (
                            "#dc3545" if conf_pct >= 60 else
                            "#fd7e14" if conf_pct >= 35 else "#6c757d"
                        )
                        cols[i].markdown(
                            f'<span style="background:{badge_color};color:white;'
                            f'padding:2px 8px;border-radius:4px;font-size:11px">'
                            f'{cause_label} {conf_pct}%</span>',
                            unsafe_allow_html=True,
                        )
                        for ev in h.get("evidence", [])[:2]:
                            cols[i].caption(ev)

            if task["actions"]:
                st.markdown("**Recommended actions:**")
                for a in task["actions"][:3]:
                    actor   = a.get("actor", "")
                    action  = a.get("action", "")
                    blocked = a.get("blocked_if", "")
                    st.markdown(
                        f"- `{actor}` — {action}"
                        + (f"  \n  *Blocked if: {blocked}*" if blocked else ""),
                    )

            conf_str = f" · Confidence: {task['confidence']:.0%}" if task["confidence"] else ""
            st.caption(f"Cell: `{task['h3_id']}`{conf_str}")

            # Advance-status buttons
            next_statuses = _OUTCOME_NEXT.get(status, [])
            if next_statuses:
                btn_cols = st.columns(len(next_statuses) + 1)
                for i, ns in enumerate(next_statuses):
                    label_map = {
                        "dispatched": "✅ Mark Dispatched",
                        "verified":   "🔍 Mark Verified",
                        "resolved":   "✅ Mark Resolved",
                    }
                    if btn_cols[i].button(
                        label_map.get(ns, f"→ {ns}"),
                        key=f"task_btn_{task['packet_id']}_{ns}",
                    ):
                        if not officer:
                            st.warning("Enter your Officer ID above before advancing status.")
                        else:
                            _advance_task(task, ns, officer, city_id)
                            st.success(f"Marked as {ns}.")
                            st.rerun()


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_decisions(city_id: str) -> tuple[list[dict], object | None]:
    # Translate canonical city_id → place-module ID (which uses "_demo" suffix).
    place_id = _PLACE_ID.get(city_id, f"{city_id}_demo")
    try:
        from airos.drivers.place import aggregate_city_wards
        from airos.drivers.place.ward_decisions import generate_ward_decisions
        result = aggregate_city_wards(place_id)
        if result is None or result.wards_df.empty:
            return [], result
        return generate_ward_decisions(result), result
    except Exception as exc:
        st.error(f"Error loading ward decisions: {exc}")
        return [], None


# ── Urgency badge HTML ────────────────────────────────────────────────────────

def _urgency_badge(urgency: str) -> str:
    color = _URGENCY_COLOR.get(urgency, "#6c757d")
    label = _URGENCY_LABEL.get(urgency, urgency)
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:600">{label}</span>'
    )


# ── Summary metrics ───────────────────────────────────────────────────────────

def _render_summary(packets: list[dict]) -> None:
    total      = len(packets)
    immediate  = sum(1 for p in packets if p["urgency"] == "immediate")
    within_4h  = sum(1 for p in packets if p["urgency"] == "within_4h")
    escalate   = sum(1 for p in packets if p.get("escalation_required"))
    xd         = sum(1 for p in packets if p["domain"] == "cross_domain")

    render_context_metrics(
        ("Open decisions",    str(total)),
        ("Immediate",         str(immediate)),
        ("Within 4h",         str(within_4h)),
        ("Needs escalation",  str(escalate)),
        ("Cross-domain",      str(xd)),
    )


# ── Decision table ─────────────────────────────────────────────────────────────

def _fmt_score(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.2f}"


def _render_decisions_table(packets: list[dict], domain_filter: str, urgency_filter: str) -> None:
    render_section_title("Open decisions — ward engineer view")

    filtered = [
        p for p in packets
        if (domain_filter == "All" or p["domain"] == domain_filter.lower().replace(" ", "_") or
            _DOMAIN_LABELS_INV.get(domain_filter, domain_filter) == p["domain"])
        and (urgency_filter == "All" or p["urgency"] == urgency_filter)
    ]

    if not filtered:
        st.info("No decisions match the current filters.")
        return

    for p in filtered:
        sig    = p.get("signal", {})
        urg    = p["urgency"]
        color  = _URGENCY_COLOR.get(urg, "#6c757d")
        domain = p["domain"]
        dom_label = {"air": "Air Quality", "flood": "Flood", "heat": "Heat", "cross_domain": "Cross-Domain"}.get(domain, domain)
        dom_color = _DOMAIN_COLOR.get(dom_label, "#6c757d")

        escalate_html = (
            '<span style="color:#dc3545;font-size:11px">⬆ Escalate to '
            + (p.get("escalate_to") or "") + "</span>"
            if p.get("escalation_required") else ""
        )
        header = (
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:2px">'
            f'<span style="background:{dom_color};color:white;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">{dom_label}</span>'
            f'{_urgency_badge(urg)}'
            f'<span style="font-weight:600;font-size:14px">{p.get("ward_name", "")}</span>'
            f'<span style="color:#6c757d;font-size:12px">{p["decision_id"]}</span>'
            f'{escalate_html}'
            f'</div>'
        )
        st.markdown(header, unsafe_allow_html=True)

        with st.expander("Action & evidence", expanded=(urg == "immediate")):
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("**Likely cause**")
                st.caption(sig.get("attribution_plain", sig.get("source_attribution", "—")))
                st.markdown("**Recommended action**")
                st.info(p.get("recommended_action", "—"))
            with c2:
                scores = {
                    "AQI score":    _fmt_score(sig.get("avg_aqi_score")),
                    "Flood risk":   _fmt_score(sig.get("avg_flood_risk")),
                    "Heat risk":    _fmt_score(sig.get("avg_heat_risk")),
                    "Composite":    _fmt_score(sig.get("composite_risk")),
                    "Confidence":   sig.get("attribution_confidence", "—"),
                }
                for k, v in scores.items():
                    if v != "—":
                        st.markdown(f"**{k}:** {v}")
                ev = p.get("evidence", {})
                if ev.get("cell_count"):
                    st.markdown(f"**H3 cells:** {ev['cell_count']}  |  **Multi-risk:** {ev.get('multi_risk_cells', 0)}")
        st.divider()


_DOMAIN_LABELS_INV = {
    "Air Quality":  "air",
    "Flood":        "flood",
    "Heat":         "heat",
    "Cross-Domain": "cross_domain",
}


# ── By-ward summary ───────────────────────────────────────────────────────────

def _render_ward_summary(packets: list[dict]) -> None:
    render_section_title("Decision load by ward")
    if not packets:
        st.caption("No open decisions.")
        return

    ward_counts: dict[str, dict] = {}
    for p in packets:
        wid = p["ward_id"]
        wname = p.get("ward_name", wid)
        if wid not in ward_counts:
            ward_counts[wid] = {"ward": wname, "total": 0, "immediate": 0, "escalate": 0, "domains": set()}
        ward_counts[wid]["total"]    += 1
        ward_counts[wid]["domains"].add(p["domain"])
        if p["urgency"] == "immediate":
            ward_counts[wid]["immediate"] += 1
        if p.get("escalation_required"):
            ward_counts[wid]["escalate"] += 1

    rows = [
        {
            "Ward":        v["ward"],
            "Decisions":   v["total"],
            "Immediate":   v["immediate"],
            "Escalations": v["escalate"],
            "Domains":     ", ".join(sorted(v["domains"])),
        }
        for v in sorted(ward_counts.values(), key=lambda x: (-x["immediate"], -x["total"]))
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ── Escalation queue ──────────────────────────────────────────────────────────

def _render_escalation_queue(packets: list[dict]) -> None:
    render_section_title("Escalation queue — zonal officer view")
    esc = [p for p in packets if p.get("escalation_required")]
    if not esc:
        st.success("No decisions currently require escalation.")
        return

    rows = []
    for p in esc:
        sig = p.get("signal", {})
        dom = {"air": "Air Quality", "flood": "Flood", "heat": "Heat", "cross_domain": "Cross-Domain"}.get(p["domain"], p["domain"])
        rows.append({
            "Ward":       p.get("ward_name", ""),
            "Domain":     dom,
            "Decision":   p["decision_id"],
            "Urgency":    _URGENCY_LABEL.get(p["urgency"], p["urgency"]),
            "Escalate to": p.get("escalate_to", "—"),
            "Cause":      sig.get("attribution_plain", sig.get("source_attribution", ""))[:60],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(f"{len(esc)} decision(s) require escalation beyond ward engineer authority.")


# ── Coverage notice ───────────────────────────────────────────────────────────

def _render_coverage_notice(city_id: str) -> None:
    """Inline notice about cells excluded from analysis due to low DATA_CONFIDENCE.

    Imports defensively — shows nothing if the data_quality module is not
    available yet (it is being built in parallel).
    """
    try:
        from airos.os.sdk import store as _sdk_store
        summary = _sdk_store.get_quality_summary(city_id)
    except Exception:
        return  # Module not yet available — stay silent

    if summary is None:
        return

    excluded = summary.get("excluded_cells", 0)
    if not excluded:
        return

    st.caption(
        f"ℹ️  Analysis coverage: decisions shown only for cells with DATA_CONFIDENCE ≥ 0.6. "
        f"{excluded:,} cell{'s' if excluded != 1 else ''} in this city "
        f"have insufficient sensor coverage and are excluded from analysis. "
        f"[Sensor recommendations →]"
    )


# ── Main panel ────────────────────────────────────────────────────────────────

def render_ward_decisions_panel() -> None:
    c1, c2 = st.columns([3, 1])
    with c1:
        label   = st.selectbox("City", list(PANEL_CITIES.keys()), key="wd_city_selector")
    with c2:
        if st.button("↻ Refresh", key="wd_refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    city_id = PANEL_CITIES[label]

    render_domain_header(
        title="Ward Decision Support",
        caption=(
            "Active climate decisions for ward engineers — sourced from air, flood, and heat domain signals. "
            "Sorted by urgency. Each decision includes source attribution, recommended action, and escalation guidance."
        ),
        primary_alert=None,
    )

    with st.spinner("Generating ward decisions…"):
        packets, result = _load_decisions(city_id)

    if result is None:
        st.info(
            "Feature store not found. Visit Air Quality, Flood, or Heat tabs first "
            "to populate the store, then return here."
        )
        return

    if not packets:
        st.info(
            f"No climate signals above decision thresholds for **{city_id}**. "
            "All ward scores are within acceptable ranges, or no domain data is available yet."
        )
        return

    _render_summary(packets)
    _render_coverage_notice(city_id)

    # Filters
    fc1, fc2 = st.columns(2)
    with fc1:
        domain_filter = st.selectbox(
            "Domain", ["All", "Air Quality", "Flood", "Heat", "Cross-Domain"],
            key="wd_domain_filter",
        )
    with fc2:
        urgency_filter = st.selectbox(
            "Urgency", ["All", "immediate", "within_4h", "within_24h", "plan"],
            key="wd_urgency_filter",
        )

    t_tasks, t_open, t_wards, t_escalate = st.tabs([
        "📋 Tasks", "Open Decisions", "By Ward", "Escalation Queue",
    ])

    with t_tasks:
        _render_tasks_panel(city_id)

    with t_open:
        _render_decisions_table(packets, domain_filter, urgency_filter)

    with t_wards:
        _render_ward_summary(packets)

    with t_escalate:
        _render_escalation_queue(packets)

    render_technical_json_expander(
        title="Technical: decision packet snapshot",
        payload={
            "city_id":        city_id,
            "total_packets":  len(packets),
            "timestamp_bucket": result.timestamp_bucket if result else "—",
            "available_domains": result.available_domains if result else [],
            "preview":        packets[:3],
        },
    )
