from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_domain_header(
    *,
    title: str,
    caption: str,
    primary_alert: str | None = None,
    primary_alert_kind: str = "error",
    domain: str | None = None,
) -> None:
    """H2-style domain title, caption, optional prominent alert, and an
    optional maturity badge sourced from `airos.os.domain_maturity`.

    When `domain` is supplied, the badge appears next to the title with a
    colour-coded tier (production / pilot / synthetic) and, for non-prod
    tiers, the caveat is surfaced below the caption as an info strip so
    the user sees it without having to dig into the methodology doc.
    """
    if domain:
        try:
            from airos.os.domain_maturity import get_domain_maturity
            mat = get_domain_maturity(domain)
        except Exception:
            mat = None
    else:
        mat = None

    if mat:
        badge_html = (
            f'<span style="display:inline-block;padding:2px 10px;'
            f'border-radius:12px;font-size:11px;font-weight:600;'
            f'background:{mat["color"]}22;color:{mat["color"]};'
            f'border:1px solid {mat["color"]}44;'
            f'margin-left:10px;vertical-align:middle;">'
            f'{mat["label"]}</span>'
        )
        st.markdown(
            f'## {title}{badge_html}',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f"## {title}")

    st.caption(caption)

    # Surface non-production caveats prominently below the caption so the
    # user sees them without having to read the methodology doc.
    if mat and mat.get("caveat") and not mat["tier"].startswith("prod_") or (
        mat and mat["tier"] == "prod_proxy" and mat.get("caveat")
    ):
        if mat["tier"] in ("pilot_proxy", "deployment_dependent", "synthetic_demo"):
            st.warning(f"⚠ {mat['caveat']}", icon="⚠️")
        elif mat["tier"] == "prod_proxy":
            st.caption(f"ℹ {mat['caveat']}")

    if primary_alert:
        if primary_alert_kind == "warning":
            st.warning(primary_alert)
        elif primary_alert_kind == "info":
            st.info(primary_alert)
        else:
            st.error(primary_alert)


def render_context_metrics(*metrics: tuple[str, Any]) -> None:
    """Render a row of st.metric from (label, value) pairs."""
    if not metrics:
        return
    cols = st.columns(len(metrics))
    for i, (label, val) in enumerate(metrics):
        cols[i].metric(label, str(val) if val is not None else "—")


def render_section_title(title: str) -> None:
    st.markdown(f"### {title}")


def render_empty_state(message: str, *, hint: str | None = None) -> None:
    st.info(message)
    if hint:
        st.caption(hint)


def render_technical_json_expander(
    *,
    title: str = "Technical: Raw data",
    payload: Any,
    expanded: bool = False,
) -> None:
    with st.expander(title, expanded=expanded):
        st.json(payload)


def render_browse_detail_layout(
    *,
    browse: Callable[[], None],
    detail: Callable[[], None],
    left_ratio: float = 0.62,
) -> None:
    """Standard two-pane review layout (browse left, detail right)."""
    right_ratio = round(1.0 - left_ratio, 2)
    left, right = st.columns([left_ratio, right_ratio], gap="large")
    with left:
        browse()
    with right:
        detail()
