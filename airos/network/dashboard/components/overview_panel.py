"""Stakeholder overview panel — weather.com-style at-a-glance views.

Four roles, one panel:
  Commissioner  — city health scorecard + AI pattern feed
  Dept Head     — domain deep-dive, worst-ward ranking
  Ward Officer  — mobile-first field task list
  Citizen       — simple AQI indicator + advice

Each view has:
  1. Hero — single most important number/status
  2. Metric strip — 3-5 key figures
  3. Detail cards — domain/ward/task specifics
  4. Drill-down to existing Inbox / Domain panels via links
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import streamlit as st


def _html(s: str) -> str:
    """Strip common leading whitespace so Streamlit's Markdown parser
    never sees 4-space-indented lines (which it renders as code blocks)."""
    return textwrap.dedent(s).strip()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RISK_EMOJI = {
    "severe":   "🔴",
    "high":     "🟠",
    "moderate": "🟡",
    "low":      "🟢",
    "unknown":  "⚪",
}
_RISK_COLOR = {
    "severe":   "#b42318",
    "high":     "#c4520a",
    "moderate": "#92670a",
    "low":      "#1a7f37",
    "unknown":  "#6b7280",
}
_RISK_SCORE = {"severe": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}

_DOMAIN_LABEL = {
    "air":          "🌬️ Air Quality",
    "flood":        "💧 Flood",
    "heat":         "🌡️ Heat",
    "water":        "🏞️ Water",
    "fire":         "🔥 Fire",
    "waste":        "🗑️ Waste",
    "construction": "🏗️ Construction",
    "green":        "🌿 Green",
    "noise":        "🔊 Noise",
    "terrain":      "🏔️ Terrain",
    "nightlights":  "💡 Night Lights",
    "infrastructure":"🏙️ Infrastructure",
}

_AQI_LEVELS = [
    (0,   50,  "Good",           "#1a7f37", "Air quality is satisfactory."),
    (51,  100, "Satisfactory",   "#5d7a1f", "Minor discomfort for sensitive people."),
    (101, 200, "Moderate",       "#92670a", "May cause discomfort for sensitive groups."),
    (201, 300, "Poor",           "#c4520a", "Breathing discomfort for most people."),
    (301, 400, "Very Poor",      "#b42318", "Respiratory effects for prolonged exposure."),
    (401, 500, "Severe",         "#7d1f1f", "Health impacts on everyone."),
]


def _aqi_label(val: float | None) -> tuple[str, str, str]:
    """Return (label, color, advice) for an AQI value."""
    if val is None:
        return "No data", "#6b7280", "No recent air quality data available."
    for lo, hi, label, color, advice in _AQI_LEVELS:
        if lo <= val <= hi:
            return label, color, advice
    return "Severe", "#7d1f1f", "Health impacts on everyone."


def _time_ago(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s // 60}m ago"
        if s < 86400: return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "—"


def _worst_risk(risk_dict: dict[str, str]) -> tuple[str, str]:
    """Return (domain, risk_level) for the worst domain."""
    if not risk_dict:
        return "—", "unknown"
    worst_domain = max(risk_dict, key=lambda d: _RISK_SCORE.get(risk_dict[d], 0))
    return worst_domain, risk_dict[worst_domain]


# ---------------------------------------------------------------------------
# Data loaders (cached 60s)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_health(city_id: str) -> dict:
    try:
        from airos.os.sdk import store
        return store.get_city_health_summary(city_id) or {}
    except Exception:
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def _load_domain_drivers(city_id: str) -> list:
    try:
        from airos.os.sdk import store
        return store.get_domain_drivers(city_id)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _load_patterns(city_id: str) -> list:
    try:
        from airos.os.sdk import store
        return store.get_city_patterns(city_id)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _load_ward_risk(city_id: str, domain: str) -> pd.DataFrame:
    try:
        from airos.os.sdk import store
        return store.get_ward_domain_risk(city_id, domain)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _load_field_tasks(city_id: str) -> pd.DataFrame:
    try:
        from airos.os.sdk import store
        return store.get_field_tasks(city_id)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _load_latest_aqi(city_id: str) -> float | None:
    """Return the most recent AQI signal value for a city."""
    try:
        from airos.os.sdk import store
        return store.get_latest_aqi(city_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shared city selector
# ---------------------------------------------------------------------------

def _city_selector(key: str) -> str:
    """Return currently selected city_id."""
    from airos.os.sdk import store
    cities = store.list_cities()
    default = cities.index("bangalore") if "bangalore" in cities else 0
    return st.selectbox("City", cities, index=default, key=f"overview_city_{key}")


# ---------------------------------------------------------------------------
# Role: Commissioner / Senior Official
# ---------------------------------------------------------------------------

_DOMAIN_DRIVER_TEXT = {
    # Green
    "vegetation_loss":   "Vegetation loss detected — satellite NDVI change shows net canopy reduction.",
    "stable_cover":      "Green cover stable — no significant gain or loss detected.",
    "vegetation_gain":   "Vegetation gain — cover expanding, no risk.",
    # Waste
    "landfill_fire":     "Active landfill fire detected (elevated FRP) — smoke contributing to PM2.5.",
    "waste_burn":        "Waste burning incidents detected — contributing to local air pollution.",
    "no_waste_detected": "No active waste burning detected.",
    # Water
    "low_turbidity":     "High water clarity — good optical quality.",
    "moderate_turbidity":"Moderate turbidity — water clarity reduced, possible sediment/algae.",
    "high_turbidity":    "High turbidity — significantly degraded optical water quality.",
    # Air
    "poor":              "Air quality poor — PM2.5 or AQI at unhealthy levels.",
    "very_poor":         "Air quality very poor — PM2.5 severely elevated.",
    "moderate":          "Air quality moderate — acceptable but sensitive groups affected.",
    "satisfactory":      "Air quality satisfactory.",
    "good":              "Air quality good.",
    # Construction
    "high_activity":     "High construction activity — dust, noise, and traffic disruption.",
}


def _render_commissioner(city_id: str) -> None:
    health = _load_health(city_id)
    patterns = _load_patterns(city_id)

    # ── Hero ───────────────────────────────────────────────────────────────
    worst_domain, worst_risk = _worst_risk(health.get("domain_risk", {}))
    risk_color = _RISK_COLOR.get(worst_risk, "#6b7280")
    risk_emoji = _RISK_EMOJI.get(worst_risk, "⚪")

    st.markdown(_html(f"""
        <div style="background:linear-gradient(135deg,{risk_color}18 0%,{risk_color}08 100%);
            border:0.5px solid {risk_color}55;border-radius:12px;
            padding:24px 28px 18px;margin-bottom:16px;">
        <div style="font-size:11px;font-weight:600;letter-spacing:.08em;
            color:rgba(0,0,0,.4);text-transform:uppercase;">City health — {city_id.title()}</div>
        <div style="display:flex;align-items:baseline;gap:12px;margin-top:4px;">
        <span style="font-size:42px;font-weight:700;color:{risk_color};line-height:1.1;">
        {risk_emoji} {worst_risk.upper()}</span>
        <span style="font-size:14px;color:rgba(0,0,0,.55);">
        worst risk · {_DOMAIN_LABEL.get(worst_domain, worst_domain)}</span>
        </div>
        <div style="font-size:12px;color:rgba(0,0,0,.45);margin-top:6px;">
        Updated {_time_ago(health.get("latest_pattern_at"))}</div>
        </div>
    """), unsafe_allow_html=True)

    # ── Metric strip ───────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Monitored cells", f"{health.get('total_cells', 0):,}")
    c2.metric("Assessed (24h)", f"{health.get('cells_assessed_24h', 0):,}")
    c3.metric("Open insights", f"{health.get('open_insights', 0):,}")
    c4.metric(
        "Critical alerts",
        f"{health.get('critical_insights', 0):,}",
        delta=None,
        delta_color="inverse",
    )
    c5.metric("Field tasks", f"{health.get('field_tasks_pending', 0):,}")

    st.divider()

    # ── Domain risk heatmap ────────────────────────────────────────────────
    st.markdown("#### Domain status")
    domain_risk = health.get("domain_risk", {})
    if domain_risk:
        # Display as a compact grid of colored chips
        # Split into tiered (known risk) and index-only (unknown risk)
        tiered   = {d: r for d, r in domain_risk.items() if r != "unknown"}
        untiered = {d: r for d, r in domain_risk.items() if r == "unknown"}

        chips_html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;">'
        for domain, risk in sorted(tiered.items(),
                                   key=lambda x: _RISK_SCORE.get(x[1], 0),
                                   reverse=True):
            color = _RISK_COLOR.get(risk, "#6b7280")
            emoji = _RISK_EMOJI.get(risk, "⚪")
            label = _DOMAIN_LABEL.get(domain, domain.title())
            chips_html += (
                f'<div style="border:0.5px solid {color}66;border-radius:6px;'
                f'padding:5px 10px;background:{color}12;">'
                f'<span style="font-size:12px;font-weight:500;">{label}</span>'
                f'<span style="font-size:11px;color:{color};margin-left:6px;">'
                f'{emoji} {risk}</span></div>'
            )
        chips_html += "</div>"
        if untiered:
            chips_html += (
                '<div style="font-size:11px;color:rgba(0,0,0,.4);margin:4px 0 6px;">'
                'Index data collected — risk tier pending next agent sweep:</div>'
                '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;">'
            )
            for domain in sorted(untiered):
                label = _DOMAIN_LABEL.get(domain, domain.title())
                chips_html += (
                    f'<div style="border:0.5px solid rgba(0,0,0,.18);border-radius:6px;'
                    f'padding:4px 9px;background:rgba(0,0,0,.04);">'
                    f'<span style="font-size:11px;color:rgba(0,0,0,.5);">{label}</span>'
                    f'<span style="font-size:10px;color:rgba(0,0,0,.32);margin-left:5px;">'
                    f'📊 index only</span></div>'
                )
            chips_html += "</div>"
        st.markdown(chips_html, unsafe_allow_html=True)
    else:
        st.caption("No domain assessments yet. Run `python main.py --step ingest-h3` then start the scheduler.")

    # ── Domain driver breakdown ────────────────────────────────────────────
    st.markdown("#### Why these ratings?")
    st.caption("Rule-based assessment from satellite + sensor data. Explains each domain's current risk tier.")

    drivers = _load_domain_drivers(city_id)
    # Only show domains with high/severe risk
    bad_drivers = [d for d in drivers if d["worst_risk"] in ("severe", "high")]
    if bad_drivers:
        for d in bad_drivers:
            dom      = d["domain"]
            risk     = d["worst_risk"]
            color    = _RISK_COLOR.get(risk, "#6b7280")
            emoji    = _RISK_EMOJI.get(risk, "⚪")
            label    = _DOMAIN_LABEL.get(dom, dom.title())
            n_severe = d["n_severe"]
            n_high   = d["n_high"]
            n_total  = d["n_total"]
            issue    = d.get("top_issue") or ""
            issue_n  = d.get("top_issue_cells", 0)
            avg_v    = d.get("avg_value")
            max_v    = d.get("max_value")
            pidx     = d.get("primary_index") or ""

            # Build explanation text
            issue_txt = _DOMAIN_DRIVER_TEXT.get(issue, issue.replace("_", " ") if issue else "")
            cells_txt = f"{n_severe + n_high} of {n_total} cells at {risk}+ risk"
            val_txt = ""
            if avg_v is not None and pidx:
                idx_short = pidx.replace("_INDEX", "").replace("_", " ").title()
                val_txt = f" · {idx_short}: avg {avg_v:.2f}, max {max_v:.2f}"

            with st.expander(
                f"{emoji} **{label}** — {cells_txt}{val_txt}",
                expanded=True,
            ):
                if issue_txt:
                    st.markdown(f"**Primary driver:** {issue_txt}")
                    if issue_n > 0:
                        st.caption(f"{issue_n} cells with `{issue}`")
                _breakdown = []
                if n_severe: _breakdown.append(f"🔴 {n_severe} severe")
                if n_high:   _breakdown.append(f"🟠 {n_high} high")
                if d["n_moderate"]: _breakdown.append(f"🟡 {d['n_moderate']} moderate")
                if d["n_low"]:      _breakdown.append(f"🟢 {d['n_low']} low")
                if _breakdown:
                    st.caption("  ·  ".join(_breakdown))
    else:
        st.caption("No high/severe risk domains currently. All domains at moderate or low risk.")

    st.divider()

    # ── City AI pattern feed ───────────────────────────────────────────────
    st.markdown("#### AI pattern briefing")
    st.caption(
        "LLM synthesis from H3 Expert Agent findings. "
        "Covers domains where cell-level AI analysis has run. "
        "Data-only domains above (green/water/waste) are explained by rule-based assessment."
    )

    if not patterns:
        st.info(
            "No city patterns yet. The pattern agent runs after each H3 sweep "
            "(fires when ≥ 3 new insights are available). "
            "Start the scheduler: `python main.py --step scheduler`"
        )
    else:
        for pat in patterns:
            summary = pat.get("summary") or {}
            themes = summary.get("themes") or []
            headline = summary.get("headline") or summary.get("title") or "City-wide pattern"
            critical_actions = summary.get("critical_actions") or summary.get("actions") or []
            created = _time_ago(pat.get("created_at"))
            n_insights = pat.get("n_insights", 0)
            theme_count = pat.get("theme_count", 0)

            with st.expander(
                f"📋 {headline}  ·  {created}  ·  {n_insights} insights · {theme_count} themes",
                expanded=(pat is patterns[0]),
            ):
                if themes:
                    st.markdown("**Themes identified**")
                    for t in themes:
                        if isinstance(t, dict):
                            st.markdown(
                                f"- **{t.get('theme', t.get('name', '?'))}** — "
                                f"{t.get('description', t.get('detail', ''))}"
                            )
                        else:
                            st.markdown(f"- {t}")

                if critical_actions:
                    st.markdown("**Recommended actions**")
                    for act in critical_actions[:5]:
                        if isinstance(act, dict):
                            st.markdown(f"- {act.get('action', act.get('description', act))}")
                        else:
                            st.markdown(f"- {act}")

                if summary.get("overall_summary") or summary.get("summary"):
                    st.markdown("**Summary**")
                    st.markdown(summary.get("overall_summary") or summary.get("summary", ""))

                with st.expander("Raw pattern JSON", expanded=False):
                    st.json(summary)


# ---------------------------------------------------------------------------
# Role: Department Head
# ---------------------------------------------------------------------------

def _render_dept_head(city_id: str) -> None:
    # Domain selector
    all_domains = list(_DOMAIN_LABEL.keys())
    domain_labels = [_DOMAIN_LABEL[d] for d in all_domains]
    chosen_label = st.selectbox(
        "Focus domain",
        domain_labels,
        key="dh_domain",
    )
    chosen_domain = all_domains[domain_labels.index(chosen_label)]

    df = _load_ward_risk(city_id, chosen_domain)

    # ── Hero ───────────────────────────────────────────────────────────────
    if df.empty:
        worst_risk = "unknown"
        worst_area = "—"
    else:
        worst = df.iloc[0]
        worst_risk = str(worst.get("risk_level", "unknown"))
        worst_area = str(worst.get("area_name", worst.get("h3_id", "—")))

    risk_color = _RISK_COLOR.get(worst_risk, "#6b7280")
    risk_emoji = _RISK_EMOJI.get(worst_risk, "⚪")

    _issue = str(worst.get("dominant_issue", "")) if not df.empty and worst.get("dominant_issue") else ""
    _issue_html = f"  &middot;  {_issue}" if _issue else ""
    st.markdown(_html(f"""
        <div style="border:0.5px solid {risk_color}66;border-radius:10px;
            padding:18px 22px 14px;margin-bottom:16px;background:{risk_color}0d;">
        <div style="font-size:11px;font-weight:600;letter-spacing:.08em;
            color:rgba(0,0,0,.4);text-transform:uppercase;">
        {chosen_label} · Highest Risk Area</div>
        <div style="font-size:30px;font-weight:700;color:{risk_color};
            margin-top:4px;line-height:1.2;">{risk_emoji} {worst_area}</div>
        <div style="font-size:12px;color:rgba(0,0,0,.5);margin-top:4px;">
        Risk: <strong>{worst_risk.upper()}</strong>{_issue_html}</div>
        </div>
    """), unsafe_allow_html=True)

    # ── Metric strip ───────────────────────────────────────────────────────
    if not df.empty:
        by_risk = df["risk_level"].value_counts()
        n_unknown = int(by_risk.get("unknown", 0))
        all_unknown = (n_unknown == len(df))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Severe cells",   int(by_risk.get("severe", 0)))
        c2.metric("High risk cells", int(by_risk.get("high", 0)))
        c3.metric("Moderate cells", int(by_risk.get("moderate", 0)))
        c4.metric("Total assessed",  len(df))
        if all_unknown:
            st.info(
                f"All {len(df)} {chosen_domain} cells have raw index data but no risk tier yet. "
                "Re-run `python main.py --step ingest-h3 --domains "
                + chosen_domain + " --force` to apply updated thresholds.",
                icon="📊",
            )

    st.divider()

    # ── Ward ranking table ─────────────────────────────────────────────────
    st.markdown(f"#### Worst areas — {chosen_label}")
    if df.empty:
        st.info(
            f"No {chosen_domain} assessments in the last 48h for {city_id}. "
            "Run `python main.py --step ingest-h3 --domains "
            + chosen_domain + "` to refresh."
        )
        return

    def _area_label(row: Any) -> str:
        """Return a readable location label, falling back gracefully."""
        name = str(row.get("area_name") or "").strip()
        if name and name not in ("None", "nan"):
            return name
        h3 = str(row.get("h3_id") or "")
        lat = row.get("centroid_lat")
        lon = row.get("centroid_lon")
        if lat and lon:
            return f"{float(lat):.3f}°N {float(lon):.3f}°E"
        return h3[:10] + "…" if len(h3) > 10 else h3

    # Build display table
    display = df.copy()
    display["area_label"] = display.apply(_area_label, axis=1)
    display["risk_level"] = display["risk_level"].apply(
        lambda r: f"{_RISK_EMOJI.get(str(r), '⚪')} {str(r).upper()}"
    )
    display["assessed_at"] = display["assessed_at"].apply(
        lambda t: _time_ago(str(t)) if t else "—"
    )
    show_cols = ["area_label", "risk_level", "dominant_issue", "primary_value", "assessed_at"]
    display = display[[c for c in show_cols if c in display.columns]]
    display.columns = ["Area", "Risk", "Primary issue", "Value", "Last assessed"][:len(display.columns)]
    st.dataframe(display, hide_index=True, use_container_width=True)

    # ── Top issues as action items ─────────────────────────────────────────
    st.markdown("#### Action items")
    seen = set()
    for _, row in df[df["risk_level"].str.contains("severe|high", case=False, na=False)].head(5).iterrows():
        issue = str(row.get("dominant_issue") or "")
        area  = _area_label(row)
        risk  = str(row.get("risk_level") or "")
        key   = f"{area}:{issue}"
        if key in seen or not issue:
            continue
        seen.add(key)
        color = _RISK_COLOR.get(risk, "#6b7280")
        st.markdown(
            f'<div style="border-left:3px solid {color};padding:6px 10px;'
            f'margin-bottom:6px;border-radius:0 6px 6px 0;background:{color}0a;">'
            f'<strong>{area}</strong> — {issue} '
            f'<span style="color:{color};font-size:11px;">({risk})</span></div>',
            unsafe_allow_html=True,
        )
    if not seen:
        st.caption("No severe/high risk cells in current window.")


# ---------------------------------------------------------------------------
# Role: Ward Officer / Field Inspector
# ---------------------------------------------------------------------------

def _render_ward_officer(city_id: str) -> None:
    df = _load_field_tasks(city_id)

    # ── Hero ───────────────────────────────────────────────────────────────
    n_tasks = len(df)
    n_severe = int((df["risk_level"] == "severe").sum()) if not df.empty else 0

    hero_color = "#b42318" if n_severe > 0 else ("#c4520a" if n_tasks > 0 else "#1a7f37")
    hero_msg = (
        f"{n_severe} SEVERE task{'s' if n_severe != 1 else ''} need urgent attention"
        if n_severe > 0
        else (f"{n_tasks} field task{'s' if n_tasks != 1 else ''} pending"
              if n_tasks > 0
              else "No field tasks — all clear")
    )

    _hero_icon = "🚨" if n_severe > 0 else ("📋" if n_tasks > 0 else "✅")
    st.markdown(_html(f"""
        <div style="border:0.5px solid {hero_color}66;border-radius:10px;
            padding:18px 22px 14px;margin-bottom:16px;background:{hero_color}0d;">
        <div style="font-size:11px;font-weight:600;letter-spacing:.08em;
            color:rgba(0,0,0,.4);text-transform:uppercase;">Field tasks — {city_id.title()}</div>
        <div style="font-size:28px;font-weight:700;color:{hero_color};
            margin-top:4px;line-height:1.2;">{_hero_icon} {hero_msg}</div>
        </div>
    """), unsafe_allow_html=True)

    if df.empty:
        st.success("No pending field verifications. Check back after the next scheduler sweep.")
        return

    # ── Metric strip ───────────────────────────────────────────────────────
    by_domain = df["domain"].value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tasks", n_tasks)
    c2.metric("Severe", n_severe)
    c3.metric("High risk", int((df["risk_level"] == "high").sum()))
    c4.metric("Domains affected", len(by_domain))

    st.divider()

    # ── Task list (mobile-friendly cards) ─────────────────────────────────
    st.markdown("#### Your task list")
    st.caption("Ordered by severity. Tap a task for location details.")

    for _, row in df.iterrows():
        risk   = str(row.get("risk_level", "unknown"))
        area   = str(row.get("area_name", row.get("h3_id", "Unknown area")))
        domain = str(row.get("domain", ""))
        color  = _RISK_COLOR.get(risk, "#6b7280")
        emoji  = _RISK_EMOJI.get(risk, "⚪")
        domain_label = _DOMAIN_LABEL.get(domain, domain.title())
        conf   = row.get("confidence_score")
        conf_str = f"{conf:.0%}" if conf else "—"
        lat    = row.get("centroid_lat")
        lon    = row.get("centroid_lon")
        maps_url = (
            f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
            if lat and lon else None
        )

        _nav = f'  &middot; <a href="{maps_url}" target="_blank">📍 Navigate</a>' if maps_url else ""
        _pid = str(row.get("packet_id", ""))[:12]
        with st.container():
            st.markdown(_html(f"""
                <div style="border:0.5px solid {color}66;border-radius:8px;
                    padding:12px 14px;margin-bottom:8px;background:{color}0a;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:14px;font-weight:600;">{area}</span>
                <span style="font-size:12px;color:{color};font-weight:500;">{emoji} {risk.upper()}</span>
                </div>
                <div style="font-size:12px;color:rgba(0,0,0,.55);margin-top:4px;">
                {domain_label} &middot; Confidence: {conf_str}{_nav}</div>
                <div style="font-size:11px;color:rgba(0,0,0,.4);margin-top:2px;">Task ID: {_pid}…</div>
                </div>
            """), unsafe_allow_html=True)

    st.caption(
        "Mark tasks complete in the **📬 Inbox** tab → select packet → set outcome to 'verified_clean' or 'verified_issue'."
    )


# ---------------------------------------------------------------------------
# Role: Citizen / Public
# ---------------------------------------------------------------------------

def _render_citizen(city_id: str) -> None:
    aqi = _load_latest_aqi(city_id)
    label, color, advice = _aqi_label(aqi)

    # ── Hero ───────────────────────────────────────────────────────────────
    aqi_display = f"{aqi:.0f}" if aqi is not None else "—"
    st.markdown(_html(f"""
        <div style="text-align:center;padding:32px 24px 24px;
            background:linear-gradient(160deg,{color}18,{color}06);
            border:0.5px solid {color}55;border-radius:16px;margin-bottom:20px;">
        <div style="font-size:11px;font-weight:600;letter-spacing:.08em;
            color:rgba(0,0,0,.4);text-transform:uppercase;margin-bottom:8px;">
        Air Quality Index · {city_id.title()}</div>
        <div style="font-size:80px;font-weight:800;color:{color};
            line-height:1;margin-bottom:8px;">{aqi_display}</div>
        <div style="font-size:22px;font-weight:600;color:{color};margin-bottom:12px;">{label}</div>
        <div style="font-size:14px;color:rgba(0,0,0,.62);max-width:380px;margin:0 auto;">{advice}</div>
        </div>
    """), unsafe_allow_html=True)

    # ── Health guidance strip ──────────────────────────────────────────────
    score = _RISK_SCORE.get(label.lower().replace(" ", "_"), 0) if aqi else 0
    # Map AQI bands to advice cards
    if aqi is None:
        cards = [
            ("📡", "No recent data", "Sensor data not yet available for this city."),
        ]
    elif aqi <= 50:
        cards = [
            ("🏃", "Great for outdoor activity", "Ideal conditions for running, cycling, or spending time outside."),
            ("🪟", "Open your windows", "Good ventilation is fine — enjoy fresh air."),
            ("🌿", "Garden & green spaces", "Perfect day to visit a park or green area."),
        ]
    elif aqi <= 100:
        cards = [
            ("🚶", "Outdoor activity is fine", "Most people can go outside normally."),
            ("😷", "Sensitive groups: take care", "Children, elderly, and people with respiratory issues should limit prolonged outdoor exertion."),
            ("💧", "Stay hydrated", "Drink plenty of water throughout the day."),
        ]
    elif aqi <= 200:
        cards = [
            ("⚠️", "Limit prolonged outdoor activity", "Take breaks if exercising outside."),
            ("😷", "Consider a mask outdoors", "An N95/FFP2 mask helps if you need to be outside for extended periods."),
            ("🏠", "Keep windows closed", "Use indoor air filtration if available."),
        ]
    elif aqi <= 300:
        cards = [
            ("🏠", "Stay indoors", "Avoid outdoor activities today."),
            ("😷", "Wear a mask if going out", "N95/FFP2 recommended for any outdoor exposure."),
            ("💊", "If you have asthma or COPD", "Keep your inhaler/medication close."),
            ("🌀", "Use air purifier", "Run air purification indoors on maximum setting."),
        ]
    else:
        cards = [
            ("🚨", "Health emergency conditions", "All outdoor activity strongly discouraged."),
            ("😷", "N95 mask mandatory outdoors", "Even brief outdoor exposure can be harmful."),
            ("🏥", "Seek medical advice if symptomatic", "Coughing, shortness of breath, eye irritation — see a doctor."),
            ("🌀", "Maximum indoor air filtration", "Seal gaps in doors/windows if possible."),
        ]

    cols = st.columns(min(len(cards), 3))
    for i, (icon, title, desc) in enumerate(cards):
        with cols[i % len(cols)]:
            st.markdown(_html(f"""
                <div style="border:0.5px solid rgba(0,0,0,.12);border-radius:10px;
                    padding:14px 16px;height:100%;">
                <div style="font-size:24px;margin-bottom:6px;">{icon}</div>
                <div style="font-size:13px;font-weight:600;margin-bottom:4px;">{title}</div>
                <div style="font-size:12px;color:rgba(0,0,0,.55);">{desc}</div>
                </div>
            """), unsafe_allow_html=True)

    # ── Nearby domain summary ──────────────────────────────────────────────
    st.divider()
    health = _load_health(city_id)
    domain_risk = health.get("domain_risk", {})

    if domain_risk:
        st.markdown("#### Other conditions in your city")
        # Show only public-relevant domains
        PUBLIC_DOMAINS = ["air", "flood", "heat", "water", "noise", "green"]
        chips = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
        for d in PUBLIC_DOMAINS:
            if d not in domain_risk:
                continue
            risk  = domain_risk[d]
            color2 = _RISK_COLOR.get(risk, "#6b7280")
            emoji2 = _RISK_EMOJI.get(risk, "⚪")
            label2 = _DOMAIN_LABEL.get(d, d.title())
            chips += (
                f'<div style="border:0.5px solid {color2}55;border-radius:6px;'
                f'padding:6px 12px;background:{color2}0e;">'
                f'{label2} <span style="color:{color2};font-weight:500;">'
                f'{emoji2} {risk}</span></div>'
            )
        chips += "</div>"
        st.markdown(chips, unsafe_allow_html=True)

    st.caption("Data is updated every 30 minutes by automated sensors. For emergencies call 112.")


# ---------------------------------------------------------------------------
# Role: Urban Planner / Researcher
# ---------------------------------------------------------------------------

def _render_planner(city_id: str) -> None:
    """Planner view — time series explorer, domain coverage, export."""
    st.markdown(
        "#### Urban Planner / Researcher view",
    )
    st.info(
        "The full signal history and time-series explorer is available in the "
        "**🔬 Raw Data** tab. The H3 map, domain overlays, and ward comparisons "
        "are in **🗺️ City Map** and **📊 Domains**.",
        icon="ℹ️",
    )

    health = _load_health(city_id)

    # Coverage stats
    c1, c2, c3 = st.columns(3)
    c1.metric("Total H3 cells monitored", f"{health.get('total_cells', 0):,}")
    c2.metric("Domains with data", len(health.get("domain_risk", {})))
    c3.metric("Open research insights", f"{health.get('open_insights', 0):,}")

    st.divider()
    st.markdown("#### Domain data availability")
    domain_risk = health.get("domain_risk", {})
    if domain_risk:
        rows = [
            {
                "Domain": _DOMAIN_LABEL.get(d, d),
                "Coverage status": f"{_RISK_EMOJI.get(r, '⚪')} {r.title()}",
            }
            for d, r in sorted(domain_risk.items())
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No domain data yet.")

    patterns = _load_patterns(city_id)
    if patterns:
        st.divider()
        st.markdown("#### Recent city-level patterns (for research)")
        for pat in patterns[:3]:
            summary = pat.get("summary") or {}
            created = _time_ago(pat.get("created_at"))
            n = pat.get("n_insights", 0)
            themes = pat.get("theme_count", 0)
            with st.expander(f"{created} — {n} insights, {themes} themes", expanded=False):
                st.json(summary)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_ROLES = {
    "🏛️ Commissioner":   ("commissioner", _render_commissioner),
    "🏢 Department Head": ("dept_head",    _render_dept_head),
    "🦺 Ward Officer":    ("ward_officer", _render_ward_officer),
    "🌍 Citizen":         ("citizen",      _render_citizen),
    "📐 Urban Planner":   ("planner",      _render_planner),
}


def render_overview_panel() -> None:
    """Render the stakeholder overview panel.

    Entry point called from app.py.
    """
    st.markdown(
        '<div style="font-size:11px;font-weight:600;letter-spacing:.08em;'
        'color:rgba(0,0,0,.4);text-transform:uppercase;margin-bottom:2px;">'
        'Stakeholder views</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "## City Overview",
    )
    st.caption(
        "Choose your role to see the most relevant information at a glance. "
        "All views are live — data refreshes every 60 seconds."
    )

    # Role selector + city selector in one row
    col_role, col_city = st.columns([3, 1])
    with col_role:
        role_label = st.radio(
            "View as",
            list(_ROLES.keys()),
            horizontal=True,
            key="overview_role",
            label_visibility="collapsed",
        )
    with col_city:
        city_id = _city_selector("main")

    st.divider()

    _, render_fn = _ROLES[role_label]
    render_fn(city_id)
