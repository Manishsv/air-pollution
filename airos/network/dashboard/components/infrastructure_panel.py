"""Urban Infrastructure panel — H3 knowledge store signals for buildings, roads, drains, crowd.

Reads OSM-derived structural signals from the H3 knowledge store and renders
per-city, per-domain summary tables and a map layer.  This panel is informational;
it does not produce alerts or recommendations — those come from the H3 Expert Agent.
"""
from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from airos.network.dashboard.ui_shell import (
    render_domain_header,
    render_context_metrics,
    render_section_title,
)

logger = logging.getLogger(__name__)

# Infrastructure domains and their key signal for the summary map
_INFRA_DOMAINS = {
    "buildings": {
        "label":       "Buildings",
        "icon":        "🏢",
        "key_signal":  "BUILDING_DENSITY",
        "key_unit":    "bldgs/km²",
        "signals":     ["BUILDING_COUNT", "BUILDING_DENSITY", "AVG_FLOORS", "COMMERCIAL_RATIO"],
        "description": "OSM building footprints — density, floor count, commercial mix. Refreshed quarterly.",
        "live":        False,
    },
    "roads": {
        "label":       "Roads",
        "icon":        "🛣️",
        "key_signal":  "ROAD_DENSITY",
        "key_unit":    "m/km²",
        "signals":     ["ROAD_LENGTH_M", "ROAD_DENSITY", "MAJOR_ROAD_RATIO", "INTERSECTION_COUNT"],
        "description": "OSM road network — length, density, major-road fraction, intersections. Refreshed quarterly.",
        "live":        False,
    },
    "drains": {
        "label":       "Drains",
        "icon":        "🌊",
        "key_signal":  "FLOOD_DRAIN_CAPACITY",
        "key_unit":    "index",
        "signals":     ["DRAIN_LENGTH_M", "WATERWAY_COUNT", "OPEN_DRAIN_RATIO", "FLOOD_DRAIN_CAPACITY"],
        "description": "OSM waterways — drain length, open vs covered ratio, flood capacity proxy. Refreshed quarterly.",
        "live":        False,
    },
    "crowd": {
        "label":       "Crowd / Live",
        "icon":        "👥",
        "key_signal":  "CROWD_DENSITY",
        "key_unit":    "people/km²",
        "signals":     ["PEOPLE_COUNT", "CAMERA_COUNT", "CROWD_DENSITY", "CROWD_INDEX", "GATHERING_ALERT"],
        "description": "Live CCTV camera people_count aggregated per H3 cell — 15-min cadence. Cells with no camera coverage are not shown.",
        "live":        True,
    },
}


def _load_infra_signals(city_id: str, domain: str) -> pd.DataFrame:
    """Pull the latest signal snapshot from the H3 knowledge store for one domain."""
    try:
        from airos.drivers.store.store import H3KnowledgeStore
        store = H3KnowledgeStore.get()
        df = store.fetchdf(
            """
            SELECT s.h3_id, s.signal_name AS signal, s.value, s.unit,
                   s.recorded_at
            FROM h3_signals s
            JOIN h3_cell_metadata m ON m.h3_id = s.h3_id
            WHERE m.city_id = ?
              AND s.domain   = ?
              AND s.recorded_at = (
                  SELECT MAX(s2.recorded_at)
                  FROM h3_signals s2
                  WHERE s2.h3_id       = s.h3_id
                    AND s2.domain      = s.domain
                    AND s2.signal_name = s.signal_name
              )
            ORDER BY s.h3_id, s.signal_name
            """,
            [city_id, domain],
        )
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        logger.debug("Infrastructure signal load failed (%s/%s): %s", city_id, domain, exc)
        return pd.DataFrame()


def _pivot_signals(df: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    """Pivot long-form signal rows to a wide table (one row per H3 cell)."""
    if df.empty:
        return pd.DataFrame()
    df = df[df["signal"].isin(signals)].copy()
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index="h3_id", columns="signal", values="value", aggfunc="last")
    wide = wide.reset_index()
    # Reorder columns: h3_id first, then signals in declaration order
    ordered = ["h3_id"] + [s for s in signals if s in wide.columns]
    return wide[ordered]


def _domain_tab(city_id: str, domain: str, meta: dict) -> None:
    """Render one infrastructure domain sub-tab."""
    is_live = meta.get("live", False)

    # Header badge
    badge = "🔴 LIVE · 15-min" if is_live else "🗓️ Quarterly"
    st.caption(f"{badge} — {meta['description']}")

    raw = _load_infra_signals(city_id, domain)
    if raw.empty:
        ingest_cmd = f"python main.py --step ingest-h3 --domains {domain}"
        if is_live:
            st.info(
                f"No live crowd data found for **{city_id}**. "
                "Start the camera publisher and run the scheduler, or trigger manually:\n"
                f"`{ingest_cmd}`"
            )
            _render_camera_registry(city_id)
        else:
            st.info(
                f"No {meta['label'].lower()} signals found for **{city_id}**. "
                f"Run `{ingest_cmd}` to populate (first run may take several minutes)."
            )
        return

    # ── Summary metrics ────────────────────────────────────────────────────
    wide = _pivot_signals(raw, meta["signals"])
    key  = meta["key_signal"]

    cells_with_data = len(wide)
    key_col = wide[key] if key in wide.columns else pd.Series(dtype=float)

    avg_val = round(float(key_col.mean()), 2) if not key_col.empty else 0.0
    max_val = round(float(key_col.max()),  2) if not key_col.empty else 0.0

    # Latest ingest timestamp
    last_ts = "—"
    if "recorded_at" in raw.columns and not raw["recorded_at"].isna().all():
        last_ts = str(raw["recorded_at"].max())[:16].replace("T", " ") + " UTC"

    if is_live:
        # Extra live metrics
        alert_col = wide["GATHERING_ALERT"] if "GATHERING_ALERT" in wide.columns else pd.Series(dtype=float)
        gatherings = int((alert_col.fillna(0) >= 1.0).sum()) if not alert_col.empty else 0
        total_people = int(wide["PEOPLE_COUNT"].fillna(0).sum()) if "PEOPLE_COUNT" in wide.columns else 0
        render_context_metrics(
            ("Active camera cells", cells_with_data),
            ("Total people counted", total_people),
            ("Gathering alerts", gatherings),
            ("Last ingest", last_ts),
        )
        # Gathering alert callout
        if gatherings:
            alert_cells = wide[alert_col >= 1.0]["h3_id"].tolist() if not alert_col.empty else []
            st.error(
                f"🚨 **{gatherings} gathering alert(s)** detected in {city_id}. "
                f"Affected cells: {', '.join(alert_cells[:5])}"
                + (" …" if len(alert_cells) > 5 else "")
            )
    else:
        render_context_metrics(
            ("H3 cells with data", cells_with_data),
            (f"Avg {meta['key_signal']} ({meta['key_unit']})", avg_val),
            (f"Max {meta['key_signal']}", max_val),
            ("Last ingested", last_ts),
        )

    # ── Wide signal table ──────────────────────────────────────────────────
    render_section_title("Per-cell signals")
    if wide.empty:
        st.caption("No data to display.")
    else:
        display = wide.copy()
        for col in display.columns:
            if col == "h3_id":
                continue
            display[col] = display[col].apply(
                lambda v: round(float(v), 4) if v is not None and str(v) != "nan" else None
            )
        st.dataframe(display, hide_index=True, use_container_width=True)

    # ── Distribution of key signal ─────────────────────────────────────────
    if key in wide.columns and not key_col.empty:
        render_section_title(f"Distribution — {key}")
        st.bar_chart(
            key_col.dropna().reset_index(drop=True).rename(key),
            use_container_width=True,
            height=220,
        )

    # ── Live: camera registry summary ─────────────────────────────────────
    if is_live:
        _render_camera_registry(city_id)

    # ── Quarterly: coverage gap note ──────────────────────────────────────
    if not is_live and key in wide.columns:
        zero_cells = int((key_col.fillna(0) == 0).sum())
        if zero_cells > 0:
            st.caption(
                f"⚠️ {zero_cells} cell(s) have {key} = 0 — either genuinely empty "
                "or OSM coverage is incomplete."
            )


def _render_camera_registry(city_id: str) -> None:
    """Show the camera registry for this city in an expander."""
    try:
        from airos.drivers.registries.cameras import cameras_for_city
        reg = cameras_for_city(city_id)
    except Exception:
        return

    with st.expander(f"Camera registry — {city_id} ({len(reg)} cameras)", expanded=False):
        if reg.empty:
            st.caption(
                "No cameras registered for this city. "
                "Add entries to `data/config/camera_registry.json`."
            )
        else:
            cols = [c for c in ["entity_id", "location_name", "latitude", "longitude", "active"]
                    if c in reg.columns]
            st.dataframe(reg[cols], hide_index=True, use_container_width=True)
            st.caption("Edit `data/config/camera_registry.json` to add or deactivate cameras.")


def render_infrastructure_panel() -> None:
    """Main entry point — called from app.py."""
    render_domain_header(
        title="Urban Infrastructure",
        caption=(
            "OSM-derived structural signals used by the H3 Expert Agent as context for "
            "generating cross-domain insights.  These are not risk signals — they amplify "
            "or contextualise environmental risks (AQI, flood, heat, noise)."
        ),
        primary_alert=(
            "Infrastructure signals are ingested weekly from OpenStreetMap. "
            "Coverage may be incomplete in informal settlements."
        ),
        primary_alert_kind="info",
    )

    # City selector
    try:
        from airos.drivers.store.ingestor import ALL_CITIES
        cities = ALL_CITIES
    except Exception:
        cities = ["bangalore", "hyderabad", "mumbai", "delhi", "chennai", "pune"]

    city_id = st.selectbox(
        "City", cities, index=0, key="infra_panel_city",
    )

    # Domain sub-tabs
    tab_labels = [f"{m['icon']} {m['label']}" for m in _INFRA_DOMAINS.values()]
    tabs = st.tabs(tab_labels)

    for tab, (domain, meta) in zip(tabs, _INFRA_DOMAINS.items()):
        with tab:
            _domain_tab(city_id, domain, meta)
