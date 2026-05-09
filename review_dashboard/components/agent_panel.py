"""H3 Expert Agent panel — run LLM agents and view cross-domain insights.

The LLM provider is fully configurable — Ollama (local), Groq, OpenAI,
Together, OpenRouter, LM Studio, or any OpenAI-compatible endpoint.
No API key is required for Ollama.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from urban_platform.city_config import CITIES as _CITY_REGISTRY
from urban_platform.agents.llm_config import (
    PROVIDER_PRESETS, ALL_PROVIDERS, load_config, LLMConfig,
)
from review_dashboard.ui_shell import (
    render_domain_header,
    render_section_title,
    render_technical_json_expander,
)

_CONFIDENCE_EMOJI = {
    (0.8, 1.01): "🟢",
    (0.6, 0.8):  "🟡",
    (0.4, 0.6):  "🟠",
    (0.0, 0.4):  "🔴",
}

def _conf_emoji(conf: float) -> str:
    for (lo, hi), emoji in _CONFIDENCE_EMOJI.items():
        if lo <= conf < hi:
            return emoji
    return "⚪"


# ---------------------------------------------------------------------------
# LLM config UI — returns an LLMConfig built from UI controls
# ---------------------------------------------------------------------------

def render_llm_settings(*, key_prefix: str = "llm") -> LLMConfig:
    """Render LLM provider settings and return the current LLMConfig.

    Call this wherever agent controls are needed.  Uses st.session_state to
    persist across rerenders without losing the user's choices.
    """
    # Load defaults from env vars on first render
    env_cfg = load_config()

    with st.expander("⚙️ LLM provider settings", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            provider_labels = {k: v["label"] for k, v in PROVIDER_PRESETS.items()}
            selected_label = st.selectbox(
                "Provider",
                options=list(provider_labels.values()),
                index=list(provider_labels.keys()).index(env_cfg.provider)
                      if env_cfg.provider in provider_labels else 0,
                key=f"{key_prefix}_provider_label",
            )
            # Map label back to key
            provider = next(k for k, v in provider_labels.items()
                            if v == selected_label)
            preset = PROVIDER_PRESETS[provider]
            st.caption(preset.get("notes", ""))

        with col2:
            model = st.text_input(
                "Model",
                value=env_cfg.model if env_cfg.provider == provider
                      else preset["default_model"],
                key=f"{key_prefix}_model",
                placeholder=preset["default_model"],
                help="Model name as the provider expects it.",
            )

        col3, col4 = st.columns(2)
        with col3:
            base_url = st.text_input(
                "Base URL",
                value=env_cfg.base_url if env_cfg.provider == provider
                      else preset["base_url"],
                key=f"{key_prefix}_base_url",
                help="OpenAI-compatible /v1 endpoint. Change only for custom setups.",
            )
        with col4:
            api_key_default = (
                env_cfg.api_key
                if env_cfg.provider == provider and env_cfg.api_key not in ("no-key", "")
                else preset.get("api_key", "")
            )
            api_key = st.text_input(
                "API key",
                value=api_key_default,
                key=f"{key_prefix}_api_key",
                type="password",
                help="Leave as 'ollama' for local Ollama. Not shown after entry.",
                placeholder="ollama" if provider == "ollama" else "sk-...",
            )

        col5, col6, col7 = st.columns(3)
        with col5:
            max_tokens = st.number_input(
                "Max tokens", min_value=256, max_value=32768,
                value=env_cfg.max_tokens, step=256,
                key=f"{key_prefix}_max_tokens",
            )
        with col6:
            temperature = st.slider(
                "Temperature", 0.0, 1.0,
                value=env_cfg.temperature, step=0.05,
                key=f"{key_prefix}_temperature",
                help="Lower = more deterministic. 0.1 recommended for analysis tasks.",
            )
        with col7:
            timeout = st.number_input(
                "Timeout (s)", min_value=10, max_value=600,
                value=env_cfg.timeout, step=10,
                key=f"{key_prefix}_timeout",
            )

        # Test connection button
        if st.button("🔌 Test connection", key=f"{key_prefix}_test_btn"):
            cfg_test = LLMConfig(
                provider=provider, base_url=base_url,
                api_key=api_key or "no-key", model=model or preset["default_model"],
                max_tokens=64, temperature=0.0, timeout=15,
            )
            with st.spinner("Testing…"):
                from urban_platform.agents.llm_client import LLMClient
                ok, msg = LLMClient(cfg_test).test_connection()
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

    return LLMConfig(
        provider=provider,
        base_url=base_url or preset["base_url"],
        api_key=api_key or preset.get("api_key", "no-key"),
        model=model or preset["default_model"],
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        timeout=int(timeout),
    )


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _store_available() -> bool:
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().is_available()
    except Exception:
        return False


def _get_high_risk_cells(city_id: str, limit: int = 30) -> pd.DataFrame:
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        return H3KnowledgeStore.get().fetchdf(
            """
            SELECT h3_id,
                   GROUP_CONCAT(domain || '=' || risk_level) AS domains_summary,
                   count(*) AS high_count
            FROM h3_assessments
            WHERE city_id = ?
              AND risk_level IN ('high', 'severe')
              AND day_bucket >= date('now', '-3 days')
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
# Main panel
# ---------------------------------------------------------------------------

def render_agent_panel() -> None:
    render_domain_header(
        title="H3 Expert Agent",
        caption=(
            "LLM-powered agents that analyse each H3 cell holistically across all domains, "
            "detecting compound risks and causal chains invisible to single-domain rules. "
            "Works with Ollama (local, free), Groq, OpenAI, Together, OpenRouter, or any "
            "OpenAI-compatible endpoint."
        ),
        primary_alert=None,
    )

    if not _store_available():
        st.error(
            "H3 Knowledge Store unavailable. "
            "Run `python main.py --step ingest-h3` to populate it first.",
            icon="❌",
        )
        return

    # ── City selector ────────────────────────────────────────────────
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    city_label   = st.selectbox("City", list(city_options.keys()), key="agent_city")
    city_id      = city_options[city_label]

    # ── Tabs ─────────────────────────────────────────────────────────
    t_run, t_insights = st.tabs(["▶ Run Agent", "💡 View Insights"])

    with t_run:
        # LLM settings — inline, collapsible
        llm_cfg = render_llm_settings(key_prefix="agent_run")

        st.divider()
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
            h3_input = st.text_input(
                "H3 cell ID",
                placeholder="e.g. 8a1b00000007fff",
                key="agent_h3_input",
            )
            if h3_input.strip():
                h3_id_to_run = h3_input.strip()
        else:
            high_risk_df = _get_high_risk_cells(city_id)
            if high_risk_df.empty:
                st.info(
                    "No high-risk cells in the knowledge store for this city. "
                    "Run `python main.py --step ingest-h3` first."
                )
            else:
                top_n = st.slider(
                    "Number of cells to analyse", 1, min(5, len(high_risk_df)), 1,
                    key="agent_top_n",
                )
                st.dataframe(high_risk_df, hide_index=True, use_container_width=True)
                h3_id_to_run = high_risk_df["h3_id"].iloc[0]

        lookback = st.slider("Signal lookback (days)", 3, 30, 7, key="agent_lookback")

        # Show current provider summary
        st.caption(
            f"Provider: **{llm_cfg.label}** · Model: `{llm_cfg.model}` · "
            f"Base URL: `{llm_cfg.base_url}`"
        )

        run_clicked = st.button(
            "▶ Run Agent",
            type="primary",
            key="agent_run_btn",
            disabled=(run_mode == "Top risk cells (automatic)" and high_risk_df.empty
                      if run_mode == "Top risk cells (automatic)" else not h3_id_to_run),
        )

        if run_clicked:
            if run_mode == "Top risk cells (automatic)":
                with st.spinner(f"Running H3 Expert Agent on top-{top_n} risk cells via {llm_cfg.provider}…"):
                    try:
                        from urban_platform.agents.h3_expert import run_top_risk_cells
                        results = run_top_risk_cells(
                            city_id, top_n=top_n, config=llm_cfg,
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
                with st.spinner(f"Running H3 Expert Agent on `{h3_id_to_run}` via {llm_cfg.provider}…"):
                    try:
                        from urban_platform.agents.h3_expert import H3ExpertAgent
                        agent = H3ExpertAgent(
                            h3_id=h3_id_to_run,
                            city_id=city_id,
                            config=llm_cfg,
                            signals_lookback_days=lookback,
                        )
                        result = agent.run()
                        st.success(f"✅ Analysis complete — {result.get('provider')} / {result.get('model')}")
                        _render_insight_card(result)
                    except Exception as exc:
                        st.error(f"Agent run failed: {exc}")

    with t_insights:
        render_section_title("Recent agent insights")

        insights_df = _get_recent_insights(city_id)
        if insights_df.empty:
            st.info("No agent insights yet. Run the agent above to generate the first batch.")
            return

        col1, col2, col3 = st.columns(3)
        col1.metric("Total insights", len(insights_df))
        if "confidence" in insights_df.columns:
            col2.metric("Avg confidence", f"{insights_df['confidence'].mean():.0%}")
        if "created_at" in insights_df.columns:
            latest = pd.to_datetime(insights_df["created_at"], utc=True, errors="coerce").max()
            col3.metric("Latest", latest.strftime("%Y-%m-%d %H:%M") if pd.notna(latest) else "—")

        st.divider()

        all_domains = sorted(set(
            d.strip()
            for val in insights_df.get("domains_involved", pd.Series([], dtype=str)).dropna()
            for d in str(val).split(",")
            if d.strip()
        ))
        domain_filter = st.multiselect(
            "Filter by domain", all_domains, default=[], key="agent_domain_filter"
        )

        display_df = insights_df.copy()
        if domain_filter:
            mask = display_df["domains_involved"].apply(
                lambda v: any(d in str(v) for d in domain_filter) if pd.notna(v) else False
            )
            display_df = display_df[mask]

        show_cols = [c for c in ["created_at", "h3_id", "domains_involved", "finding", "confidence"]
                     if c in display_df.columns]
        st.dataframe(display_df[show_cols], hide_index=True, use_container_width=True)

        st.divider()
        render_section_title("Insight detail")

        if not display_df.empty:
            sel_id = st.selectbox(
                "Select insight", display_df["insight_id"].tolist(),
                key="agent_insight_sel",
                format_func=lambda x: x[:16] + "…",
            )
            row = display_df[display_df["insight_id"] == sel_id].iloc[0].to_dict()
            causal_chain = []
            if row.get("causal_chain_json"):
                try:
                    causal_chain = json.loads(row["causal_chain_json"])
                except Exception:
                    pass
            _render_insight_card({
                "insight_id":      row.get("insight_id"),
                "h3_id":           row.get("h3_id"),
                "city_id":         city_id,
                "created_at":      str(row.get("created_at", "")),
                "finding":         row.get("finding", ""),
                "confidence":      float(row.get("confidence") or 0),
                "domains_involved": str(row.get("domains_involved", "")).split(","),
                "causal_chain":    causal_chain,
            })


# ---------------------------------------------------------------------------
# Insight card — shared between Run and View tabs
# ---------------------------------------------------------------------------

def _render_insight_card(insight: dict) -> None:
    conf    = float(insight.get("confidence") or 0)
    finding = insight.get("finding", "")
    domains = insight.get("domains_involved") or []
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]

    with st.container(border=True):
        hcol1, hcol2 = st.columns([4, 1])
        with hcol1:
            st.markdown(f"**{finding}**")
            if domains:
                st.caption("Domains: " + " · ".join(f"`{d}`" for d in domains if d))
        with hcol2:
            st.metric("Confidence", f"{_conf_emoji(conf)} {conf:.0%}")

        provider = insight.get("provider", "")
        model    = insight.get("model", "")
        st.caption(
            f"Cell: `{insight.get('h3_id', '?')}` · "
            f"City: {insight.get('city_id', '?')} · "
            f"Generated: {str(insight.get('created_at', ''))[:16]}"
            + (f" · {provider}/{model}" if provider else "")
        )

        causal_chain = insight.get("causal_chain") or []
        if causal_chain:
            with st.expander("Causal chain", expanded=True):
                for step in causal_chain:
                    if isinstance(step, dict):
                        n   = step.get("step", "")
                        ev  = step.get("evidence", "")
                        inf = step.get("inference", "")
                        st.markdown(f"**{n}.** {ev}")
                        if inf:
                            st.markdown(f"   → _{inf}_")
                    else:
                        st.markdown(f"- {step}")

        actions = insight.get("recommended_actions") or []
        if actions:
            with st.expander("Recommended actions"):
                for a in actions:
                    st.markdown(f"- {a}")

        notes = insight.get("uncertainty_notes") or []
        if notes:
            with st.expander("Uncertainty / caveats"):
                for n in notes:
                    st.markdown(f"- {n}")

        render_technical_json_expander(
            title="Technical: raw insight payload",
            payload={k: v for k, v in insight.items() if k != "causal_chain_json"},
        )
