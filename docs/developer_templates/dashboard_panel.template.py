# Copy to: review_dashboard/components/<domain_name>_panel.py
# Wire from review_dashboard/app.py in a new tab.
#
# Presentation only: read payloads from disk or session; do not encode domain rules here.

from __future__ import annotations

from typing import Any

import streamlit as st


def render_domain_panel(demo_payload: dict[str, Any] | None) -> None:
    # After copy: rename file and function to render_<domain_name>_panel (valid identifier).
    st.markdown("## <domain_name> (template panel)")
    st.caption("Replace with business-readable copy. Keep technical JSON in collapsed expanders.")

    if not demo_payload:
        st.info("No payload loaded. Run your deployment demo and point this panel at outputs.")
        return

    headline = demo_payload.get("summary", {}).get("headline", "—")  # noqa: template example
    st.metric("Demo headline", str(headline))

    with st.expander("Technical: raw payload", expanded=False):
        st.json(demo_payload)
