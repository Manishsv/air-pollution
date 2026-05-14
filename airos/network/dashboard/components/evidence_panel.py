"""Evidence panel — all 9 sections required by REVIEW_CONTRACT §Evidence Panel.

Renders inline inside the insight dialog.  Sections are never hidden behind
expanders except where the spec explicitly permits it.  Uncertainty notes (§4)
and blocked uses (§9) are always immediately visible — the spec prohibits
collapsing them.

Sections
--------
§1  Insight Summary          — finding, confidence, priority_tier, domains,
                               created_at, agent_type
§2  Hypothesis Chain         — every HypothesisItem (proposition, testable_by, confidence)
§3  Recommended Actions      — action, actor, urgency, condition, blocked_if
§4  Uncertainty Notes        — note + impact (MUST NOT be collapsible)
§5  Spatial Context          — map: target cell + k=1 ring, risk_level per domain
§6  Signal Evidence          — latest values, data_quality, DATA_CONFIDENCE,
                               30-day baseline percentile, circadian percentile
§7  Prior Outcomes           — prior h3_expert insights with outcome_status
§8  Safety Gates             — gate name, status, evidence
§9  Blocked Uses             — must be acknowledged before close is enabled

Returns whether the reviewer has acknowledged blocked uses (for the close gate).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_RISK_CSS = {
    "severe": "#b42318", "high": "#c4520a",
    "moderate": "#92670a", "low": "#1a7f37", "unknown": "#6b7280",
}
_RISK_DOT = {
    "severe": "🔴", "high": "🟠", "moderate": "🟡", "low": "🟢", "unknown": "⚪",
}
_URGENCY_CSS = {
    "immediate": "#dc2626", "within_4h": "#ea580c",
    "within_24h": "#ca8a04", "this_week": "#2563eb", "plan": "#6b7280",
}
_GATE_CSS   = {"pass": "#16a34a", "fail": "#dc2626", "not_applicable": "#6b7280"}
_IMPACT_CSS = {"high": "#b42318", "medium": "#92670a", "low": "#6b7280"}
_DQ_LABEL   = {
    "real_station":       "📡 Real station",
    "satellite_derived":  "🛰️ Satellite derived",
    "model_estimate":     "🔮 Model estimate",
    "osm_structural":     "🗺️ OSM structural",
    "derived":            "🧮 Derived",
    "synthetic_fallback": "⚠️ Synthetic estimate",
    "unknown":            "❓ Unknown",
}


def _parse(raw: Any) -> Any:
    if not raw:
        return raw
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _time_ago(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 60:      return "just now"
        if s < 3600:    return f"{s // 60}m ago"
        if s < 86400:   return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return str(ts)[:16]


def _section(label: str) -> None:
    # Use mid-grey #6b7280 which has adequate contrast on both light and dark
    # themes (~4.5:1 on white, ~3.5:1 on Streamlit's dark bg).
    st.markdown(
        f'<div style="font-size:11px;font-weight:700;letter-spacing:.08em;'
        f'text-transform:uppercase;color:#6b7280;margin:18px 0 6px;">'
        f'{label}</div>',
        unsafe_allow_html=True,
    )


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
        f'font-size:11px;font-weight:600;background:{color}18;color:{color};'
        f'border:1px solid {color}33;">{text}</span>'
    )


# ---------------------------------------------------------------------------
# Data loaders (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_neighbors(h3_id: str, city_id: str) -> list[dict]:
    try:
        from airos.os.sdk import store
        return store.get_cell_neighbors(h3_id, city_id)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _load_cell_assessments(h3_id: str, city_id: str) -> list[dict]:
    try:
        from airos.os.sdk import store
        return store.get_cell_assessments(h3_id, city_id)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _load_signal_evidence(h3_id: str, city_id: str) -> dict:
    """Latest signals + DATA_CONFIDENCE + 30-day percentile ranks for this cell."""
    try:
        from airos.os.sdk import store
        return store.get_cell_signal_evidence(h3_id, city_id)
    except Exception as exc:
        return {"rows": [], "error": str(exc)}


@st.cache_data(ttl=60, show_spinner=False)
def _load_prior_outcomes(h3_id: str, city_id: str, current_insight_id: str) -> list[dict]:
    try:
        from airos.os.sdk import store
        return store.get_prior_outcomes(h3_id, city_id, exclude_insight_id=current_insight_id)
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def _load_packets(h3_id: str, city_id: str) -> list[dict]:
    try:
        from airos.os.sdk import store
        return store.get_cell_packets(h3_id, city_id)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _load_pois_for_cells(city_id: str, h3_ids: tuple[str, ...]) -> list[dict]:
    """Return individual POI points whose centroid falls in any of h3_ids."""
    if not h3_ids:
        return []
    import sqlite3 as _sql
    from airos.drivers.store.schema import DB_PATH
    placeholders = ",".join("?" * len(h3_ids))
    try:
        conn = _sql.connect(str(DB_PATH))
        conn.row_factory = _sql.Row
        rows = conn.execute(
            f"""
            SELECT poi_id, h3_id, category, name, latitude, longitude
            FROM poi_points
            WHERE city_id = ? AND h3_id IN ({placeholders})
            """,
            [city_id, *h3_ids],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        # Table may not exist yet on older DBs — that's fine, just no POIs to show.
        return []


# Map category → display colour (RGBA) for the scatter layer.
# Pollution-source categories use warm colours; exposure categories cool.
_POI_COLOR: dict[str, list[int]] = {
    "INDUSTRIAL":        [180,  35,  24, 220],  # red
    "KILN":              [120,   0,   0, 230],  # dark red
    "CONSTRUCTION":      [217, 119,   6, 220],  # orange
    "FUEL_STATION":      [234, 88,   12, 220],  # bright orange
    "WASTE_FACILITY":    [120,  53,  15, 220],  # brown
    "CREMATORIUM":       [88,   28,  135, 220], # purple
    "EATERY":            [180, 83,    9, 180],  # light brown
    "MARKET":            [161, 98,    7, 200],  # tan
    "TRANSIT_TERMINAL":  [29,  78,  216, 220],  # blue
    "HOSPITAL":          [22,  101,  52, 220],  # green
    "SCHOOL":            [21,  94,  117, 200],  # teal
}
_POI_ICON: dict[str, str] = {
    "INDUSTRIAL":       "🏭", "KILN":             "🧱",
    "CONSTRUCTION":     "🚧", "FUEL_STATION":     "⛽",
    "WASTE_FACILITY":   "🗑️", "CREMATORIUM":      "🔥",
    "EATERY":           "🍴", "MARKET":           "🛒",
    "TRANSIT_TERMINAL": "🚌", "HOSPITAL":         "🏥",
    "SCHOOL":           "🏫",
}


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_s1_summary(row: dict) -> None:
    """§1 Insight Summary"""
    _section("§1 — Insight Summary")
    conf     = float(row.get("confidence") or 0)
    tier     = row.get("priority_tier") or ("high" if conf >= 0.75 else "medium" if conf >= 0.45 else "low")
    domains  = row.get("domains_involved") or []
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]
    agent    = row.get("agent_type") or "—"
    created  = row.get("created_at") or ""
    outcome  = row.get("outcome_status", "open")

    tier_col = {"high": "#b42318", "medium": "#92670a", "low": "#1a7f37"}.get(tier, "#6b7280")
    outcome_col = {"open": "#6b7280", "confirmed": "#16a34a",
                   "refuted": "#dc2626", "unverifiable": "#d97706"}.get(outcome, "#6b7280")

    domain_chips = "  ".join(_badge(d, _RISK_CSS.get("moderate", "#6b7280")) for d in domains)

    st.markdown(
        f'<div style="font-size:15px;font-weight:600;line-height:1.5;margin-bottom:10px;">'
        f'{row.get("finding", "")}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px;">'
        f'{_badge(f"confidence {conf:.0%}", tier_col)}'
        f'&nbsp;{_badge(tier.upper() + " PRIORITY", tier_col)}'
        f'&nbsp;{_badge(outcome, outcome_col)}'
        f'&nbsp;<span style="color:#6b7280;">agent: {agent}</span>'
        f'&nbsp;<span style="color:#6b7280;">{_time_ago(created)}</span>'
        f'</div>'
        f'<div style="margin-top:8px;">{domain_chips}</div>',
        unsafe_allow_html=True,
    )


def _render_s2_hypothesis(chain: list) -> None:
    """§2 Hypothesis Chain — every item, never collapsed"""
    _section("§2 — Hypothesis Chain")
    if not chain:
        st.caption("No hypothesis chain recorded.")
        return
    for i, item in enumerate(chain):
        if not isinstance(item, dict):
            st.markdown(f"**{i+1}.** {item}")
            continue
        # Spec shape: proposition / testable_by / confidence
        # Legacy shape: step / evidence / hypothesis / testable_by
        prop = item.get("proposition") or item.get("hypothesis") or item.get("evidence", "")
        test = item.get("testable_by", "")
        conf = item.get("confidence")
        conf_str = f" — conf {float(conf):.0%}" if conf is not None else ""
        st.markdown(f"**{i+1}.** {prop}{conf_str}")
        if test:
            st.markdown(
                f'<div style="margin-left:16px;font-size:12px;color:#6b7280;'
                f'border-left:2px solid rgba(128,128,128,0.25);padding-left:8px;margin-top:2px;">'
                f'🔍 Verify: {test}</div>',
                unsafe_allow_html=True,
            )


def _render_s3_actions(actions: list) -> None:
    """§3 Recommended Actions"""
    _section("§3 — Recommended Actions")
    if not actions:
        st.info(
            "This insight predates the schema change that requires the agent "
            "to emit at least one recommended action. The next agent run on "
            "this cell will produce structured actions. Until then, use the "
            "**💬 Ask agent** tab to draft a follow-up plan from the full "
            "cell dossier — the LLM has access to all signals, POIs, and the "
            "cause classifier output and can produce a brief on demand.",
            icon="ℹ️",
        )
        return
    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            st.markdown(f"- {a}")
            continue
        action   = a.get("action", str(a))
        actor    = a.get("actor") or a.get("who", "")
        urgency  = a.get("urgency", "")
        cond     = a.get("condition", "")
        blocked  = a.get("blocked_if", "")
        urg_col  = _URGENCY_CSS.get(urgency, "#6b7280")

        parts = [f"**{action}**"]
        badges = ""
        if urgency:
            badges += _badge(urgency.replace("_", " "), urg_col) + "&nbsp;"
        if actor:
            badges += _badge(f"→ {actor}", "#2563eb") + "&nbsp;"

        st.markdown(f"{parts[0]}", unsafe_allow_html=False)
        if badges:
            st.markdown(badges, unsafe_allow_html=True)
        if cond:
            st.caption(f"When: {cond}")
        if blocked:
            st.caption(f"⚠️ Blocked if: {blocked}")
        if i < len(actions) - 1:
            st.divider()


def _render_s4_uncertainty(notes: list) -> None:
    """§4 Uncertainty Notes — MUST NOT be hidden (spec prohibition on collapse)"""
    _section("§4 — Uncertainty Notes")
    # Spec: "MUST NOT hide uncertainty notes behind an expand/collapse"
    if not notes:
        st.warning("No uncertainty notes recorded — this is a spec violation.", icon="⚠️")
        return
    for n in notes:
        if isinstance(n, dict):
            text   = n.get("note", str(n))
            impact = n.get("impact", "medium")
        else:
            text   = str(n)
            impact = "medium"
        col = _IMPACT_CSS.get(impact, "#6b7280")
        st.markdown(
            f'<div style="padding:8px 12px;border-left:3px solid {col};'
            f'background:{col}0d;border-radius:0 6px 6px 0;margin:4px 0;">'
            f'<span style="font-size:11px;font-weight:700;color:{col};'
            f'text-transform:uppercase;">{impact} impact</span><br>'
            f'<span style="font-size:13px;">{text}</span></div>',
            unsafe_allow_html=True,
        )


def _render_s5_spatial(h3_id: str, city_id: str, row: dict) -> None:
    """§5 Spatial Context — cell map + k=1 ring risk levels"""
    _section("§5 — Spatial Context")

    # Cell centroid + meta
    lat = row.get("centroid_lat")
    lon = row.get("centroid_lon")
    area = row.get("area_name") or ""
    land = row.get("land_use_class") or ""

    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.markdown(
            f'<div style="font-size:12px;">'
            f'<b>Cell:</b> <code>{h3_id}</code><br>'
            + (f'<b>Area:</b> {area}<br>' if area else "")
            + (f'<b>Land use:</b> {land}<br>' if land else "")
            + (f'<b>Centroid:</b> {float(lat):.4f}°N, {float(lon):.4f}°E' if lat and lon else "")
            + '</div>',
            unsafe_allow_html=True,
        )

    # Current cell risk per domain
    assessments = _load_cell_assessments(h3_id, city_id)
    if assessments:
        with col_b:
            st.markdown('<div style="font-size:12px;font-weight:600;">Risk by domain</div>',
                        unsafe_allow_html=True)
            for a in assessments:
                rl  = a.get("risk_level", "unknown")
                dot = _RISK_DOT.get(rl, "⚪")
                st.markdown(
                    f'<div style="font-size:12px;">{dot} <b>{a["domain"]}</b> — {rl}</div>',
                    unsafe_allow_html=True,
                )

    # Map — target cell + k=1 ring
    if lat and lon:
        try:
            import pydeck as pdk
            from airos.network.dashboard.pydeck_utils import clean_h3_data

            # Build cells list: target + neighbors
            neighbors = _load_neighbors(h3_id, city_id)
            risk_by_cell: dict[str, str] = {}
            for nb in neighbors:
                # keep highest-risk domain per neighbor cell
                cur = risk_by_cell.get(nb["h3_id"], "unknown")
                if _RISK_DOT.get(nb["risk_level"], 0) and \
                   ["unknown","low","moderate","high","severe"].index(nb.get("risk_level","unknown")) > \
                   ["unknown","low","moderate","high","severe"].index(cur):
                    risk_by_cell[nb["h3_id"]] = nb["risk_level"]

            # Target cell — use its highest risk
            target_risk = "unknown"
            if assessments:
                order = ["unknown","low","moderate","high","severe"]
                for a in assessments:
                    rl = a.get("risk_level","unknown")
                    if order.index(rl) > order.index(target_risk):
                        target_risk = rl

            # Neighbour cells: semi-transparent fill (alpha 140)
            _RGBA_NB = {
                "severe":   [180, 35,  24, 140],
                "high":     [196, 82,  10, 130],
                "moderate": [202, 138,  4, 110],
                "low":      [ 22, 163, 74,  90],
                "unknown":  [156, 163,175,  70],
            }
            # Target cell stroke colours (RGB only — alpha on line is separate)
            _STROKE = {
                "severe":   [180,  35,  24],
                "high":     [196,  82,  10],
                "moderate": [202, 138,   4],
                "low":      [ 22, 163,  74],
                "unknown":  [107, 114, 128],
            }
            # Target cell: very low fill so map shows through, bright border
            _target_stroke = _STROKE.get(target_risk, _STROKE["unknown"])
            target_fill = _target_stroke + [35]   # alpha=35 → ~14% opaque

            nb_cells = [
                {"h3_id": nb_id, "color": _RGBA_NB.get(nb_risk, _RGBA_NB["unknown"])}
                for nb_id, nb_risk in risk_by_cell.items()
            ]
            target_cell = [{"h3_id": h3_id, "color": target_fill,
                             "line_color": _target_stroke + [255]}]

            # Layer 1: neighbour cells (filled, no stroke)
            nb_layer = pdk.Layer(
                "H3HexagonLayer",
                data=clean_h3_data(nb_cells),
                get_hexagon="h3_id",
                get_fill_color="color",
                get_elevation=0,
                elevation_scale=0,
                pickable=False,
                filled=True,
                stroked=False,
                extruded=False,
            )
            # Layer 2: target cell (transparent fill + bright stroke)
            target_layer = pdk.Layer(
                "H3HexagonLayer",
                data=clean_h3_data(target_cell),
                get_hexagon="h3_id",
                get_fill_color="color",
                get_line_color="line_color",
                get_elevation=0,
                elevation_scale=0,
                pickable=False,
                filled=True,
                stroked=True,
                line_width_min_pixels=3,
                extruded=False,
            )

            # Layer 3: POIs — load points in target + neighbour cells
            poi_layer = None
            poi_categories_shown: dict[str, int] = {}
            cell_pool = tuple({h3_id, *risk_by_cell.keys()})
            pois = _load_pois_for_cells(city_id, cell_pool)
            if pois:
                poi_data = []
                for p in pois:
                    cat = p.get("category", "")
                    color = _POI_COLOR.get(cat, [100, 100, 100, 200])
                    poi_data.append({
                        "lon":      float(p["longitude"]),
                        "lat":      float(p["latitude"]),
                        "color":    color,
                        "name":     p.get("name") or cat.replace("_", " ").title(),
                        "category": cat.replace("_", " ").title(),
                    })
                    poi_categories_shown[cat] = poi_categories_shown.get(cat, 0) + 1
                poi_layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=poi_data,
                    get_position="[lon, lat]",
                    get_fill_color="color",
                    get_radius=18,
                    radius_min_pixels=4,
                    radius_max_pixels=10,
                    pickable=True,
                    stroked=True,
                    line_width_min_pixels=0.5,
                    get_line_color=[255, 255, 255, 200],
                )

            view = pdk.ViewState(latitude=float(lat), longitude=float(lon), zoom=13, pitch=0)
            layers = [nb_layer, target_layer]
            if poi_layer is not None:
                layers.append(poi_layer)
            st.pydeck_chart(
                pdk.Deck(
                    layers=layers,
                    initial_view_state=view,
                    map_style="light",
                    tooltip={"html": "<b>{name}</b><br/>{category}",
                             "style": {"backgroundColor": "white",
                                       "color":           "black",
                                       "fontSize":        "12px"}},
                ),
                use_container_width=True,
            )

            # Legend — only the categories actually visible in this view
            if poi_categories_shown:
                legend_chips = "&nbsp; ".join(
                    f'<span style="display:inline-block;width:9px;height:9px;'
                    f'border-radius:50%;background:rgb({_POI_COLOR[cat][0]},'
                    f'{_POI_COLOR[cat][1]},{_POI_COLOR[cat][2]});"></span>&nbsp;'
                    f'{_POI_ICON.get(cat, "•")} {cat.replace("_", " ").title()} '
                    f'<span style="color:#6b7280;">×{n}</span>'
                    for cat, n in sorted(poi_categories_shown.items(),
                                         key=lambda x: -x[1])
                )
                st.markdown(
                    f'<div style="font-size:11px;margin:4px 0 8px 0;">'
                    f'<b>POIs on map:</b>&nbsp; {legend_chips}</div>',
                    unsafe_allow_html=True,
                )

            # k=1 ring summary table
            if neighbors:
                nb_summary = {}
                for nb in neighbors:
                    nb_id = nb["h3_id"]
                    rl    = nb.get("risk_level", "unknown")
                    dom   = nb.get("domain", "?")
                    if nb_id not in nb_summary:
                        nb_summary[nb_id] = {}
                    nb_summary[nb_id][dom] = rl

                with st.expander(f"k=1 ring — {len(nb_summary)} neighbour cells", expanded=False):
                    for nb_id, domains in nb_summary.items():
                        dom_str = "  ".join(
                            f'{_RISK_DOT.get(rl,"⚪")} {d}'
                            for d, rl in sorted(domains.items())
                        )
                        st.markdown(
                            f'`{nb_id[:10]}…`&nbsp;&nbsp;{dom_str}',
                            unsafe_allow_html=True,
                        )
        except ImportError:
            if lat and lon:
                map_df = pd.DataFrame([{"lat": float(lat), "lon": float(lon)}])
                st.map(map_df, zoom=13)
    else:
        st.caption("No centroid coordinates — map unavailable.")


def _render_s6_signals(h3_id: str, city_id: str) -> None:
    """§6 Signal Evidence — latest values, data_quality, DATA_CONFIDENCE, baseline %ile"""
    _section("§6 — Signal Evidence")
    ev = _load_signal_evidence(h3_id, city_id)
    rows = ev.get("rows", [])
    if not rows:
        st.caption("No recent signals found for this cell.")
        return

    # Group by domain
    by_domain: dict[str, list] = {}
    for r in rows:
        by_domain.setdefault(r.get("domain", "?"), []).append(r)

    for domain, sigs in sorted(by_domain.items()):
        # Find DATA_CONFIDENCE for this domain
        dc_row = next((s for s in sigs if s.get("signal") == "DATA_CONFIDENCE"), None)
        dc_val = dc_row.get("value") if dc_row else None

        dc_badge = ""
        if dc_val is not None:
            dc_col = "#16a34a" if dc_val >= 0.7 else "#ca8a04" if dc_val >= 0.4 else "#dc2626"
            dc_badge = f'&nbsp;{_badge(f"DC {dc_val:.2f}", dc_col)}'

        st.markdown(
            f'<div style="font-size:12px;font-weight:700;margin:10px 0 4px;">'
            f'{domain.upper()}{dc_badge}</div>',
            unsafe_allow_html=True,
        )

        for s in sigs:
            sig_name = s.get("signal", "")
            if sig_name == "DATA_CONFIDENCE":
                continue  # shown in header badge above
            val   = s.get("value")
            unit  = s.get("unit") or ""
            dq    = s.get("data_quality", "unknown")
            pct   = s.get("pct_rank_30d")
            mean  = s.get("mean_30d")
            obs   = _time_ago(s.get("observed_at"))

            val_str = f"{val:.3g} {unit}".strip() if val is not None else "—"
            pct_str = f"{pct:.0f}th pct (30d)" if pct is not None else ""
            mean_str = f"30d mean: {mean:.3g} {unit}".strip() if mean is not None else ""
            dq_label = _DQ_LABEL.get(dq, dq)

            st.markdown(
                f'<div style="font-size:12px;padding:3px 0 3px 12px;'
                f'border-left:2px solid rgba(128,128,128,0.22);">'
                f'<b>{sig_name}</b>: {val_str}'
                + (f'&ensp;<span style="color:#6b7280;">{pct_str}</span>' if pct_str else "")
                + (f'&ensp;<span style="color:#9ca3af;font-size:11px;">{mean_str}</span>' if mean_str else "")
                + f'<br><span style="font-size:11px;color:#9ca3af;">{dq_label} · {obs}</span>'
                + '</div>',
                unsafe_allow_html=True,
            )


def _render_s7_prior_outcomes(h3_id: str, city_id: str, insight_id: str) -> None:
    """§7 Prior Outcomes — all prior h3_expert insights for this cell"""
    _section("§7 — Prior Outcomes")
    prior = _load_prior_outcomes(h3_id, city_id, insight_id)
    if not prior:
        st.caption("No prior closed insights for this cell.")
        return

    # Flag if any prior insights were refuted — spec: MUST be visually flagged
    refuted = [p for p in prior if p.get("outcome_status") == "refuted"]
    if refuted:
        st.warning(
            f"⚠️ {len(refuted)} prior insight(s) for this cell were **refuted**. "
            "Review carefully before confirming a similar finding.",
            icon="⚠️",
        )

    _STATUS_CSS = {
        "confirmed":    "#16a34a",
        "refuted":      "#dc2626",
        "unverifiable": "#d97706",
    }
    for p in prior:
        status  = p.get("outcome_status", "?")
        col     = _STATUS_CSS.get(status, "#6b7280")
        finding = str(p.get("finding") or "")[:120]
        when    = _time_ago(p.get("closed_at") or p.get("created_at"))
        closedby= p.get("closed_by") or "—"
        st.markdown(
            f'{_badge(status, col)}'
            f'&nbsp;<span style="font-size:12px;">{finding}…</span>'
            f'<br><span style="font-size:11px;color:#9ca3af;">'
            f'closed by {closedby} · {when}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("")


def _render_s8_safety_gates(packets: list) -> None:
    """§8 Safety Gates — from associated decision packets"""
    _section("§8 — Safety Gates")
    all_gates = []
    for p in packets:
        gates = p.get("safety_gates") or []
        for g in gates:
            if isinstance(g, dict):
                all_gates.append({**g, "_packet_domain": p.get("domain", "")})

    if not all_gates:
        st.caption("No safety gate evaluations recorded for this cell's packets.")
        return

    for g in all_gates:
        status = g.get("status", "not_applicable")
        name   = g.get("gate") or g.get("name", "unnamed gate")
        # Detail text can arrive under several keys depending on which writer
        # produced the gate (insight_packets uses `note`; older writers use
        # `evidence`/`reason`).  Read all three.
        evid   = (
            g.get("evidence")
            or g.get("reason")
            or g.get("note")
            or g.get("description")
            or ""
        )
        col    = _GATE_CSS.get(status, "#6b7280")
        icon   = {"pass": "✅", "fail": "❌", "not_applicable": "➖"}.get(status, "❓")
        st.markdown(
            f'{icon} {_badge(status, col)}'
            f'&nbsp;<span style="font-size:13px;font-weight:600;">{name}</span>'
            + (f'<br><span style="font-size:12px;color:#6b7280;padding-left:22px;">{evid}</span>' if evid else ""),
            unsafe_allow_html=True,
        )


def _render_s9_blocked_uses(packets: list, scope: str) -> bool:
    """§9 Blocked Uses — displayed prominently; returns True when acknowledged.

    Spec: MUST NOT allow reviewer to close without having scrolled past /
    acknowledged blocked uses.  We implement this as a required checkbox.
    """
    _section("§9 — Blocked Uses")

    all_blocked: list[str] = []
    for p in packets:
        uses = p.get("blocked_uses") or []
        for u in uses:
            text = u.get("use") or u.get("description") or str(u) if isinstance(u, dict) else str(u)
            if text and text not in all_blocked:
                all_blocked.append(text)

    if not all_blocked:
        st.caption("No blocked uses declared for this cell's packets.")
        return True  # nothing to acknowledge

    for u in all_blocked:
        st.markdown(
            f'<div style="padding:8px 12px;border-left:3px solid #dc2626;'
            f'background:#dc26260d;border-radius:0 6px 6px 0;margin:4px 0;">'
            f'🚫 {u}</div>',
            unsafe_allow_html=True,
        )

    ack_key = f"blocked_ack_{scope}"
    acknowledged = st.checkbox(
        "I have read and understood the blocked uses listed above.",
        key=ack_key,
        value=st.session_state.get(ack_key, False),
    )
    if not acknowledged:
        st.caption("⚠️ You must acknowledge the blocked uses before closing this insight.")
    return acknowledged


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_evidence_panel(row: dict, *, scope: str = "ev") -> bool:
    """Render the full 9-section evidence panel.

    Parameters
    ----------
    row   : Fully enriched insight dict (from _load_full_row in inbox_panel)
    scope : Unique prefix for session state keys (use insight_id slice)

    Returns
    -------
    bool : True when the reviewer has acknowledged any blocked uses (required
           for the close action to be enabled).
    """
    h3_id      = str(row.get("h3_id", ""))
    city_id    = str(row.get("city_id", ""))
    insight_id = str(row.get("insight_id", ""))

    chain   = _parse(row.get("hypothesis_chain_json") or row.get("hypothesis_chain") or [])
    actions = _parse(row.get("recommended_actions_json") or row.get("recommended_actions") or [])
    notes   = _parse(row.get("uncertainty_notes_json") or row.get("uncertainty_notes") or [])
    packets = _load_packets(h3_id, city_id) if h3_id and city_id else []

    # Fallback: older insights (before schema required recommended_actions)
    # may have an empty list. Look up the associated packet's routing_action
    # so the section is never blank.
    if not actions and h3_id and city_id:
        try:
            import sqlite3 as _sql
            from airos.drivers.store.schema import DB_PATH
            _conn = _sql.connect(str(DB_PATH))
            _row = _conn.execute(
                """
                SELECT packet_json FROM h3_packets
                WHERE h3_id = ? AND city_id = ?
                  AND json_extract(packet_json, '$.source_insight_id') = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (h3_id, city_id, insight_id),
            ).fetchone()
            _conn.close()
            if _row and _row[0]:
                _pj = json.loads(_row[0])
                _ra = _pj.get("routing_action")
                if _ra:
                    actions = [{
                        "action":    _ra,
                        "actor":     _pj.get("routed_to") or "ward_engineer",
                        "urgency":   _pj.get("urgency", "within_24h"),
                        "condition": "Auto-derived from cause-classifier routing — verify in field before dispatch.",
                    }]
        except Exception:
            pass

    _render_s1_summary(row)
    st.divider()
    _render_s2_hypothesis(chain)
    st.divider()
    _render_s3_actions(actions)
    st.divider()
    _render_s4_uncertainty(notes)
    st.divider()
    _render_s5_spatial(h3_id, city_id, row)
    st.divider()
    _render_s6_signals(h3_id, city_id)
    st.divider()
    _render_s7_prior_outcomes(h3_id, city_id, insight_id)
    st.divider()
    _render_s8_safety_gates(packets)
    st.divider()
    acknowledged = _render_s9_blocked_uses(packets, scope=scope)

    return acknowledged
