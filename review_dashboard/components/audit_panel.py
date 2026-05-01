from __future__ import annotations

import streamlit as st


def render_audit_panel(audit: dict, metrics: dict):
    st.subheader("System Data Quality")
    st.caption("These indicators describe how much the system should be trusted for this run.")

    rel = audit.get("source_reliability_summary") or {}
    active = int(audit.get("number_of_real_aq_stations", 0) or 0)
    degraded = int(rel.get("degraded_count", 0) or 0) + int(rel.get("suspect_count", 0) or 0) + int(rel.get("offline_count", 0) or 0)

    rows = [
        ("Active AQ sensors", str(int(audit.get("number_of_real_aq_stations", 0) or 0))),
        ("Estimated grid cells", f"{float(audit.get('percent_cells_interpolated', 0.0) or 0.0):.1f}%"),
        ("Synthetic/test data", f"{float(audit.get('percent_cells_synthetic', 0.0) or 0.0):.1f}%"),
        ("Average distance to sensor", f"{float(audit.get('avg_nearest_station_distance_km', 0.0) or 0.0):.2f} km"),
        ("Sensors active / degraded", f"{active} / {degraded}"),
        ("Validation error (RMSE)", f"{float(metrics.get('spatial_validation_rmse', 0.0) or 0.0):.2f}"),
        ("Operational recommendations enabled", "Yes" if bool(audit.get("recommendation_allowed", True)) else "No"),
    ]

    for k, v in rows:
        st.markdown(f"**{k}**  \n{v}")

    if not bool(audit.get("recommendation_allowed", True)):
        br = str(audit.get("recommendation_block_reason", "") or "")
        if br:
            st.warning(br)

