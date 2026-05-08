"""H3 Expert Agent panel — run Claude agents and view cross-domain insights."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from urban_platform.city_config import CITIES as _CITY_REGISTRY, get_bbox
from review_dashboard.ui_shell import (
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)

_CONFIDENCE_EMOJI = {
    (0.8, 1.0): "🟢",
    (0.6, 0.8): "🟡",
    (0.4, 0.6): "🟠",
    (0.0, 0.4): "🔴",
}

def _conf_emoji(conf: float) -> str:
    for (lo, hi), emoji in _CONFIDENCE_EMOJI.items():
        if lo <= conf <= hi:
            return emoji
    return "⚪"


def _store_available() -> bool:
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().is_available()
    except Exception:
        return False


def _get_high_risk_cells(city_id: str, limit: int = 30) -> pd.DataFrame:
    """Return cells with high/severe assessments in the past 3 days."""
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().fetchdf(
            """
            SELECT h3_id,
                   string_agg(domain || '=' || risk_level, ', ' ORDER BY domain) AS domains_summary,
                   count(*) AS high_count
            FROM h3_assessments
            WHERE city_id = ?
              AND risk_level IN ('high', 'severe')
              AND day_bucket >= current_date - INTERVAL '3 days'
            GROUP BY h3_id
            ORDER BY high_count DESC
            LIMIT ?
            """,
            [city_id, limit],
        )
    except Exception:
        return pd.DataFrame()


def _get_recent_insights(city_id: str, limit: int = 50) -> pd.DataFrame:
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().fetchdf(
            """
            SELECT insight_id, h3_id, agent_type, created_at,
                   domains_involved, finding, confidence, causal_chain_json
            FROM h3_insights
            WHERE city_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [city_id, limit],
        )
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_agent_panel() -> None:
    render_domain_header(
        title="H3 Expert Agent",
        caption=(
            "Claude-powered agents that analyse each H3 cell holistically across all domains, "
            "detecting compound risks and causal chains that single-domain rules cannot see."
        ),
        primary_alert=(
            "Agents require an ANTHROPIC_API_KEY environment variable and consume API credits. "
            "Each agent run analyses one cell across all domains using Claude."
        ),
        primary_alert_kind="info",
    )

    if not _store_available():
        st.error(
            "H3 Knowledge Store is not available. "
            "Run `python main.py --step ingest-h3` first to populate the store.",
            icon="❌",
        )
        return

    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # ── Controls ────────────────────────────────────────────────────────
    c1, c2 = st.columns([2, 2])
    with c1:
        city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
        city_label = st.selectbox("City", list(city_options.keys()), key="agent_city")
        city_id = city_options[city_label]
    with c2:
        model = st.selectbox(
            "Claude model",
            ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
            index=0,
            key="agent_model",
            help="Opus = best reasoning, Haiku = fastest/cheapest for testing",
        )

    # ── Tabs: Run Agent | View Insights ─────────────────────────────────
    t_run, t_insights = st.tabs(["▶ Run Agent", "💡 View Insights"])

    # ──────────────────────────────────────────────────────────────────
    with t_run:
        render_section_title("Select a cell to analyse")

        run_mode = st.radio(
            "Cell selection",
            ["Top risk cells (automatic)", "Enter H3 cell ID manually"],
            horizontal=True,
            key="agent_run_mode",
        )

        h3_id_to_run: str | None = None
        top_n = 1

        if run_mode == "Enter H3 cell ID manually":
            h3_id_input = st.text_input(
                "H3 cell ID",
                placeholder="e.g. 8a1b00000007fff",
                key="agent_h3_input",
            )
            if h3_id_input.strip():
                h3_id_to_run = h3_id_input.strip()

        else:
            high_risk_df = _get_high_risk_cells(city_id)
            if high_risk_df.empty:
                st.info(
                    "No high-risk cells found in the knowledge store for this city. "
                    "Run the ingestor first: `python main.py --step ingest-h3`"
                )
            else:
                top_n = st.slider("Number of cells to analyse", 1, min(5, len(high_risk_df)), 1,
                                  key="agent_top_n")
                st.dataframe(high_risk_df, hide_index=True, use_container_width=True)
                if not high_risk_df.empty:
                    h3_id_to_run = high_risk_df["h3_id"].iloc[0]  # preview first cell

        lookback = st.slider("Signal lookback (days)", 3, 30, 7, key="agent_lookback")

        if not api_key_set:
            st.warning(
                "ANTHROPIC_API_KEY is not set. Set it in your `.env` file to run agents.",
                icon="🔑",
            )

        can_run = api_key_set and (h3_id_to_run or run_mode == "Top risk cells (automatic)")

        col_run, col_note = st.columns([1, 3])
        with col_run:
            run_clicked = st.button(
                "▶ Run Agent",
                disabled=not can_run,
                type="primary",
                key="agent_run_btn",
            )
        with col_note:
            if not api_key_set:
                st.caption("Set ANTHROPIC_API_KEY to enable.")
            else:
                st.caption("Each run calls Claude and uses API credits.")

        if run_clicked and can_run:
            if run_mode == "Top risk cells (automatic)":
                with st.spinner(f"Running H3 Expert Agent on top-{top_n} risk cells…"):
                    try:
                        from urban_platform.agents.h3_expert import run_top_risk_cells
                        results = run_top_risk_cells(
                            city_id, top_n=top_n, model=model,
                        )
                        if not results:
                            st.info("No eligible cells found or all cells have recent insights.")
                        else:
                            st.success(f"✅ Analysed {len(results)} cells")
                            for r in results:
                                _render_insight_card(r)
                    except Exception as exc:
                        st.error(f"Agent run failed: {exc}")
            else:
                with st.spinner(f"Running H3 Expert Agent on {h3_id_to_run}…"):
                    try:
                        from urban_platform.agents.h3_expert import H3ExpertAgent
                        agent = H3ExpertAgent(
                            h3_id=h3_id_to_run,
                            city_id=city_id,
                            model=model,
                            signals_lookback_days=lookback,
                        )
                        result = agent.run()
                        st.success("✅ Analysis complete")
                        _render_insight_card(result)
                    except Exception as exc:
                        st.error(f"Agent run failed: {exc}")

    # ──────────────────────────────────────────────────────────────────
    with t_insights:
        render_section_title("Recent agent insights")

        insights_df = _get_recent_insights(city_id)
        if insights_df.empty:
            st.info(
                "No agent insights yet for this city. "
                "Run the agent above to generate the first batch."
            )
            return

        # Summary stats
        col1, col2, col3 = st.columns(3)
        col1.metric("Total insights", len(insights_df))
        if "confidence" in insights_df.columns:
            col2.metric("Avg confidence", f"{insights_df['confidence'].mean():.0%}")
        if "created_at" in insights_df.columns:
            latest = pd.to_datetime(insights_df["created_at"], utc=True, errors="coerce").max()
            col3.metric("Latest", latest.strftime("%Y-%m-%d %H:%M") if pd.notna(latest) else "—")

        st.divider()

        # Filter
        if "domains_involved" in insights_df.columns:
            all_domains = sorted(set(
                d.strip()
                for val in insights_df["domains_involved"].dropna()
                for d in str(val).split(",")
                if d.strip()
            ))
            domain_filter = st.multiselect(
                "Filter by domain", all_domains, default=[], key="agent_domain_filter"
            )
        else:
            domain_filter = []

        display_df = insights_df.copy()
        if domain_filter:
            mask = display_df["domains_involved"].apply(
                lambda v: any(d in str(v) for d in domain_filter) if pd.notna(v) else False
            )
            display_df = display_df[mask]

        # Table
        show_cols = [c for c in ["created_at", "h3_id", "domains_involved",
                                  "finding", "confidence"] if c in display_df.columns]
        st.dataframe(display_df[show_cols], hide_index=True, use_container_width=True)

        st.divider()
        render_section_title("Insight detail")

        if not display_df.empty:
            ids = display_df["insight_id"].tolist()
            sel_id = st.selectbox("Select insight", ids, key="agent_insight_sel",
                                  format_func=lambda x: x[:16] + "…")
            row = display_df[display_df["insight_id"] == sel_id].iloc[0].to_dict()

            causal_chain = []
            if row.get("causal_chain_json"):
                try:
                    causal_chain = json.loads(row["causal_chain_json"])
                except Exception:
                    pass

            _render_insight_card({
                "insight_id": row.get("insight_id"),
                "h3_id": row.get("h3_id"),
                "city_id": city_id,
                "created_at": str(row.get("created_at", "")),
                "finding": row.get("finding", ""),
                "confidence": float(row.get("confidence") or 0),
                "domains_involved": str(row.get("domains_involved", "")).split(","),
                "causal_chain": causal_chain,
            })


# ---------------------------------------------------------------------------
# Shared insight card renderer
# ---------------------------------------------------------------------------

def _render_insight_card(insight: dict) -> None:
    conf = float(insight.get("confidence") or 0)
    emoji = _conf_emoji(conf)
    finding = insight.get("finding", "")
    domains = insight.get("domains_involved") or []
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]

    with st.container(border=True):
        # Header row
        hcol1, hcol2 = st.columns([4, 1])
        with hcol1:
            st.markdown(f"**{finding}**")
            if domains:
                st.caption("Domains: " + " · ".join(f"`{d}`" for d in domains))
        with hcol2:
            st.metric("Confidence", f"{emoji} {conf:.0%}")

        st.caption(
            f"Cell: `{insight.get('h3_id', '?')}` · "
            f"City: {insight.get('city_id', '?')} · "
            f"Generated: {str(insight.get('created_at', ''))[:16]}"
        )

        # Causal chain
        causal_chain = insight.get("causal_chain") or []
        if causal_chain:
            with st.expander("Causal chain", expanded=True):
                for step in causal_chain:
                    if isinstance(step, dict):
                        n = step.get("step", "")
                        ev = step.get("evidence", "")
                        inf = step.get("inference", "")
                        st.markdown(f"**{n}.** {ev}")
                        if inf:
                            st.markdown(f"   → _{inf}_")
                    else:
                        st.markdown(f"- {step}")

        # Recommended actions
        actions = insight.get("recommended_actions") or []
        if actions:
            with st.expander("Recommended actions"):
                for a in actions:
                    st.markdown(f"- {a}")

        # Uncertainty notes
        notes = insight.get("uncertainty_notes") or []
        if notes:
            with st.expander("Uncertainty / caveats"):
                for n in notes:
                    st.markdown(f"- {n}")

        # Raw JSON
        render_technical_json_expander(
            title="Technical: raw insight payload",
            payload={k: v for k, v in insight.items()
                     if k not in ("causal_chain_json",)},
        )
