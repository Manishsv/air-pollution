"""Raw Data Explorer — source-centric view of all H3 knowledge store signals.

Replaces the old domain-tab Data Explorer.  Each tab maps to ONE data source
(CPCB sensors, OpenMeteo, FIRMS, Sentinel-2 GEE, OSM, CCTV cameras, Noise sensors)
and shows:
  • Ingest status (last run, staleness, rows written)
  • Signal coverage (cells with data, DATA_CONFIDENCE distribution)
  • Latest signal table (pivot: h3_id × signal names)
  • Methodology note (how raw→H3 mapping works for this source)

No decision packets. No H3 resolution sliders.
All data is read from H3KnowledgeStore — no pipeline re-execution.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from datetime import datetime, timezone, timedelta

from review_dashboard.ui_shell import render_domain_header, render_section_title

from urban_platform.city_config import CITIES as _CITY_REGISTRY

# ---------------------------------------------------------------------------
# Source catalogue
# ---------------------------------------------------------------------------

_DATA_SOURCES: dict[str, dict] = {
    "air_sensors": {
        "emoji": "🌬️",
        "label": "Air Sensors",
        "subtitle": "CPCB / AQICN / OpenMeteo Air Quality",
        "domains": ["air"],
        "key_signals": ["AQI", "PM25", "PM10", "NO2", "DATA_CONFIDENCE", "NEAREST_OBS_KM"],
        "cadence": "Hourly",
        "methodology": (
            "Point observations from CPCB / AQICN sensor network. "
            "IDW (inverse distance weighting, 1/d²) interpolates values to all H3 cell centroids. "
            "Cells >3 km from any sensor get DATA_CONFIDENCE < 0.6."
        ),
        "coverage_note": "Confidence degrades with distance from nearest sensor.",
        "conf_floor": 0.50,
    },
    "weather": {
        "emoji": "🌧️",
        "label": "Weather",
        "subtitle": "OpenMeteo — temperature, rainfall, wind",
        "domains": ["weather"],
        "key_signals": ["TEMP_C", "HUMIDITY_PCT", "WIND_SPEED_MS", "WIND_DIR_DEG", "RAINFALL_MM"],
        "cadence": "Hourly",
        "methodology": (
            "OpenMeteo grid model output. City-centre point queried; same value applied to all cells "
            "(no spatial variation within the city bbox). "
            "RAINFALL_MM is the primary input to flood risk."
        ),
        "coverage_note": "Grid model — no sensor-distance degradation.",
        "conf_floor": 0.85,
    },
    "fire_firms": {
        "emoji": "🔥",
        "label": "Fire — FIRMS",
        "subtitle": "NASA VIIRS / MODIS active fire detections",
        "domains": ["fire"],
        "key_signals": ["FRP_MW", "FIRE_SCORE", "DATA_CONFIDENCE"],
        "cadence": "Every 3 hours",
        "methodology": (
            "MODIS active fire product (1 km pixels) and VIIRS 375 m pixels. "
            "Each pixel centroid → h3.latlng_to_cell(lat, lon, 8). "
            "FRP (fire radiative power in MW) is summed per cell. "
            "Only fires with FRP ≥ 5 MW are written."
        ),
        "coverage_note": "Cloud cover limits detection. Confidence = 0.80.",
        "conf_floor": 0.60,
    },
    "satellite_gee": {
        "emoji": "🛰️",
        "label": "Satellite — Sentinel-2",
        "subtitle": "GEE: heat · flood · water quality · green cover · construction · waste",
        "domains": ["heat", "flood", "water", "green", "construction", "waste"],
        "key_signals": [
            "HEAT_RISK_SCORE", "LST_CELSIUS", "NDVI",
            "FLOOD_RISK_INDEX", "WATER_QUALITY_INDEX", "MNDWI",
            "GCCI", "CONSTRUCTION_RISK_INDEX", "WASTE_RISK_INDEX",
            "DATA_CONFIDENCE",
        ],
        "cadence": "Daily (clear-sky dependent)",
        "methodology": (
            "Sentinel-2 Level-2A surface reflectance (10–60 m) processed via Google Earth Engine. "
            "Multiple pixels per H3 res-8 cell (~0.74 km²) are averaged. "
            "Key indices: NDVI (vegetation), LST (thermal), MNDWI (water body), "
            "BSI (bare soil), FAI (floating algae), NDTI (turbidity)."
        ),
        "coverage_note": "10-day revisit cycle; cloud cover reduces availability during monsoon.",
        "conf_floor": 0.40,
    },
    "osm": {
        "emoji": "🗺️",
        "label": "OpenStreetMap",
        "subtitle": "Building footprints · road network · waterways — quarterly",
        "domains": ["buildings", "roads", "drains"],
        "key_signals": [
            "BUILDING_COUNT", "BUILDING_DENSITY", "AVG_FLOORS",
            "ROAD_LENGTH_M", "ROAD_DENSITY", "MAJOR_ROAD_RATIO", "INTERSECTION_COUNT",
            "DRAIN_LENGTH_M", "FLOOD_DRAIN_CAPACITY", "OPEN_DRAIN_RATIO",
            "DATA_CONFIDENCE",
        ],
        "cadence": "Quarterly",
        "methodology": (
            "OSM Overpass API queried for the city bounding box. "
            "Buildings: polygon centroid → latlng_to_cell. "
            "Roads/drains: UTM-projected line-clip per cell (STRtree index + shapely intersection). "
            "Length in true metres via EPSG:32643/32644 projection."
        ),
        "coverage_note": "Roads 0.85, Buildings 0.75, Drains 0.65 (informal drains often unmapped).",
        "conf_floor": 0.50,
    },
    "cctv_cameras": {
        "emoji": "📷",
        "label": "CCTV Cameras",
        "subtitle": "Camera analytics — people_count (real-time, 15-min cadence)",
        "domains": ["crowd"],
        "key_signals": ["PEOPLE_COUNT", "CAMERA_COUNT", "CROWD_DENSITY", "CROWD_INDEX", "GATHERING_ALERT"],
        "cadence": "Every 15 minutes",
        "methodology": (
            "Camera analytics publisher writes people_count to observation_store.parquet. "
            "Camera registry (data/config/camera_registry.json) maps entity_id → lat/lon. "
            "Each camera → latlng_to_cell(lat, lon, 8). "
            "Only cells with ≥1 active camera are written (absent ≠ zero crowd)."
        ),
        "coverage_note": "0.90 for active camera cells. Coverage = camera footprint only.",
        "conf_floor": 0.80,
    },
    "noise_sensors": {
        "emoji": "🔊",
        "label": "Noise Sensors",
        "subtitle": "Ambient noise monitoring network",
        "domains": ["noise"],
        "key_signals": ["LAeq_DB", "NOISE_RISK_INDEX", "RECEPTOR_PROXIMITY", "DATA_CONFIDENCE"],
        "cadence": "Hourly",
        "methodology": (
            "Noise sensor network + proximity model for known sources (traffic corridors, "
            "construction zones, industrial areas). IDW interpolation to H3 cell centroids. "
            "NRI combines dB level (0.6 weight) with receptor proximity index (0.4 weight)."
        ),
        "coverage_note": "Sensor density varies significantly by city.",
        "conf_floor": 0.40,
    },
}

_STALENESS_THRESHOLDS = {
    "air_sensors":    timedelta(hours=2),
    "weather":        timedelta(hours=2),
    "fire_firms":     timedelta(hours=6),
    "satellite_gee":  timedelta(days=2),
    "osm":            timedelta(days=7),
    "cctv_cameras":   timedelta(minutes=30),
    "noise_sensors":  timedelta(hours=2),
}


# ---------------------------------------------------------------------------
# Data loading (reads from H3KnowledgeStore)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_ingest_log(city_id: str, domains: tuple[str, ...]) -> pd.DataFrame:
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        s = H3KnowledgeStore.get()
        if not domains:
            return pd.DataFrame()
        ph = ",".join(["?" for _ in domains])
        return s.fetchdf(
            f"SELECT domain, last_ingested_at, rows_written, status, error_msg "
            f"FROM h3_ingest_log WHERE city_id = ? AND domain IN ({ph})",
            [city_id, *domains],
        )
    except Exception as e:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _load_signals(city_id: str, domains: tuple[str, ...]) -> pd.DataFrame:
    """Latest signal value per (h3_id, domain, signal)."""
    try:
        from urban_platform.h3_knowledge.store import H3KnowledgeStore
        s = H3KnowledgeStore.get()
        if not domains:
            return pd.DataFrame()
        ph = ",".join(["?" for _ in domains])
        return s.fetchdf(
            f"""
            SELECT s.h3_id, s.domain, s.signal, s.value, s.unit, s.hour_bucket, s.source
            FROM h3_signals s
            INNER JOIN (
                SELECT h3_id, domain, signal, MAX(hour_bucket) AS max_hb
                FROM h3_signals
                WHERE city_id = ? AND domain IN ({ph})
                GROUP BY h3_id, domain, signal
            ) latest
              ON  s.h3_id      = latest.h3_id
              AND s.domain     = latest.domain
              AND s.signal     = latest.signal
              AND s.hour_bucket = latest.max_hb
            WHERE s.city_id = ?
            ORDER BY s.h3_id, s.domain, s.signal
            """,
            [city_id, *domains, city_id],
        )
    except Exception as e:
        return pd.DataFrame()


def _pivot_signals(signals_df: pd.DataFrame, key_signals: list[str]) -> pd.DataFrame:
    """Pivot long-form signals to wide (h3_id × signal), filtered to key_signals."""
    if signals_df.empty:
        return pd.DataFrame()
    present = [s for s in key_signals if s in signals_df["signal"].values]
    if not present:
        present = signals_df["signal"].unique().tolist()[:10]
    filtered = signals_df[signals_df["signal"].isin(present)]
    try:
        wide = filtered.pivot_table(
            index="h3_id", columns="signal", values="value", aggfunc="last"
        ).reset_index()
        # Round numeric columns
        for col in wide.columns:
            if col != "h3_id":
                wide[col] = wide[col].round(4)
        return wide
    except Exception:
        return filtered[["h3_id", "domain", "signal", "value", "unit", "hour_bucket"]]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _staleness_badge(last_ingested_at_str: str | None, threshold: timedelta) -> str:
    if not last_ingested_at_str:
        return "🔴 Never ingested"
    try:
        ts = datetime.fromisoformat(str(last_ingested_at_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        age_str = _fmt_age(age)
        if age <= threshold:
            return f"🟢 Fresh — {age_str} ago"
        elif age <= threshold * 3:
            return f"🟡 Stale — {age_str} ago"
        else:
            return f"🔴 Very stale — {age_str} ago"
    except Exception:
        return f"⚪ Unknown ({last_ingested_at_str})"


def _fmt_age(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:    return f"{secs}s"
    if secs < 3600:  return f"{secs // 60}m"
    if secs < 86400: return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _render_ingest_cards(ingest_df: pd.DataFrame, domains: list[str]) -> None:
    if ingest_df.empty:
        st.info("No ingest records yet. Run `python main.py --step ingest-h3` to populate.")
        return
    cols = st.columns(min(len(domains), 4))
    for i, domain in enumerate(domains):
        row = ingest_df[ingest_df["domain"] == domain]
        with cols[i % len(cols)]:
            if row.empty:
                st.metric(domain.title(), "Never run")
            else:
                r = row.iloc[0]
                status  = str(r.get("status", "—"))
                rows_wr = int(r.get("rows_written", 0) or 0)
                last_at = str(r.get("last_ingested_at", ""))
                st.metric(
                    domain.title(),
                    f"{rows_wr:,} rows",
                    delta=last_at[:16].replace("T", " ") + " UTC" if last_at else "—",
                    delta_color="off",
                )
                err = r.get("error_msg")
                if err:
                    st.caption(f"⚠️ {err}")


def _render_coverage_summary(signals_df: pd.DataFrame, conf_floor: float) -> None:
    if signals_df.empty:
        st.caption("No signals in store for this source / city combination.")
        return

    total_cells = signals_df["h3_id"].nunique()
    conf_rows   = signals_df[signals_df["signal"] == "DATA_CONFIDENCE"]
    avg_conf    = round(conf_rows["value"].mean(), 3) if not conf_rows.empty else None
    low_conf    = int((conf_rows["value"] < conf_floor).sum()) if not conf_rows.empty else 0
    domains_present = sorted(signals_df["domain"].unique().tolist())
    latest_hb = signals_df["hour_bucket"].max() if "hour_bucket" in signals_df.columns else "—"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("H3 cells with data", f"{total_cells:,}")
    c2.metric("Avg DATA_CONFIDENCE", f"{avg_conf:.2f}" if avg_conf is not None else "—")
    c3.metric("Low-confidence cells", str(low_conf),
              help=f"Cells with DATA_CONFIDENCE < {conf_floor}")
    c4.metric("Latest bucket", str(latest_hb)[:16].replace("T", " ") if latest_hb else "—")

    if len(domains_present) > 1:
        st.caption(f"Domains in this source group: {', '.join(domains_present)}")


def _render_signal_table(signals_df: pd.DataFrame, key_signals: list[str]) -> None:
    if signals_df.empty:
        st.caption("No signals yet — run the H3 ingestor for this domain.")
        return

    wide = _pivot_signals(signals_df, key_signals)
    if wide.empty:
        st.dataframe(
            signals_df[["h3_id", "domain", "signal", "value", "unit", "hour_bucket"]].head(200),
            hide_index=True, use_container_width=True,
        )
        return

    # Truncate h3_id for readability
    if "h3_id" in wide.columns:
        wide["h3_id"] = wide["h3_id"].astype(str).str[:16] + "…"

    # Column order: h3_id first, then key signals in order
    ordered_cols = ["h3_id"] + [c for c in key_signals if c in wide.columns]
    remaining = [c for c in wide.columns if c not in ordered_cols]
    wide = wide[ordered_cols + remaining]

    st.dataframe(wide.head(200), hide_index=True, use_container_width=True)
    if len(wide) == 200:
        total = signals_df["h3_id"].nunique()
        st.caption(f"Showing 200 of {total} cells.")


def _render_methodology(source_meta: dict) -> None:
    with st.expander("📐 How raw data maps to H3 cells", expanded=False):
        st.markdown(f"**Cadence:** {source_meta['cadence']}")
        st.markdown(f"**Mapping method:** {source_meta['methodology']}")
        st.markdown(f"**Coverage note:** {source_meta['coverage_note']}")


def _render_source_tab(city_id: str, source_key: str) -> None:
    meta       = _DATA_SOURCES[source_key]
    domains    = tuple(meta["domains"])
    threshold  = _STALENESS_THRESHOLDS.get(source_key, timedelta(hours=24))

    st.caption(meta["subtitle"])

    # ── Ingest status ─────────────────────────────────────────────────────
    render_section_title("Ingest status")
    ingest_df = _load_ingest_log(city_id, domains)
    _render_ingest_cards(ingest_df, list(domains))

    # Per-domain staleness badges
    if not ingest_df.empty:
        for _, row in ingest_df.iterrows():
            badge = _staleness_badge(str(row.get("last_ingested_at", "")), threshold)
            st.markdown(f"**{row['domain'].title()}** — {badge}")

    st.divider()

    # ── Signal coverage ────────────────────────────────────────────────────
    render_section_title("Signal coverage")
    with st.spinner("Loading signals from H3 store…"):
        signals_df = _load_signals(city_id, domains)
    _render_coverage_summary(signals_df, meta["conf_floor"])

    st.divider()

    # ── Signal table ───────────────────────────────────────────────────────
    render_section_title("Latest signals per cell")
    st.caption(
        "Latest value per signal per H3 cell (all domains combined for this source). "
        "Pivot table — rows are cells, columns are signals."
    )
    _render_signal_table(signals_df, meta["key_signals"])

    # ── Methodology ────────────────────────────────────────────────────────
    _render_methodology(meta)

    # ── Confidence distribution ────────────────────────────────────────────
    conf_rows = signals_df[signals_df["signal"] == "DATA_CONFIDENCE"] if not signals_df.empty else pd.DataFrame()
    if not conf_rows.empty:
        with st.expander("DATA_CONFIDENCE distribution", expanded=False):
            st.bar_chart(
                conf_rows["value"].round(2).value_counts().sort_index(),
                height=150,
            )
            st.caption(
                "Each bar = count of cells with that confidence score. "
                "Scores below 0.6 indicate poor sensor/satellite coverage."
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_raw_data_panel() -> None:
    render_domain_header(
        title="Raw Data Explorer",
        caption=(
            "Source-centric view of all signals in the H3 Knowledge Store. "
            "Each tab maps to one data source — shows ingest health, cell coverage, "
            "and the latest signal values. No decision logic runs here."
        ),
        primary_alert=None,
    )

    # City selector
    city_options = {v["display_name"]: k for k, v in _CITY_REGISTRY.items()}
    city_label   = st.selectbox("City", list(city_options.keys()), key="raw_data_city")
    city_id      = city_options[city_label]

    # ── Refresh button ─────────────────────────────────────────────────────
    if st.button("🔄 Refresh", key="raw_data_refresh"):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # ── Source tabs ────────────────────────────────────────────────────────
    source_keys  = list(_DATA_SOURCES.keys())
    tab_labels   = [f"{_DATA_SOURCES[k]['emoji']} {_DATA_SOURCES[k]['label']}" for k in source_keys]
    tabs         = st.tabs(tab_labels)

    for tab, source_key in zip(tabs, source_keys):
        with tab:
            _render_source_tab(city_id, source_key)
