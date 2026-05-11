from __future__ import annotations

from typing import Any, Callable

import streamlit as st


def render_domain_header(
    *,
    title: str,
    caption: str,
    primary_alert: str | None = None,
    primary_alert_kind: str = "error",
) -> None:
    """H2-style domain title, caption, and optional prominent alert (error | warning | info)."""
    st.markdown(f"## {title}")
    st.caption(caption)
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
