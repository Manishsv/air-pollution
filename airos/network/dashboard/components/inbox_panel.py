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
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

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


def _format_chain_step(i: int, step) -> str:
    """Render one step of either the current (proposition/testable_by/confidence)
    or legacy (evidence/inference) chain shape into a single line for the LLM
    system prompt."""
    if not isinstance(step, dict):
        return f"  {i+1}. {step}"

    # Current shape — used by h3_expert agent
    proposition = step.get("proposition")
    testable    = step.get("testable_by")
    confidence  = step.get("confidence")

    # Legacy shape
    evidence    = step.get("evidence")
    inference   = step.get("inference")

    head = proposition or evidence or ""
    parts = [f"  {i+1}. {head}"]
    if confidence is not None:
        try:
            parts[0] += f" (conf {float(confidence):.0%})"
        except Exception:
            pass
    if testable:
        parts.append(f"     verifiable by: {testable}")
    elif inference:
        parts.append(f"     → {inference}")
    return "\n".join(parts)


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


def _cluster_similar(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse near-duplicate insights into one row per (location, pattern).

    The packet generator (insight_packets._spatially_thin) only sees insights
    once they become packets. The inbox shows raw insights, where adjacent
    cells in the same neighbourhood routinely produce 4–5 near-identical
    findings in a single sweep (IDW spatial smoothing + city-broadcast
    heat/weather — see methodology §4.4).

    We cluster by `(city, location_name, finding_signature, hour_bucket)`
    where `finding_signature` is the first ~50 chars of the finding text
    normalised. The top-ranked insight in each cluster is kept; an extra
    `cluster_count` column records how many were collapsed. The renderer
    shows this as `Nx Location, City — finding…`.
    """
    if df is None or df.empty:
        return df

    def _signature(s) -> str:
        """Return the primary pattern of a finding, ignoring numeric jitter and
        compound-domain modifiers. "Persistent air-heat-noise compound stress:
        PM2.5 spike (58 µg/m³, ↑391%…)" and "Persistent air-heat-green compound
        risk: PM2.5 spike (58.3 µg/m³, ↑396%…)" both collapse to
        "compound|pm25_spike" — same incident, different framing.
        """
        if not isinstance(s, str):
            return ""
        t = s.lower()
        tokens = []
        if "compound" in t:
            tokens.append("compound")
        if "pm2.5 spike" in t or "pm25 spike" in t:
            tokens.append("pm25_spike")
        if "wqi" in t or "water" in t:
            tokens.append("water")
        if "flood" in t:
            tokens.append("flood")
        if "heat" in t and "air-heat" not in t and "compound" not in t:
            tokens.append("heat")
        if "fire" in t or "frp" in t:
            tokens.append("fire")
        # Fall back to the first 24 chars if no recognised pattern fired —
        # better to under-cluster than to merge unrelated findings.
        return "|".join(tokens) if tokens else " ".join(t.split())[:24]

    def _hour_bucket(ts) -> str:
        try:
            return str(ts)[:13]  # YYYY-MM-DDTHH — group within the same hour
        except Exception:
            return ""

    work = df.copy()
    work["_sig"]  = work["finding"].map(_signature)
    work["_hour"] = work["created_at"].map(_hour_bucket)
    work["_loc"]  = work.apply(_row_location, axis=1)

    cluster_key = ["city_id", "_loc", "_sig", "_hour"]
    grouped = work.groupby(cluster_key, dropna=False, sort=False)
    sizes   = grouped.size().rename("cluster_count")
    # Keep the first row per cluster (df is already sorted by the caller's choice)
    out = work.drop_duplicates(subset=cluster_key, keep="first").merge(
        sizes, on=cluster_key, how="left"
    )
    return out.drop(columns=["_sig", "_hour", "_loc"]).reset_index(drop=True)


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
                        f'<div style="margin-left:18px;color:#6b7280;'
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

    # Surface the dossier timestamp + version so the user can reconcile
    # answers if the underlying signals changed between questions
    # (methodology §4.5). Compute lazily — we already build the dossier
    # inside the LLM call below; cheap to also do it once for display.
    try:
        from airos.os.cell_dossier import build_cell_dossier
        _preview = build_cell_dossier(
            str(insight.get("city_id")),
            str(insight.get("h3_id")),
        )
        _built_at = _preview.get("built_at", "")
        _ver      = (_preview.get("dossier_version") or "")[:12]
        if _built_at and _ver:
            st.caption(
                f"📋 Dossier built at {_built_at[:19]}Z · version `{_ver}` — "
                f"every chat answer is grounded in this signal snapshot."
            )
    except Exception:
        pass

    # Track whether the chat has ever been started for this insight. The
    # suggestion buttons are gated on BOTH (a) empty history AND (b) this
    # flag being False, so Streamlit cannot leave a stale button visible
    # after the conditional flips on rerun.
    started_key = f"chat_started_{scope}"
    chat_started = bool(st.session_state.get(started_key, False)) or bool(history)

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if not chat_started:
        st.caption("Suggested questions:")
        # Lay out as columns so all 3 buttons share one row, and the whole
        # block is unambiguously one UI element to hide on first interaction.
        sug_cols = st.columns(3)
        suggestions = [
            "Why is the confidence at this level?",
            "What would escalate this to critical?",
            "Draft a field inspection brief.",
        ]
        for col, sug in zip(sug_cols, suggestions):
            with col:
                if st.button(sug, key=f"sug_{scope}_{sug[:15]}",
                             use_container_width=True):
                    st.session_state[chat_key].append({"role": "user", "content": sug})
                    st.session_state[started_key] = True
                    st.session_state["ib_keep_open"] = True
                    st.rerun()

    if prompt := st.chat_input("Ask about this insight…", key=f"inp_{scope}"):
        st.session_state[chat_key].append({"role": "user", "content": prompt})
        st.session_state[started_key] = True
        st.session_state["ib_keep_open"] = True
        st.rerun()

    if history and history[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    from airos.agents.llm_client import LLMClient
                    from airos.os.cell_dossier import build_cell_dossier, format_dossier_for_prompt

                    domains  = _parse_domains(insight.get("domains_involved"))
                    # Current schema uses `hypothesis_chain_json`. Earlier
                    # writers wrote to `causal_chain_json` (kept as fallback
                    # for old data). Read both so the chat tab never sees an
                    # empty chain for an insight that actually has one.
                    chain    = _parse_chain(
                        insight.get("hypothesis_chain_json")
                        or insight.get("causal_chain_json")
                        or insight.get("hypothesis_chain")
                        or []
                    )
                    chain_tx = "\n".join(
                        _format_chain_step(i, s) for i, s in enumerate(chain)
                    )

                    # Pull the agent's structured outputs — the LLM should
                    # see what the agent already flagged so it validates
                    # against them instead of re-discovering them.
                    rec_actions = _parse_chain(insight.get("recommended_actions_json") or [])
                    uncertainty = _parse_chain(insight.get("uncertainty_notes_json") or [])

                    actions_tx = "\n".join(
                        f"  {i+1}. {a.get('action', a)}"
                        + (f"  [{a.get('urgency','')}, {a.get('actor','')}]"
                           if isinstance(a, dict) and (a.get('urgency') or a.get('actor')) else "")
                        for i, a in enumerate(rec_actions)
                    ) if rec_actions else ""

                    uncertainty_tx = "\n".join(
                        f"  - [{n.get('impact','medium')}] {n.get('note', n)}"
                        if isinstance(n, dict) else f"  - {n}"
                        for n in uncertainty
                    ) if uncertainty else ""

                    # Build full cell dossier — gives the LLM all signals,
                    # POI breakdown, cause hypotheses, and 7-day trend.
                    dossier_text = ""
                    try:
                        d = build_cell_dossier(
                            str(insight.get("city_id")),
                            str(insight.get("h3_id")),
                        )
                        dossier_text = format_dossier_for_prompt(d)
                    except Exception as exc:
                        logger.warning("Dossier build failed: %s", exc)

                    system = f"""You are an urban intelligence assistant helping a city officer
investigate the root cause of an environmental risk finding in one H3 cell.

Finding: {insight.get('finding')}
Agent confidence: {float(insight.get('confidence') or 0):.0%}
Insight domains: {', '.join(domains)}

Hypothesis chain from agent:
{chain_tx or '  (not recorded — agent did not emit a hypothesis chain)'}

Recommended actions the agent emitted:
{actions_tx or '  (none recorded — older insight pre-dating the schema change)'}

Uncertainty notes the agent explicitly flagged:
{uncertainty_tx or '  (none recorded)'}

You have a full dossier of cell signals below — refer to specific numbers
when you reason. The cause classifier's hypotheses are pre-computed; treat
them as evidence to validate or challenge, not as ground truth. The agent's
own uncertainty notes above are gaps the agent already knows about — do not
re-list them unless asked; use them as a starting point for deeper analysis.

When the user asks about root cause, structure your answer as:
1. Most likely cause (with the strongest 1–3 pieces of evidence from below)
2. Alternative hypothesis (what would have to be true)
3. What field check would discriminate between them
4. Specific data gaps that limit confidence (incremental to what the agent already flagged)

If asked to draft a brief or ticket, produce one. Be concise. Cite signal
values explicitly. Acknowledge uncertainty.

--- CELL DOSSIER ---
{dossier_text or '(dossier unavailable)'}
--- END DOSSIER ---"""

                    resp  = LLMClient(llm_cfg).chat(
                        [{"role": m["role"], "content": m["content"]} for m in history],
                        system=system, max_tokens=1500,
                    )
                    reply = resp.content or "(Empty response from model.)"
                except Exception as exc:
                    reply = f"⚠️ {exc}"
            st.markdown(reply)
        st.session_state[chat_key].append({"role": "assistant", "content": reply})
        # Keep the dialog open so the assistant reply is visible after rerun.
        st.session_state["ib_keep_open"] = True
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
            _STATUS_ICONS = {
                "confirmed":           "✅",
                "refuted":             "❌",
                "partially_confirmed": "◐",
                "unverifiable":        "❓",
            }
            icon = _STATUS_ICONS.get(outcome, "ℹ️")
            st.markdown(
                f'{icon} **{outcome.title()}** · closed by `{closed_by_val}` · {closed_label}',
            )
            # Four-way verdict layers (methodology §4.3) — show whichever
            # were captured. Older closures only have condition.
            _layer_pairs = [
                ("Condition", row.get("condition_verdict")),
                ("Cause",     row.get("cause_verdict")),
                ("Routing",   row.get("routing_verdict")),
                ("Action",    row.get("action_verdict")),
            ]
            _layer_pairs = [(n, v) for n, v in _layer_pairs if v]
            if _layer_pairs:
                st.markdown(
                    "  ".join(f"`{name}`: **{v}**" for name, v in _layer_pairs)
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
                    "Four orthogonal sub-verdicts (methodology §4.3) — only "
                    "**Condition** is required. The others are optional and help "
                    "the evaluation framework stratify failures by layer "
                    "(condition vs cause vs routing vs action)."
                )

                # REVIEW_CONTRACT §Reviewer Identity: closed_by MUST be non-empty.
                officer = st.text_input(
                    "Your officer ID",
                    key=f"officer_{llm_key_prefix}_{insight_id}",
                    placeholder="e.g. ward_engineer_42 or officer@city.gov",
                    help="Required. Must uniquely identify you within this deployment.",
                )

                # ── 1. Condition verdict (required) ───────────────────────
                st.markdown("**1. Condition verdict** — was the hypothesised condition observed?")
                condition_verdict = st.radio(
                    "condition_verdict",
                    ["confirmed", "refuted", "partially_confirmed", "unverifiable"],
                    format_func=lambda x: {
                        "confirmed":            "✓ Confirmed",
                        "refuted":              "✗ Refuted",
                        "partially_confirmed":  "◐ Partially confirmed",
                        "unverifiable":         "? Unverifiable",
                    }[x],
                    horizontal=True,
                    key=f"vc_cond_{llm_key_prefix}_{insight_id}",
                    label_visibility="collapsed",
                )

                # ── 2. Cause verdict (optional) ───────────────────────────
                st.markdown("**2. Cause verdict** — was the top cause hypothesis the right attribution? *(optional)*")
                cause_verdict = st.radio(
                    "cause_verdict",
                    ["—", "confirmed", "refuted", "partially_confirmed", "unverifiable"],
                    format_func=lambda x: {
                        "—":                    "Skip",
                        "confirmed":            "✓ Confirmed",
                        "refuted":              "✗ Refuted",
                        "partially_confirmed":  "◐ Partially",
                        "unverifiable":         "? Unverifiable",
                    }[x],
                    horizontal=True,
                    key=f"vc_cause_{llm_key_prefix}_{insight_id}",
                    label_visibility="collapsed",
                )

                # ── 3. Routing verdict (optional) ─────────────────────────
                st.markdown("**3. Routing verdict** — was the department in `routed_to` the right owner? *(optional)*")
                routing_verdict = st.radio(
                    "routing_verdict",
                    ["—", "correct", "incorrect", "joint_responsibility", "unknown"],
                    format_func=lambda x: {
                        "—":                    "Skip",
                        "correct":              "✓ Correct",
                        "incorrect":            "✗ Wrong department",
                        "joint_responsibility": "⇆ Joint responsibility",
                        "unknown":              "? Unknown",
                    }[x],
                    horizontal=True,
                    key=f"vc_route_{llm_key_prefix}_{insight_id}",
                    label_visibility="collapsed",
                )

                # ── 4. Action verdict (optional) ──────────────────────────
                st.markdown("**4. Action verdict** — was an action taken? *(optional)*")
                action_verdict = st.radio(
                    "action_verdict",
                    [
                        "—", "taken", "not_required", "escalated",
                        "not_taken_resource_limited", "not_taken_other",
                    ],
                    format_func=lambda x: {
                        "—":                          "Skip",
                        "taken":                      "✓ Taken",
                        "not_required":               "○ Not required",
                        "escalated":                  "↑ Escalated",
                        "not_taken_resource_limited": "✗ Blocked (resource)",
                        "not_taken_other":            "✗ Not taken (other)",
                    }[x],
                    horizontal=True,
                    key=f"vc_action_{llm_key_prefix}_{insight_id}",
                    label_visibility="collapsed",
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
                        # Treat "—" sentinels as None (not collected)
                        _norm = lambda v: None if v == "—" else v
                        AirOSClient().close_insight(
                            insight_id=insight_id,
                            outcome_status=condition_verdict,   # legacy field — mirrors condition
                            closed_by=officer.strip(),
                            condition_verdict=condition_verdict,
                            cause_verdict=_norm(cause_verdict),
                            routing_verdict=_norm(routing_verdict),
                            action_verdict=_norm(action_verdict),
                        )
                        _layers = [
                            ("Condition", condition_verdict),
                            ("Cause",     _norm(cause_verdict)),
                            ("Routing",   _norm(routing_verdict)),
                            ("Action",    _norm(action_verdict)),
                        ]
                        _summary = ", ".join(f"{name}={v}" for name, v in _layers if v)
                        st.success(f"Submitted: {_summary}. Thank you — this calibrates future analysis.")
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
        f'<div style="font-size:13px;color:#6b7280;">'
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
            f'<div style="border:0.5px solid rgba(128,128,128,0.25);border-radius:8px;'
            f'padding:12px 16px;">'
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:4px;">DATA PIPELINE</div>'
            f'<div style="font-size:13px;">'
            f'{"🟢" if ok_count else "🟡"} {ok_count} sources live'
            f'{f", {partial_count} degraded" if partial_count else ""}'
            f'</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:4px;">'
            f'Last pull: {last_ingest}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div style="border:0.5px solid rgba(128,128,128,0.25);border-radius:8px;'
            f'padding:12px 16px;">'
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:4px;">AI AGENT</div>'
            f'<div style="font-size:13px;">⏳ Waiting for scheduled run</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:4px;">'
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

/* Anchor the close (✕) button to the top-right of the dialog box.
   Earlier CSS used `position: sticky` which now drops the button at the
   bottom of the layout flow in current Streamlit DOM — pin it explicitly. */
div[data-testid="stDialog"] [role="dialog"] button[aria-label="Close"] {
    position: absolute !important;
    top:   0.75rem !important;
    right: 1.25rem !important;
    z-index: 10 !important;
}
/* The dialog needs a positioning context so absolute children anchor to it. */
div[data-testid="stDialog"] [role="dialog"] {
    position: relative !important;
}
</style>
"""

_SORT_OPTIONS = {
    "Newest first":       ("created_at",  False),
    "Oldest first":       ("created_at",  True),
    "Highest risk first": ("risk_score",  False),
    "Lowest risk first":  ("risk_score",  True),
}


_ROW_CSS = """
<style>
/* Inbox row buttons — scoped via the per-widget class Streamlit adds
   from the button's key (st-key-ib_row_<insight_id>). Affects only
   the row buttons, not pagination / refresh / other buttons. */
div[class*="st-key-ib_row_"] button {
    text-align: left !important;
    justify-content: flex-start !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 0.5px solid rgba(128,128,128,0.20) !important;
    border-radius: 0 !important;
    padding: 8px 12px !important;
    font-weight: 400 !important;
    min-height: 0 !important;
}
div[class*="st-key-ib_row_"] button:hover {
    background: rgba(128,128,128,0.10) !important;
}
/* Streamlit wraps button labels in nested <div>/<p> with centred flex —
   override both so the markdown text aligns left. */
div[class*="st-key-ib_row_"] button > div,
div[class*="st-key-ib_row_"] button > div > p,
div[class*="st-key-ib_row_"] button p {
    text-align: left !important;
    justify-content: flex-start !important;
    width: 100% !important;
    margin: 0 !important;
}
</style>
"""


def _render_list(df: pd.DataFrame) -> None:
    """Paginated inbox list as click-anywhere rows.

    Each row is a full-width button — clicking anywhere on the row opens
    the detail dialog. Sort selection lives in the unified filter bar
    rendered by `render_inbox_panel`; this function reads it from session
    state (`ib_sort`) and applies it.
    """
    # Sort value is set by the unified filter bar in render_inbox_panel.
    sort_label = st.session_state.get("ib_sort", next(iter(_SORT_OPTIONS)))
    sort_col, sort_asc = _SORT_OPTIONS.get(sort_label, ("created_at", False))
    if sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=sort_asc).reset_index(drop=True)

    # Collapse near-duplicate rows (methodology §4.4 similarity-bias mitigation)
    df = _cluster_similar(df)

    total   = len(df)
    page    = st.session_state.get("ib_page", 0)
    n_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page    = min(page, n_pages - 1)
    start   = page * PAGE_SIZE
    end     = min(start + PAGE_SIZE, total)

    page_df = df.iloc[start:end].reset_index(drop=True)

    # ── Click-anywhere row buttons ────────────────────────────────────────
    st.markdown(_ROW_CSS, unsafe_allow_html=True)

    just_clicked_id: str | None = None
    for i in range(len(page_df)):
        row = page_df.iloc[i]
        risk    = str(row.get("risk_level", "unknown") or "unknown")
        dot     = _RISK_DOT.get(risk, "⚪")
        place   = _row_location(row)
        finding = str(row.get("finding") or "")
        if len(finding) > 110:
            finding = finding[:110] + "…"
        when    = _time_ago(row.get("created_at"))
        insight_id = str(row.get("insight_id", f"row_{start + i}"))

        # Cluster badge — if this row represents N>1 similar insights collapsed
        # by `_cluster_similar`, prefix the label with the count so the user
        # knows the click opens the top-ranked of N near-duplicates.
        try:
            cc = int(row.get("cluster_count") or 1)
        except (TypeError, ValueError):
            cc = 1
        badge = f"**{cc}× **" if cc > 1 else ""
        # Button label supports markdown (bold, italic, emoji).
        label = f"{dot}  {badge}**{place}** — {finding}  ·  _{when}_"
        if st.button(
            label,
            key=f"ib_row_{insight_id}",
            use_container_width=True,
        ):
            just_clicked_id = insight_id
            st.session_state["ib_open_target"] = insight_id

    # ── Dialog open logic ─────────────────────────────────────────────────
    # Streamlit's @st.dialog closes whenever any widget inside it triggers a
    # rerun, *unless* we re-call the dialog function on the next run. Two
    # paths re-open it:
    #   (a) The user just clicked a row in this run.
    #   (b) A widget inside the dialog (suggested-question button, chat input,
    #       LLM-reply append) called st.rerun() and set `ib_keep_open` to ask
    #       us to keep showing the same insight.
    # The ✕ close button is handled implicitly — it doesn't set `ib_keep_open`
    # and doesn't trigger (a), so the dialog stays closed.
    keep_open = st.session_state.pop("ib_keep_open", False)
    target_id = just_clicked_id or (
        st.session_state.get("ib_open_target") if keep_open else None
    )
    if target_id:
        # Find the insight row across the full filtered df (not just the
        # current page) so pagination changes don't lose the dialog target.
        matching = df[df["insight_id"].astype(str) == target_id]
        if not matching.empty:
            opened_row = _load_full_row(matching.iloc[0].to_dict())
            _insight_dialog(opened_row)

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

    # ── Unified single-row toolbar ────────────────────────────────────────
    # City | Priority | Window | Status | Domains | Sort | View | ↺
    # All controls live on one row; the View toggle decides whether the
    # List renderer or the Map panel renders below the bar.
    fc_city, fc_tier, fc_win, fc_status, fc_doms, fc_sort, fc_view, fc_refresh = \
        st.columns([2.0, 1.1, 0.9, 1.1, 2.4, 1.6, 1.3, 0.6])

    with fc_city:
        city_opts  = {"All cities": None} | {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
        city_label = st.selectbox("City", list(city_opts.keys()), key="ib_city",
                                  label_visibility="collapsed")
        city_id    = city_opts[city_label]
    with fc_tier:
        tier_opts = {"All tiers": None, "High": "high", "Medium": "medium", "Low": "low"}
        tier_label = st.selectbox("Priority", list(tier_opts.keys()), key="ib_tier",
                                  label_visibility="collapsed")
        priority_tier = tier_opts[tier_label]
    with fc_win:
        days = st.selectbox("Window", [1, 2, 7, 30, 90], index=2,
                            format_func=lambda d: {1: "24h", 2: "48h"}.get(d, f"{d}d"),
                            key="ib_days", label_visibility="collapsed")
    with fc_status:
        outcome_opts = {"Open only": "open", "All": None}
        outcome_label = st.selectbox("Status", list(outcome_opts.keys()), key="ib_outcome",
                                     label_visibility="collapsed")
        outcome_filter = outcome_opts[outcome_label]
    with fc_doms:
        all_domains = ["air","water","noise","fire","heat","flood","construction","green","waste"]
        dom_filter  = st.multiselect("Domains", all_domains, key="ib_domains",
                                     placeholder="All domains", label_visibility="collapsed")
    with fc_sort:
        st.selectbox(
            "Sort by",
            list(_SORT_OPTIONS.keys()),
            index=0,
            key="ib_sort",
            label_visibility="collapsed",
        )
    with fc_view:
        view_choice = st.radio(
            "View",
            ["📋 List", "🗺️ Map"],
            horizontal=True,
            key="ib_view",
            label_visibility="collapsed",
        )
    with fc_refresh:
        if st.button("↺", key="ib_refresh", use_container_width=True, help="Clear cache and reload"):
            st.cache_data.clear()

    # ── Dispatch — Map view delegates to map_panel and returns ────────────
    if view_choice == "🗺️ Map":
        from airos.network.dashboard.components.map_panel import render_map_panel
        render_map_panel()
        return

    # ── List view — apply filters, reset pagination on change ────────────
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

    # City-broadcast weather banner — surfaces signals that are constant across
    # every cell so they are NOT repeated inside per-cell findings (methodology §4.4).
    _render_city_weather_banner(city_id)

    _render_list(df)


def _render_city_weather_banner(city_id: str | None) -> None:
    """Show one row of city-broadcast weather context above the inbox list.

    Pulls latest WIND/HUMIDITY/TEMPERATURE/PRECIP values per city. With no
    city filter selected, renders a row per city for which we have current
    data. The banner makes city-wide conditions visible once instead of
    showing up redundantly inside every per-cell "compound" finding.
    """
    import sqlite3
    from airos.drivers.store.schema import DB_PATH

    sigs = ("TEMPERATURE_C", "HUMIDITY_PCT", "WIND_SPEED_KMH", "WIND_DIR_DEG",
            "PRECIP_MM", "HEAT_INDEX_C")
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        # Pull median across cells per city (median to suppress IDW edge artefacts;
        # for true city-broadcast signals every cell has the same value anyway).
        placeholders = ",".join("?" * len(sigs))
        params: list = list(sigs)
        where_city = ""
        if city_id:
            where_city = " AND city_id = ?"
            params.append(city_id)
        rows = conn.execute(
            f"""
            SELECT city_id, signal, value FROM h3_signals
            WHERE signal IN ({placeholders}) AND value IS NOT NULL
              AND hour_bucket >= datetime('now', '-6 hours'){where_city}
            """,
            params,
        ).fetchall()
        conn.close()
    except Exception:
        return

    if not rows:
        return

    by_city: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        by_city.setdefault(r["city_id"], {}).setdefault(r["signal"], []).append(
            float(r["value"])
        )

    def _med(xs: list[float]) -> float | None:
        if not xs:
            return None
        s = sorted(xs); n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    def _wind_compass(deg: float | None) -> str:
        if deg is None:
            return ""
        compass = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
                   "S","SSW","SW","WSW","W","WNW","NW","NNW"]
        return compass[int((deg % 360) / 22.5 + 0.5) % 16]

    for cid, sig_map in by_city.items():
        t  = _med(sig_map.get("TEMPERATURE_C") or [])
        h  = _med(sig_map.get("HUMIDITY_PCT") or [])
        w  = _med(sig_map.get("WIND_SPEED_KMH") or [])
        wd = _med(sig_map.get("WIND_DIR_DEG") or [])
        p  = _med(sig_map.get("PRECIP_MM") or [])
        hi = _med(sig_map.get("HEAT_INDEX_C") or [])

        parts = []
        if t  is not None: parts.append(f"🌡 {t:.0f} °C")
        if hi is not None and hi > (t or 0) + 1: parts.append(f"feels {hi:.0f}")
        if h  is not None: parts.append(f"💧 {h:.0f}%")
        if w  is not None:
            parts.append(f"💨 {w:.0f} km/h {_wind_compass(wd)}".rstrip())
        if p  is not None and p > 0.0: parts.append(f"🌧 {p:.1f} mm")
        if not parts:
            continue
        st.caption(
            f"**{cid.title()}** city-wide today · " + " · ".join(parts)
            + "  ·  _shown once because these are constant across every cell_"
        )
