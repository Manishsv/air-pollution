from __future__ import annotations

import streamlit as st


def render_filters():
    with st.expander("Filters", expanded=True):
        category = st.selectbox("PM2.5 category", options=["(any)", "good", "satisfactory", "moderate", "poor", "very_poor", "severe"], index=0)
        confidence_level = st.selectbox("Confidence level", options=["(any)", "low", "medium", "high"], index=0)
        actionability_level = st.selectbox("Suggested handling", options=["(any)", "blocked", "verify_only", "advisory", "operational"], index=0)
        aq_source_type = st.selectbox("Air-quality data type", options=["(any)", "real", "interpolated", "synthetic", "unavailable"], index=0)
        recommendation_allowed = st.selectbox("Operational recommendations enabled", options=["(any)", "true", "false"], index=0)
        min_conf = st.slider("Minimum confidence", min_value=0.0, max_value=1.0, value=0.0, step=0.05)

    return {
        "category": None if category == "(any)" else category,
        "confidence_level": None if confidence_level == "(any)" else confidence_level,
        "actionability_level": None if actionability_level == "(any)" else actionability_level,
        "aq_source_type": None if aq_source_type == "(any)" else aq_source_type,
        "recommendation_allowed": None if recommendation_allowed == "(any)" else (recommendation_allowed == "true"),
        "min_confidence": float(min_conf),
    }

