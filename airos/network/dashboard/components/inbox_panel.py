"""Inbox panel — Gmail-style unified view of H3 expert insights.

Design principles
-----------------
- Dense list: one row per insight, ~36 px, no cards/borders
- Single-click row selection → detail opens below, full width
- Filters in a single compact bar above the list
- LLM chat only loaded inside the "Ask" tab (not at top level)
- Detail header is a single line of meta, not a big coloured block
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RISK_DOT = {
    "severe":   "🔴",
    "high":     "🟠",
    "moderate": "🟡",
    "low":      "🟢",
    "unknown":  "⚪",
}
_RISK_CSS = {
    "severe":   "#b42318",
    "high":     "#c4520a",
    "moderate": "#92670a",
    "low":      "#1a7f37",
    "unknown":  "#6b7280",
}
_RISK_SCORE = {"severe": 4, "high": 3, "moderate": 2, "low": 1, "unknown": 0}
_SCORE_RISK = {v: k for k, v in _RISK_SCORE.items()}


def _time_ago(dt) -> str:
    if dt is None:
        return "—"
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 60:      return "just now"
        if s < 3600:
            m = s // 60
            return f"{m} min ago" if m == 1 else f"{m} mins ago"
        if s < 86400:
            h = s // 3600
            return f"{h} hr ago" if h == 1 else f"{h} hrs ago"
        d = s // 86400
        return f"{d} day ago" if d == 1 else f"{d} days ago"
    except Exception:
        return "—"


def _parse_domains(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [d.strip() for d in raw if d]
    return [d.strip() for d in str(raw).split(",") if d.strip()]


def _parse_chain(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _load_insights(
    *,
    city_id: Optional[str],
    min_confidence: float,
    domains: list[str] | None,
    days_back: int,
    priority_tier: str | None = None,
    outcome_status: str | None = "open",
    limit: int = 300,
) -> pd.DataFrame:
    try:
        from airos.os.sdk import store
        return store.get_insights(
            city_id,
            min_confidence=min_confidence,
            domains=domains,
            days_back=days_back,
            priority_tier=priority_tier,
            outcome_status=outcome_status,
            limit=limit,
        )
    except Exception as exc:
        st.error(f"Could not load insights: {exc}")
        return pd.DataFrame()


def _row_location(r) -> str:
    _an      = r.get("area_name")
    area     = "" if (not _an or not pd.notna(_an)) else str(_an).strip()
    land_use = str(r.get("land_use_class") or "").strip()
    city     = str(r.get("city_id") or "").strip()
    h3_short = str(r.get("h3_id", ""))[:8]
    loc      = area or land_use or h3_short
    return f"{loc}, {city.title()}" if city else loc


# ---------------------------------------------------------------------------
# Detail — causal chain
# ---------------------------------------------------------------------------

def _render_causal_chain(chain: list) -> None:
    if not chain:
        st.caption("No causal chain recorded.")
        return
    for i, step in enumerate(chain):
        if isinstance(step, dict):
            ev  = step.get("evidence", "")
            inf = step.get("inference", "")
            if not ev and not inf:
                # flat dict — just join values
                text = " · ".join(str(v) for v in step.values() if v)
                st.markdown(f"**{i+1}.** {text}")
            else:
                st.markdown(f"**{i+1}.** {ev}")
                if inf:
                    st.markdown(
                        f'<div style="margin-left:18px;color:rgba(0,0,0,0.55);'
                        f'font-size:12px;margin-top:2px;">→ {inf}</div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.markdown(f"**{i+1}.** {step}")


# ---------------------------------------------------------------------------
# Follow-up chat
# ---------------------------------------------------------------------------

def _render_chat(insight: dict, llm_key_prefix: str = "ask_llm") -> None:
    from airos.network.dashboard.components.agent_panel import render_llm_settings
    # llm_key_prefix is panel-scoped ("inbox_ask_llm" / "map_ask_llm") — stable across rerenders
    llm_cfg  = render_llm_settings(key_prefix=llm_key_prefix)
    # Combine panel prefix + insight id so the same insight in two tabs has distinct keys
    scope    = f"{llm_key_prefix}_{insight.get('insight_id','x')[:12]}"
    chat_key = f"chat_{scope}"

    if chat_key not in st.session_state:
        st.session_state[chat_key] = []
    history: list[dict] = st.session_state[chat_key]

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if not history:
        st.caption("Suggested questions:")
        for sug in [
            "Why is the confidence at this level?",
            "What would escalate this to critical?",
            "Draft a field inspection brief.",
        ]:
            if st.button(sug, key=f"sug_{scope}_{sug[:15]}"):
                st.session_state[chat_key].append({"role": "user", "content": sug})
                st.rerun()

    if prompt := st.chat_input("Ask about this insight…", key=f"inp_{scope}"):
        st.session_state[chat_key].append({"role": "user", "content": prompt})
        st.rerun()

    if history and history[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    from airos.agents.llm_client import LLMClient
                    domains  = _parse_domains(insight.get("domains_involved"))
                    chain    = _parse_chain(insight.get("causal_chain_json"))
                    chain_tx = "\n".join(
                        f"  {i+1}. {s.get('evidence','')}"
                        + (f" → {s.get('inference','')}" if isinstance(s, dict) and s.get('inference') else "")
                        if isinstance(s, dict) else f"  {i+1}. {s}"
                        for i, s in enumerate(chain)
                    )
                    system = f"""You are an urban intelligence assistant helping a city officer
understand an AI-generated environmental risk finding.

Finding: {insight.get('finding')}
Confidence: {float(insight.get('confidence') or 0):.0%}
Domains: {', '.join(domains)}
Cell: {insight.get('h3_id')} ({insight.get('city_id')})
Causal chain:\n{chain_tx or '  (not recorded)'}

Answer clearly and concisely. Reference specific signal values when available.
If asked for a document, produce one. Acknowledge uncertainty honestly."""

                    resp  = LLMClient(llm_cfg).chat(
                        [{"role": m["role"], "content": m["content"]} for m in history],
                        system=system, max_tokens=1024,
                    )
                    reply = resp.content or "(Empty response from model.)"
                except Exception as exc:
                    reply = f"⚠️ {exc}"
            st.markdown(reply)
        st.session_state[chat_key].append({"role": "assistant", "content": reply})
        st.rerun()


# ---------------------------------------------------------------------------
# Detail panel
# ---------------------------------------------------------------------------

def _render_detail(row: dict, llm_key_prefix: str = "ask_llm") -> None:
    from airos.network.dashboard.components.evidence_panel import render_evidence_panel

    insight_id = str(row.get("insight_id", ""))
    h3_id      = str(row.get("h3_id", ""))
    city       = str(row.get("city_id", ""))
    outcome    = row.get("outcome_status", "open")
    scope      = f"{llm_key_prefix}_{insight_id[:12]}"

    # ── Tabs ──────────────────────────────────────────────────────────────
    # Evidence tab is first and contains all 9 spec-required sections.
    # Close tab is gated on blocked-uses acknowledgement from Evidence tab.
    t_ev, t_close, t_ask = st.tabs(["📋 Evidence (9 sections)", "✅ Close", "💬 Ask agent"])

    with t_ev:
        # render_evidence_panel returns True when blocked uses are acknowledged
        blocked_ack = render_evidence_panel(row, scope=scope)
        # Store ack state so Close tab can read it
        st.session_state[f"ev_complete_{scope}"] = blocked_ack

    with t_close:
        if outcome != "open":
            # Insight already closed — show permanent record.
            # REVIEW_CONTRACT §Re-open Prohibition: closed records are permanent.
            # The review interface MUST NOT offer a re-open action.
            closed_by_val = row.get("closed_by") or "—"
            closed_at_val = row.get("closed_at", "")
            closed_label  = _time_ago(closed_at_val) if closed_at_val else "—"
            _STATUS_ICONS = {"confirmed": "✅", "refuted": "❌", "unverifiable": "❓"}
            icon = _STATUS_ICONS.get(outcome, "ℹ️")
            st.markdown(
                f'{icon} **{outcome.title()}** · closed by `{closed_by_val}` · {closed_label}',
            )
            st.caption(
                "This insight has been closed. Closed records are permanent — "
                "if conditions recur the agent will produce a new insight on the next sweep."
            )
        else:
            # REVIEW_CONTRACT §Completeness Requirement:
            # reviewer MUST have seen full evidence (incl. blocked uses) before close.
            blocked_ack = st.session_state.get(f"ev_complete_{scope}", False)
            if not blocked_ack:
                st.info(
                    "Open the **📋 Evidence** tab first and review all sections — "
                    "including any blocked uses — before submitting a verdict.",
                    icon="👆",
                )
            else:
                st.markdown(
                    "**Record your field verdict on this hypothesis.**  \n"
                    "This closes the feedback loop — outcomes calibrate future agent confidence scores."
                )

                # REVIEW_CONTRACT §Reviewer Identity: closed_by MUST be non-empty.
                officer = st.text_input(
                    "Your officer ID",
                    key=f"officer_{llm_key_prefix}_{insight_id}",
                    placeholder="e.g. ward_engineer_42 or officer@city.gov",
                    help="Required. Must uniquely identify you within this deployment.",
                )

                verdict = st.radio(
                    "Verdict",
                    ["confirmed", "refuted", "unverifiable"],
                    format_func=lambda x: {
                        "confirmed":    "✓ Confirmed — field check validated the hypothesis",
                        "refuted":      "✗ Refuted — field check contradicted the hypothesis",
                        "unverifiable": "? Unverifiable — cannot check (access, resources, etc.)",
                    }[x],
                    key=f"verdict_{llm_key_prefix}_{insight_id}",
                )

                submit_disabled = not officer.strip()
                if submit_disabled:
                    st.caption("⚠️ Enter your officer ID before submitting.")

                if st.button(
                    "Submit verdict",
                    type="primary",
                    key=f"submit_verdict_{llm_key_prefix}_{insight_id}",
                    disabled=submit_disabled,
                ):
                    try:
                        from airos.os.sdk import AirOSClient
                        AirOSClient().close_insight(
                            insight_id=insight_id,
                            outcome_status=verdict,
                            closed_by=officer.strip(),
                        )
                        st.success(f"Marked as **{verdict}**. Thank you — this improves future analysis.")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"Submission rejected: {e}")
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

    with t_ask:
        _render_chat(row, llm_key_prefix=llm_key_prefix)


# ---------------------------------------------------------------------------
# Empty state — with in-app agent trigger
# ---------------------------------------------------------------------------

def _render_empty_state(city_id: str | None, city_registry: dict) -> None:
    """Informational empty state — no triggers, just status and guidance."""
    from airos.os.sdk import store

    city_label = "all cities" if not city_id else (
        city_registry.get(city_id, {}).get("display_name", city_id.title())
    )

    # Pull ingest log and cell counts to explain *why* there are no insights
    try:
        stats = store.get_stats()
        if not bool(stats):  # non-empty means store is available
            cell_count = 0
            log_df     = pd.DataFrame()
        else:
            cell_count = int(stats.get("cell_count", 0))
            log_df     = stats.get("ingest_log", pd.DataFrame())
    except Exception:
        cell_count = 0
        log_df     = pd.DataFrame()

    st.markdown("")

    if cell_count == 0 and log_df.empty:
        # Pipeline has never run for this city
        st.info(
            f"**No data ingested for {city_label} yet.**  \n"
            "The batch pipeline hasn't run for this city. "
            "Check the **🔌 Data Sources** tab to see pipeline status "
            "or ask your administrator to schedule ingest.",
            icon="📡",
        )
        return

    # Pipeline has run but agent hasn't produced insights yet
    last_ingest = "—"
    if not log_df.empty and "last_ingested_at" in log_df.columns:
        latest_ts = log_df["last_ingested_at"].dropna().max()
        if latest_ts:
            last_ingest = _time_ago(latest_ts)

    ok_count      = int((log_df["status"] == "ok").sum())     if not log_df.empty else 0
    partial_count = int((log_df["status"] == "partial").sum()) if not log_df.empty else 0

    st.markdown(
        f'<div style="text-align:center;padding:28px 0 4px;">'
        f'<div style="font-size:28px;margin-bottom:8px;">📭</div>'
        f'<div style="font-size:15px;font-weight:500;margin-bottom:6px;">'
        f'No insights for {city_label} yet</div>'
        f'<div style="font-size:13px;color:rgba(0,0,0,0.5);">'
        f'{cell_count:,} cells assessed · last data pull {last_ingest}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("")

    # Status detail in two compact columns
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div style="border:0.5px solid rgba(0,0,0,0.12);border-radius:8px;'
            f'padding:12px 16px;">'
            f'<div style="font-size:12px;color:rgba(0,0,0,0.45);margin-bottom:4px;">DATA PIPELINE</div>'
            f'<div style="font-size:13px;">'
            f'{"🟢" if ok_count else "🟡"} {ok_count} sources live'
            f'{f", {partial_count} degraded" if partial_count else ""}'
            f'</div>'
            f'<div style="font-size:11px;color:rgba(0,0,0,0.45);margin-top:4px;">'
            f'Last pull: {last_ingest}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div style="border:0.5px solid rgba(0,0,0,0.12);border-radius:8px;'
            f'padding:12px 16px;">'
            f'<div style="font-size:12px;color:rgba(0,0,0,0.45);margin-bottom:4px;">AI AGENT</div>'
            f'<div style="font-size:13px;">⏳ Waiting for scheduled run</div>'
            f'<div style="font-size:11px;color:rgba(0,0,0,0.45);margin-top:4px;">'
            f'Insights are generated automatically by the batch process</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.caption("Check the **🔌 Data Sources** tab for pipeline health and schedule details.")


# ---------------------------------------------------------------------------
# Dialog — modal detail popup (Streamlit ≥ 1.36)
# ---------------------------------------------------------------------------

PAGE_SIZE = 25


@st.dialog("Insight Detail", width="large")
def _insight_dialog(row: dict) -> None:
    """Modal popup shown when the user clicks a row in the inbox list.

    Uses a scrollable st.container so content that exceeds viewport height
    is always reachable — the dialog box itself also has overflow-y:auto via
    _DIALOG_CSS, giving two independent scroll layers for belt-and-suspenders.
    """
    with st.container(height=700, border=False):
        _render_detail(row, llm_key_prefix="inbox_dialog")


# ---------------------------------------------------------------------------
# Row enrichment
# ---------------------------------------------------------------------------

def _load_full_row(row: dict) -> dict:
    """Enrich a summary row dict with all JSON columns from the DB."""
    try:
        import json as _json
        from airos.os.sdk import store
        city_id = row.get("city_id")
        h3_id   = row.get("h3_id")
        df = store.get_signals(city_id, h3_id=h3_id, lookback_days=7)
        if not df.empty:
            erow = df.iloc[0]
            for col in df.columns:
                if col not in row or (isinstance(row.get(col), float) and pd.isna(row[col])):
                    row[col] = erow[col]
            for json_col, dest_key in [
                ("recommended_actions_json", "recommended_actions"),
                ("uncertainty_notes_json",   "uncertainty_notes"),
                ("hypothesis_chain_json",    "hypothesis_chain"),
                ("causal_chain_json",        "causal_chain"),  # legacy fallback
            ]:
                if json_col in erow.index:
                    raw = erow[json_col]
                    if raw and not (isinstance(raw, float) and pd.isna(raw)):
                        try:
                            row[dest_key] = _json.loads(raw)
                        except Exception:
                            row[dest_key] = []
                    else:
                        row.setdefault(dest_key, [])
    except Exception:
        pass
    return row


# ---------------------------------------------------------------------------
# List view
# ---------------------------------------------------------------------------

_DIALOG_CSS = """
<style>
/* ── Responsive dialog sizing ────────────────────────────────────────────
   Streamlit hardcodes "large" dialogs to 80rem (~1280px). Override to
   viewport-relative units so the dialog scales on any screen size.

   SCROLL FIX: the dialog box itself is the scroll container.
   Previously we relied on > div:last-child which is fragile across
   Streamlit versions. Making [role="dialog"] overflow-y:auto directly
   is simpler and works regardless of inner nesting depth.
──────────────────────────────────────────────────────────────────────── */

/* Dialog box: 85 % wide, at most 88 % tall, scrollable */
div[data-testid="stDialog"] [role="dialog"] {
    width:      85vw    !important;
    max-width:  85vw    !important;
    max-height: 88vh    !important;
    overflow-y: auto    !important;   /* dialog itself scrolls */
    overflow-x: hidden  !important;
}

/* Belt-and-suspenders: also enable scroll on every known Streamlit
   content-wrapper variant so whichever one Streamlit renders will work. */
div[data-testid="stDialog"] [role="dialog"] > div,
div[data-testid="stDialog"] [role="dialog"] > div > div,
div[data-testid="stDialog"] div[data-testid="stVerticalBlock"],
div[data-testid="stDialog"] div[data-testid="stVerticalBlockBorderWrapper"] {
    overflow-y: visible !important;   /* don't double-clip; let dialog scroll */
    overflow-x: hidden  !important;
}

/* Reposition the close (✕) button to match the narrower right edge */
div[data-testid="stDialog"] [role="dialog"] button[aria-label="Close"] {
    right: 1.5rem !important;
    position: sticky !important;
    top: 0 !important;
    z-index: 10 !important;
}
</style>
"""

_SORT_OPTIONS = {
    "Newest first":       ("created_at",  False),
    "Oldest first":       ("created_at",  True),
    "Highest risk first": ("risk_score",  False),
    "Lowest risk first":  ("risk_score",  True),
}


def _render_list(df: pd.DataFrame) -> None:
    """Paginated inbox list as a selectable dataframe.

    Sorting is done server-side (session state) so sort order survives reruns.
    Dialog open/close is tracked by insight_id — no key rotation needed, so
    the table widget is stable and never flickers on row click.
    """
    # ── Server-side sort ───────────────────────────────────────────────────
    sort_label = st.selectbox(
        "Sort by",
        list(_SORT_OPTIONS.keys()),
        index=0,
        key="ib_sort",
        label_visibility="collapsed",
    )
    sort_col, sort_asc = _SORT_OPTIONS[sort_label]
    if sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=sort_asc).reset_index(drop=True)

    total   = len(df)
    page    = st.session_state.get("ib_page", 0)
    n_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page    = min(page, n_pages - 1)
    start   = page * PAGE_SIZE
    end     = min(start + PAGE_SIZE, total)

    page_df = df.iloc[start:end].reset_index(drop=True)

    display_df = pd.DataFrame({
        " ":       page_df["risk_level"].map(_RISK_DOT).fillna("⚪"),
        "Place":   page_df.apply(_row_location, axis=1),
        "Insight": page_df["finding"].astype(str),
        "When":    page_df["created_at"].apply(_time_ago),
    })

    # Stable key — never rotated.  Dialog reopen prevention is handled by
    # tracking the last-opened insight_id instead of resetting the widget.
    event = st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        height=520,
        on_select="rerun",
        selection_mode="single-row",
        key="ib_table",
        column_config={
            " ":       st.column_config.TextColumn(" ",       width=40),
            "Place":   st.column_config.TextColumn("Place",   width=180),
            "Insight": st.column_config.TextColumn("Insight"),
            "When":    st.column_config.TextColumn("When",    width=90),
        },
    )

    sel = event.selection.rows
    if sel:
        orig_idx  = start + sel[0]
        row_data  = df.iloc[orig_idx]
        selected_id = str(row_data.get("insight_id", orig_idx))

        # Open dialog only for a *new* selection.
        # When the dialog closes, Streamlit reruns and the row may still be
        # highlighted — we skip reopening so the user must click again to reopen.
        if st.session_state.get("ib_open_for") != selected_id:
            st.session_state["ib_open_for"] = selected_id
            row = _load_full_row(row_data.to_dict())
            _insight_dialog(row)
    else:
        # Row deselected — allow the same row to reopen next time it's clicked.
        st.session_state.pop("ib_open_for", None)

    # ── Pagination ─────────────────────────────────────────────────────────
    if n_pages > 1:
        pg1, pg2, pg3 = st.columns([1, 5, 1])
        with pg1:
            if st.button("← Prev", key="ib_prev_page", disabled=(page == 0),
                         use_container_width=True):
                st.session_state["ib_page"] = page - 1
                st.rerun()
        with pg2:
            st.caption(
                f"Page {page + 1} of {n_pages}  ·  "
                f"showing {start + 1}–{end} of {total} insights"
            )
        with pg3:
            if st.button("Next →", key="ib_next_page",
                         disabled=(page >= n_pages - 1),
                         use_container_width=True):
                st.session_state["ib_page"] = page + 1
                st.rerun()
    else:
        st.caption(f"{total} insight{'s' if total != 1 else ''}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render_inbox_panel() -> None:
    from airos.os.city_config import CITIES as _CITY_REGISTRY

    # Inject responsive dialog CSS + row styling once per render
    st.markdown(_DIALOG_CSS, unsafe_allow_html=True)

    # ── Filter bar (REVIEW_CONTRACT §Required Filters) ────────────────────
    # Spec requires: Priority tier | Domain | Time window
    f1, f2, f3, f4, f5, f6 = st.columns([2, 1, 1, 1, 3, 1])
    with f1:
        city_opts  = {"All cities": None} | {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
        city_label = st.selectbox("City", list(city_opts.keys()), key="ib_city",
                                  label_visibility="collapsed")
        city_id    = city_opts[city_label]
    with f2:
        # REVIEW_CONTRACT §Required Filters: Priority tier filter
        tier_opts = {"All tiers": None, "High": "high", "Medium": "medium", "Low": "low"}
        tier_label = st.selectbox("Priority", list(tier_opts.keys()), key="ib_tier",
                                  label_visibility="collapsed")
        priority_tier = tier_opts[tier_label]
    with f3:
        # REVIEW_CONTRACT §Required Filters: Time window — 24h / 48h / 7d / custom
        days = st.selectbox("Window", [1, 2, 7, 30, 90], index=2,
                            format_func=lambda d: {1: "24h", 2: "48h"}.get(d, f"{d}d"),
                            key="ib_days", label_visibility="collapsed")
    with f4:
        # Toggle between open-only (default inbox view) and all statuses
        outcome_opts = {"Open only": "open", "All": None}
        outcome_label = st.selectbox("Status", list(outcome_opts.keys()), key="ib_outcome",
                                     label_visibility="collapsed")
        outcome_filter = outcome_opts[outcome_label]
    with f5:
        # REVIEW_CONTRACT §Required Filters: Domain filter
        all_domains = ["air","water","noise","fire","heat","flood","construction","green","waste"]
        dom_filter  = st.multiselect("Domains", all_domains, key="ib_domains",
                                     placeholder="All domains", label_visibility="collapsed")
    with f6:
        if st.button("↺ Refresh", key="ib_refresh", use_container_width=True):
            st.cache_data.clear()

    # Reset page when filters change
    new_filter_state = {
        "city_id": city_id, "days": days, "tier": priority_tier,
        "outcome": outcome_filter, "domains": dom_filter,
    }
    if st.session_state.get("ib_filter_state") != new_filter_state:
        st.session_state["ib_page"] = 0
    st.session_state["ib_filter_state"] = new_filter_state

    df = _load_insights(
        city_id=city_id,
        min_confidence=0,
        domains=dom_filter or None,
        days_back=days,
        priority_tier=priority_tier,
        outcome_status=outcome_filter,
    )

    if df.empty:
        _render_empty_state(city_id, _CITY_REGISTRY)
        return

    n_high   = int((df["priority_tier"] == "high").sum())
    n_medium = int((df["priority_tier"] == "medium").sum())
    n_low    = int((df["priority_tier"] == "low").sum())
    avg_conf = df["confidence"].mean() if "confidence" in df.columns else 0.0
    oldest   = pd.to_datetime(df["created_at"], utc=True, errors="coerce").min()
    latest   = pd.to_datetime(df["created_at"], utc=True, errors="coerce").max()
    _status_label = f" · {outcome_filter}" if outcome_filter else " · all statuses"
    st.caption(
        f"{len(df)} insights{_status_label} · "
        f"**{n_high} high · {n_medium} medium · {n_low} low** · "
        f"avg conf {avg_conf:.0%} · oldest {_time_ago(oldest)} · latest {_time_ago(latest)}"
    )

    _render_list(df)
