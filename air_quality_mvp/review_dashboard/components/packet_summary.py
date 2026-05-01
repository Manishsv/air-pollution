from __future__ import annotations

import streamlit as st


def _row(label: str, value: str) -> None:
    st.markdown(f"**{label}**  \n{value}")


def render_packet_summary(packet: dict, *, title: str | None = None):
    pred = packet.get("prediction") or {}
    conf = packet.get("confidence") or {}
    prov = packet.get("provenance") or {}

    if title:
        st.subheader(title)
    else:
        st.subheader("Review Summary")

    forecast_mean = pred.get("forecast_pm25_mean", "—")
    category = pred.get("pm25_category_india", "—")
    confidence_level = packet.get("confidence_level", "—")
    confidence_score = conf.get("confidence_score", "—")
    handling = packet.get("actionability_level", "—")
    aq_type = prov.get("aq_source_type", "—")
    next_step = packet.get("recommended_action", "—")

    _row("Forecast PM2.5", f"{forecast_mean} µg/m³" if forecast_mean not in {"—", None, ""} else "—")
    _row("Category", str(category))
    _row("Confidence", f"{confidence_level} ({confidence_score})")
    _row("Suggested handling", str(handling))
    _row("Air-quality data type", str(aq_type))
    _row("Suggested next step", str(next_step))

    with st.expander("Technical identifiers", expanded=False):
        st.caption(f"Technical ID: {packet.get('packet_id', '')}")
        st.write(
            {
                "packet_id": packet.get("packet_id"),
                "event_id": packet.get("event_id"),
                "h3_id": packet.get("h3_id"),
                "timestamp": packet.get("timestamp"),
            }
        )

    st.markdown("**Why this recommendation**")
    why = str(packet.get("why_this_recommendation", "") or "")
    # Business-friendly, sentence case framing
    if why and why[:1].islower():
        why = why[:1].upper() + why[1:]
    # Add conservative estimate disclaimer when AQ is interpolated/synthetic
    try:
        aqst = str(prov.get("aq_source_type") or "").lower()
    except Exception:
        aqst = ""
    if aqst in {"interpolated", "synthetic"} and "estimated" not in why.lower():
        why = (
            f"{why}\n\nPM2.5 is forecast to remain in the {str(category).title()} category, "
            "but the value is estimated from nearby stations. Field verification is recommended before taking action."
        ).strip()
    st.write(why)

    roe = packet.get("risk_of_error") or []
    if roe:
        st.markdown("**Risk of error**")
        for r in roe:
            st.write(f"- {r}")

