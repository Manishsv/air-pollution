"""Ward engineer decision support panel.

Surfaces active climate decisions for each ward — sorted by urgency — with
source attribution and recommended action. Implements the ward-level view
from docs/architecture/WARD_DECISION_CATALOGUE.md.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from review_dashboard.ui_shell import (
    render_context_metrics,
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)
from urban_platform.city_config import CITIES as _CITY_REGISTRY, PANEL_CITIES

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


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_decisions(city_id: str) -> tuple[list[dict], object | None]:
    # Translate canonical city_id → place-module ID (which uses "_demo" suffix).
    place_id = _PLACE_ID.get(city_id, f"{city_id}_demo")
    try:
        from urban_platform.place import aggregate_city_wards
        from urban_platform.place.ward_decisions import generate_ward_decisions
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
        from urban_platform.h3_knowledge.data_quality import get_city_quality_summary
        summary = get_city_quality_summary(city_id)
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

    t_open, t_wards, t_escalate = st.tabs(["Open Decisions", "By Ward", "Escalation Queue"])

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
