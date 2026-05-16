"""City situational-awareness map — full-screen pydeck H3 view.

The landing view for AirOS dashboard. Per user spec:
  - Streamlit + pydeck (deck.gl H3HexagonLayer for GPU rendering)
  - Each H3 cell is shaded by the WORST risk_level across assessment
    domains for that cell ("auto-collapse to worst-risk-per-cell")
  - Point-event icons overlay for fire FRP, waste hotspots,
    crowd GATHERING_ALERT, flood high-risk
  - Cells with an open insight (tier ∈ high/medium/critical) get a
    coloured border (border colour = tier)
  - Click a cell → side panel with cell signals + insight if present
  - Hover → tooltip
  - Top-left: city dropdown overlay
  - Top-right (popover): layer toggles + legend

Stays inside Streamlit so it shares auth, session, city_config, etc.
Methodology §11 (Design Principles): translucent overlays so the
operator can always see the basemap underneath.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import h3
import pandas as pd
import pydeck as pdk
import streamlit as st

logger = logging.getLogger(__name__)


# ── Visual config (translucent overlays, methodology §11) ────────────────────

# Risk-tier RGB shading (alpha kept low so basemap shows through).
# Order matches the canonical 4-tier vocabulary (good/low/moderate/high/severe).
_RISK_FILL_RGBA: dict[str, tuple[int, int, int, int]] = {
    "good":     (88, 180, 90,  60),    # green
    "low":      (140, 200, 90, 60),    # yellow-green
    "moderate": (240, 200, 60, 90),    # yellow
    "high":     (240, 130, 50, 110),   # orange
    "severe":   (220, 50,  50, 130),   # red
    "unknown":  (160, 160, 160, 40),
}

# Insight-tier border colour (no fill — these draw on top of the shade layer).
_INSIGHT_BORDER_RGBA: dict[str, tuple[int, int, int, int]] = {
    "critical": (220, 0,   0,   220),
    "high":     (240, 120, 0,   220),
    "medium":   (240, 200, 0,   200),
    # low is intentionally excluded — only operationally meaningful insights
    # earn a border (per user spec choice (ii))
}

# Numeric severity rank — used to pick "worst risk" when multiple domains
# assess the same cell.
_RISK_RANK: dict[str, int] = {
    "good": 0, "low": 1, "unknown": 1, "moderate": 2, "high": 3, "severe": 4,
}

# Icon mapping for point-event domains. Uses public icons8 PNGs via CDN —
# no auth. Sizes are normalised in the IconLayer (size_units='pixels',
# get_size=18) so every icon renders at the same on-screen footprint
# regardless of map zoom, instead of fire icons dominating the view.
_ICON_ATLAS = {
    "fire":         {"url": "https://img.icons8.com/color/48/000000/fire-element.png",
                     "label": "Fire / FRP"},
    "waste":        {"url": "https://img.icons8.com/color/48/000000/biohazard.png",
                     "label": "Waste hotspot"},
    "crowd":        {"url": "https://img.icons8.com/color/48/000000/conference-call.png",
                     "label": "Crowd / gathering"},
    "flood":        {"url": "https://img.icons8.com/color/48/000000/wave.png",
                     "label": "Flood risk"},
    "construction": {"url": "https://img.icons8.com/color/48/000000/under-construction.png",
                     "label": "Construction"},
    "industrial":   {"url": "https://img.icons8.com/color/48/000000/factory.png",
                     "label": "Industrial cluster"},
    "mobility":     {"url": "https://img.icons8.com/color/48/000000/car--v2.png",
                     "label": "Major road / transit hub"},
    "wind":         {"url": "https://img.icons8.com/ios-filled/50/0e62b8/up--v1.png",
                     "label": "Wind direction"},
}

# Pixel size for every map icon — fixed so they stay readable but never
# dominate at high zoom-out (the IGP airshed view at zoom 5).
_ICON_PIXEL_SIZE = 18


def _db_path() -> str:
    from airos.drivers.store.schema import DB_PATH
    return str(DB_PATH)


def _ro_conn() -> sqlite3.Connection:
    """Thin wrapper around airos.drivers.store.schema.ro_connect — kept
    here so existing citymap-only call sites don't need to change.
    """
    from airos.drivers.store.schema import ro_connect
    return ro_connect()


# _filter_by_city_bbox removed — the spatial JOINs in the loaders above
# (h3_metadata.centroid_lat/lon BETWEEN bbox) make this defensive guard
# redundant. Out-of-bbox cells are now excluded at the query level.


# ── Data loaders (cached) ────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _load_worst_risk_per_cell(aoi_id: str) -> pd.DataFrame:
    """Per-cell worst risk_level across all assessment domains, filtered
    spatially to the AOI's bbox (city_id-agnostic — Phase 1 AOI lens).

    Reads the latest row per (h3_id, domain) from h3_assessments joined
    to h3_metadata for the centroid, and keeps the row whose risk_level
    has the highest severity per cell. Works identically for city,
    airshed, watershed and other AOI kinds — the bbox does the work.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = _ro_conn()
    try:
        rows = conn.execute(
            """
            SELECT a.h3_id, a.domain, a.risk_level, a.primary_index,
                   a.primary_value, a.dominant_issue,
                   COALESCE(m.area_name, '') AS area_name
            FROM h3_assessments a
            INNER JOIN h3_metadata m ON m.h3_id = a.h3_id
            INNER JOIN (
                SELECT h3_id, domain, MAX(day_bucket) AS db
                FROM h3_assessments
                GROUP BY h3_id, domain
            ) latest ON latest.h3_id = a.h3_id
                    AND latest.domain = a.domain
                    AND latest.db = a.day_bucket
            WHERE a.risk_level IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(
            columns=["h3_id", "risk_level", "dominant_domain",
                     "primary_index", "primary_value", "dominant_issue",
                     "area_name"]
        )
    df = pd.DataFrame([dict(r) for r in rows])
    df["risk_rank"] = df["risk_level"].map(_RISK_RANK).fillna(0)
    # Keep the highest-severity domain per cell.
    df = df.sort_values("risk_rank", ascending=False).drop_duplicates("h3_id")
    df = df.rename(columns={"domain": "dominant_domain"})
    return df.drop(columns=["risk_rank"]).reset_index(drop=True)


@st.cache_data(ttl=120, show_spinner=False)
def _load_open_insights_by_cell(aoi_id: str) -> pd.DataFrame:
    """One row per cell inside the AOI bbox with an open insight at tier
    ∈ {critical, high, medium}. Spatial filter (Phase 1 lens model).
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = _ro_conn()
    try:
        rows = conn.execute(
            """
            SELECT i.insight_id, i.h3_id, i.priority_tier, i.finding,
                   i.confidence, i.created_at,
                   COALESCE(m.area_name, '') AS area_name
            FROM h3_insights i
            INNER JOIN h3_metadata m ON m.h3_id = i.h3_id
            WHERE i.outcome_status = 'open'
              AND i.priority_tier IN ('critical', 'high', 'medium')
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            ORDER BY i.h3_id,
                CASE i.priority_tier
                    WHEN 'critical' THEN 0
                    WHEN 'high'     THEN 1
                    WHEN 'medium'   THEN 2
                END,
                i.created_at DESC
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame(
            columns=["insight_id", "h3_id", "priority_tier", "finding",
                     "confidence", "created_at", "area_name"]
        )
    df = pd.DataFrame([dict(r) for r in rows])
    df = df.drop_duplicates("h3_id")
    return df.reset_index(drop=True)


@st.cache_data(ttl=120, show_spinner=False)
def _load_source_receptor_ranking(
    aoi_id: str, *, top_n: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Identify top emission sources and top receptors inside an AOI.

    Prefers UPWIND_PM25_LOAD_REGIONAL (airshed-scale, ~100-300 km cone
    produced by the airshed compositor) when present; falls back to
    UPWIND_PM25_LOAD_K10 (metro-scale, ~7.5 km cone) when not. The
    third return value indicates which signal was used so the UI can
    label the scale honestly.

      source_score   = max(PM25 - upwind, 0)   — net contributor
      receptor_score = upwind                  — net importer

    Returns (sources_df, receptors_df, scale_label). Empty frames when
    no PM25 has been ingested yet.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = _ro_conn()
    try:
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.area_name
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, s2.signal, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('PM25',
                                    'UPWIND_PM25_LOAD_K10',
                                    'UPWIND_PM25_LOAD_REGIONAL')
                  AND s2.value IS NOT NULL
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value IS NOT NULL
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"],
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        empty = pd.DataFrame(columns=["h3_id", "pm25", "upwind",
                                      "score", "area_name"])
        return empty, empty.copy(), "—"

    df = pd.DataFrame([dict(r) for r in rows])
    pivot = (df.pivot_table(index=["h3_id", "area_name"], columns="signal",
                            values="value", aggfunc="first")
               .reset_index()
               .rename_axis(None, axis=1))
    for col in ("PM25", "UPWIND_PM25_LOAD_K10", "UPWIND_PM25_LOAD_REGIONAL"):
        if col not in pivot.columns:
            pivot[col] = None
    pivot = pivot.rename(columns={"PM25": "pm25"})

    # Prefer regional (~200 km, airshed-scale) when present.
    has_regional = pivot["UPWIND_PM25_LOAD_REGIONAL"].notna().any()
    if has_regional:
        pivot["upwind"] = pivot["UPWIND_PM25_LOAD_REGIONAL"]
        scale = "airshed ~100-300 km"
    else:
        pivot["upwind"] = pivot["UPWIND_PM25_LOAD_K10"]
        scale = "metro ~7.5 km"

    valid = pivot.dropna(subset=["pm25"]).copy()
    valid["upwind"] = valid["upwind"].fillna(0.0)

    valid["source_score"]   = (valid["pm25"] - valid["upwind"]).clip(lower=0)
    valid["receptor_score"] = valid["upwind"]

    sources = (valid.sort_values("source_score", ascending=False)
                    .head(top_n)
                    .loc[:, ["h3_id", "pm25", "upwind",
                             "source_score", "area_name"]]
                    .rename(columns={"source_score": "score"})
                    .reset_index(drop=True))
    receptors = (valid.sort_values("receptor_score", ascending=False)
                      .head(top_n)
                      .loc[:, ["h3_id", "pm25", "upwind",
                               "receptor_score", "area_name"]]
                      .rename(columns={"receptor_score": "score"})
                      .reset_index(drop=True))
    return sources, receptors, scale


@st.cache_data(ttl=120, show_spinner=False)
def _load_event_points(aoi_id: str) -> pd.DataFrame:
    """Active point-event signals inside the AOI bbox — fire FRP > 0,
    waste SITE = 1, crowd GATHERING_ALERT = 1, flood risk_level in
    (high, severe). Spatial filter (Phase 1 lens model) replaces the
    earlier defensive city_id bbox guard.

    Returns (h3_id, domain, lat, lon, magnitude_label) for IconLayer.
    """
    from airos.os.aoi_registry import bbox_of
    bbox = bbox_of(aoi_id)
    conn = _ro_conn()
    try:
        # Latest per (h3_id, signal) within the last 24h, spatially scoped.
        rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value, m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT s2.h3_id, s2.signal, MAX(s2.hour_bucket) AS hb
                FROM h3_signals s2
                INNER JOIN h3_metadata m2 ON m2.h3_id = s2.h3_id
                WHERE s2.signal IN ('FRP', 'SITE', 'GATHERING_ALERT')
                  AND s2.hour_bucket >= datetime('now', '-24 hours')
                  AND m2.centroid_lat BETWEEN ? AND ?
                  AND m2.centroid_lon BETWEEN ? AND ?
                GROUP BY s2.h3_id, s2.signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value > 0
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"],
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
        flood_rows = conn.execute(
            """
            SELECT a.h3_id, m.centroid_lat, m.centroid_lon
            FROM h3_assessments a
            INNER JOIN h3_metadata m ON m.h3_id = a.h3_id
            INNER JOIN (
                SELECT h3_id, MAX(day_bucket) AS db
                FROM h3_assessments
                WHERE domain = 'flood'
                GROUP BY h3_id
            ) latest ON latest.h3_id = a.h3_id AND latest.db = a.day_bucket
            WHERE a.domain = 'flood'
              AND a.risk_level IN ('high', 'severe')
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    sig_to_domain = {"FRP": "fire", "SITE": "waste", "GATHERING_ALERT": "crowd"}
    for r in rows:
        d = dict(r)
        lat, lon = d.get("centroid_lat"), d.get("centroid_lon")
        if lat is None or lon is None:
            lat, lon = h3.cell_to_latlng(d["h3_id"])
        out.append({
            "h3_id":    d["h3_id"],
            "domain":   sig_to_domain.get(d["signal"], d["signal"].lower()),
            "lat":      float(lat),
            "lon":      float(lon),
            "magnitude": f"{d['signal']}={d['value']:.2g}",
        })
    for r in flood_rows:
        d = dict(r)
        lat, lon = d.get("centroid_lat"), d.get("centroid_lon")
        if lat is None or lon is None:
            lat, lon = h3.cell_to_latlng(d["h3_id"])
        out.append({
            "h3_id":    d["h3_id"],
            "domain":   "flood",
            "lat":      float(lat),
            "lon":      float(lon),
            "magnitude": "high flood risk",
        })

    # Construction + industrial point markers — from POI counts already
    # ingested per-city. Threshold keeps the icon density manageable.
    out.extend(_poi_hotspot_points(bbox, threshold=3))

    # Wind direction arrows — one per AOI member city's centroid,
    # rotated by the latest WIND_DIR_DEG for that cell.
    out.extend(_wind_arrow_points(aoi_id, bbox))

    return pd.DataFrame(out)


def _poi_hotspot_points(bbox: dict, *, threshold: int = 3) -> list[dict]:
    """Pollution-source icon points inside `bbox`. Three signal families
    are surfaced as map icons:

      - POI_CONSTRUCTION_COUNT  →  🚧 construction
      - POI_INDUSTRIAL_COUNT    →  🏭 industrial
      - mobility: any cell with MAJOR_ROAD_RATIO ≥ 0.5 OR
        POI_TRANSIT_TERMINAL_COUNT ≥ 2 →  🚗 mobility hub

    Thresholds keep the icon density readable at airshed zoom. Returns
    one row per (cell, hotspot-kind) — a cell with both industrial AND
    mobility hubs gets two icons stacked on its centroid.
    """
    conn = _ro_conn()
    try:
        # Construction + industrial — straight POI count thresholds.
        poi_rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value,
                   m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT h3_id, signal, MAX(hour_bucket) AS hb
                FROM h3_signals
                WHERE signal IN ('POI_CONSTRUCTION_COUNT', 'POI_INDUSTRIAL_COUNT')
                GROUP BY h3_id, signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE s.value >= ?
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (float(threshold),
             bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()

        # Mobility — high major-road share OR transit terminals. Both
        # are vehicle emission proxies; the union covers highway
        # corridors AND urban transit hubs.
        mob_rows = conn.execute(
            """
            SELECT s.h3_id, s.signal, s.value,
                   m.centroid_lat, m.centroid_lon
            FROM h3_signals s
            INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
            INNER JOIN (
                SELECT h3_id, signal, MAX(hour_bucket) AS hb
                FROM h3_signals
                WHERE signal IN ('MAJOR_ROAD_RATIO', 'POI_TRANSIT_TERMINAL_COUNT')
                GROUP BY h3_id, signal
            ) latest ON latest.h3_id = s.h3_id
                    AND latest.signal = s.signal
                    AND latest.hb = s.hour_bucket
            WHERE (
                (s.signal = 'MAJOR_ROAD_RATIO' AND s.value >= 0.5)
                OR (s.signal = 'POI_TRANSIT_TERMINAL_COUNT' AND s.value >= 2)
            )
              AND m.centroid_lat BETWEEN ? AND ?
              AND m.centroid_lon BETWEEN ? AND ?
            """,
            (bbox["lat_min"], bbox["lat_max"],
             bbox["lon_min"], bbox["lon_max"]),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    sig_to_domain = {
        "POI_CONSTRUCTION_COUNT": "construction",
        "POI_INDUSTRIAL_COUNT":   "industrial",
    }
    for r in poi_rows:
        domain = sig_to_domain.get(r["signal"])
        if domain is None:
            continue
        out.append({
            "h3_id":    r["h3_id"],
            "domain":   domain,
            "lat":      float(r["centroid_lat"]),
            "lon":      float(r["centroid_lon"]),
            "magnitude": f"{r['signal']}={r['value']:.0f}",
        })
    # Dedup mobility hits — a cell can fire on both signals; show one
    # mobility icon per cell with whichever signal triggered first.
    seen_mob: set[str] = set()
    for r in mob_rows:
        if r["h3_id"] in seen_mob:
            continue
        seen_mob.add(r["h3_id"])
        v = r["value"]
        if r["signal"] == "MAJOR_ROAD_RATIO":
            label = f"major-road share {v:.0%}"
        else:
            label = f"{int(v)} transit terminals"
        out.append({
            "h3_id":    r["h3_id"],
            "domain":   "mobility",
            "lat":      float(r["centroid_lat"]),
            "lon":      float(r["centroid_lon"]),
            "magnitude": label,
        })
    return out


def _wind_arrow_points(aoi_id: str, bbox: dict) -> list[dict]:
    """One wind-direction arrow per AOI member city (or the AOI itself
    if it's a city). The arrow icon rotates by WIND_DIR_DEG so the
    operator can see prevailing advection at the airshed scale.

    Wind is city-broadcast (one OpenMeteo point per city) so we get
    one arrow per ingested wind source — typically 3-5 arrows across
    an airshed AOI, which is exactly the right density to read.
    """
    from airos.os.aoi_registry import get_aoi
    try:
        cfg = get_aoi(aoi_id)
    except KeyError:
        return []

    # For city AOI: arrow at the city centroid. For airshed/etc.: arrows
    # at every member city's centroid (or sampled grid if no members).
    if cfg["kind"] == "city":
        city_aois = [aoi_id]
    else:
        city_aois = cfg.get("member_aois") or []
    if not city_aois:
        return []

    conn = _ro_conn()
    out: list[dict] = []
    try:
        for cid in city_aois:
            try:
                ccfg = get_aoi(cid)
            except KeyError:
                continue
            cbbox = ccfg["bbox"]
            centre_lat = (cbbox["lat_min"] + cbbox["lat_max"]) / 2
            centre_lon = (cbbox["lon_min"] + cbbox["lon_max"]) / 2
            if not (bbox["lat_min"] <= centre_lat <= bbox["lat_max"]
                    and bbox["lon_min"] <= centre_lon <= bbox["lon_max"]):
                continue
            # Latest WIND_DIR_DEG + WIND_SPEED_KMH near this city centroid
            row = conn.execute(
                """
                SELECT s.signal, s.value
                FROM h3_signals s
                INNER JOIN h3_metadata m ON m.h3_id = s.h3_id
                WHERE s.signal IN ('WIND_DIR_DEG', 'WIND_SPEED_KMH')
                  AND s.value IS NOT NULL
                  AND m.centroid_lat BETWEEN ? AND ?
                  AND m.centroid_lon BETWEEN ? AND ?
                  AND s.hour_bucket >= datetime('now', '-6 hours')
                ORDER BY s.hour_bucket DESC
                """,
                (cbbox["lat_min"], cbbox["lat_max"],
                 cbbox["lon_min"], cbbox["lon_max"]),
            ).fetchall()
            wind_dir, wind_speed = None, None
            for r in row:
                if wind_dir is None and r["signal"] == "WIND_DIR_DEG":
                    wind_dir = float(r["value"])
                elif wind_speed is None and r["signal"] == "WIND_SPEED_KMH":
                    wind_speed = float(r["value"])
                if wind_dir is not None and wind_speed is not None:
                    break
            if wind_dir is None:
                continue
            # Meteorological wind_dir is the direction the wind is COMING
            # FROM. We want the arrow to point in the direction the wind
            # is GOING — so rotate by (wind_dir + 180) mod 360. The icon
            # asset is an upward-pointing arrow (north), so applying this
            # angle directly gives the downwind heading.
            arrow_angle = (wind_dir + 180.0) % 360.0
            ws_label = f" @ {wind_speed:.1f} km/h" if wind_speed is not None else ""
            out.append({
                "h3_id":    f"wind_{cid}",
                "domain":   "wind",
                "lat":      centre_lat,
                "lon":      centre_lon,
                "magnitude": f"wind from {wind_dir:.0f}°{ws_label}",
                "angle":    arrow_angle,
            })
    finally:
        conn.close()
    return out


# ── Layer assembly ───────────────────────────────────────────────────────────

def _hex_to_rgba_array(s: pd.Series, table: dict) -> list[list[int]]:
    """Map a Series of risk/tier strings to a list of [r, g, b, a] arrays
    (pydeck expects per-row list-of-ints, not tuples)."""
    default = list(table.get("unknown", (160, 160, 160, 40)))
    return [list(table.get(v, default)) for v in s.fillna("unknown")]


def _rollup_cells_to_resolution(
    df: pd.DataFrame, target_res: int, *,
    severity_col: str | None = None,
    severity_rank: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Aggregate per-cell rows from their native H3 resolution to a coarser
    target resolution, keeping the worst-severity child per parent.

    df:            DataFrame with an `h3_id` column. May contain mixed
                   resolutions (e.g. res-5 airshed cells alongside res-8
                   city cells inside an AOI's spatial query).
    target_res:    H3 resolution to aggregate to (e.g. 5 for airshed view).
    severity_col:  Column whose value drives "worst child wins". If None,
                   any-child-wins (the first row per parent is kept).
    severity_rank: Map from severity_col value → integer rank (higher = worse).

    Per-row handling:
      native_res >  target_res → aggregate up to parent at target_res
      native_res == target_res → keep as-is
      native_res <  target_res → drop (coarser than target; no honest
                                 way to refine it without fabricating data)

    Returns one row per parent at target_res.
    """
    if df.empty or "h3_id" not in df.columns:
        return df
    import h3

    df = df.copy()
    # Vectorised native-resolution + parent lookup via list comprehension
    # over `.values`. The previous df.apply(..., axis=1) path was O(N)
    # Python calls with ~5000 rows on the IGP-North view; this halves
    # per-render time on the citymap.
    h3_vals = df["h3_id"].values.tolist()
    native_res = [h3.get_resolution(c) for c in h3_vals]
    df["_native_res"] = native_res

    # Drop rows that are already coarser than target (they have no
    # res-`target_res` parent — they'd be the "children" of the target).
    df = df[df["_native_res"] >= target_res]
    if df.empty:
        return df.drop(columns=["_native_res"])

    parents = [
        c if r == target_res else h3.cell_to_parent(c, target_res)
        for c, r in zip(df["h3_id"].values, df["_native_res"].values)
    ]
    df["_parent"] = parents

    if severity_col and severity_col in df.columns and severity_rank:
        df["_rank"] = df[severity_col].map(severity_rank).fillna(0)
        df = (df.sort_values("_rank", ascending=False)
                .drop_duplicates("_parent")
                .drop(columns=["_rank"]))
    else:
        df = df.drop_duplicates("_parent")

    df["h3_id"] = df["_parent"]
    return df.drop(columns=["_parent", "_native_res"]).reset_index(drop=True)


def _rollup_icons_to_resolution(
    df: pd.DataFrame, target_res: int,
) -> pd.DataFrame:
    """One icon per (parent_cell, domain) instead of one per native-res
    cell. Handles mixed-resolution input (some res-5, some res-8) the
    same way _rollup_cells_to_resolution does: aggregate up, drop
    rows already coarser than target. Vectorised — same speed-up
    motivation as the cell roll-up."""
    if df.empty or "h3_id" not in df.columns:
        return df
    import h3
    df = df.copy()
    df["_native_res"] = [h3.get_resolution(c) for c in df["h3_id"].values]
    df = df[df["_native_res"] >= target_res]
    if df.empty:
        return df.drop(columns=["_native_res"])

    df["_parent"] = [
        c if r == target_res else h3.cell_to_parent(c, target_res)
        for c, r in zip(df["h3_id"].values, df["_native_res"].values)
    ]
    df = df.drop_duplicates(subset=["_parent", "domain"], keep="first")
    df["h3_id"] = df["_parent"]
    return df.drop(columns=["_parent", "_native_res"]).reset_index(drop=True)


def _build_layers(
    risk_df: pd.DataFrame,
    insight_df: pd.DataFrame,
    event_df: pd.DataFrame,
    *,
    show_risk_shade: bool,
    show_insight_border: bool,
    show_event_icons: bool,
) -> list[pdk.Layer]:
    layers: list[pdk.Layer] = []

    # 1. Risk shade — full H3 hex fill per cell, colour by worst risk_level
    if show_risk_shade and not risk_df.empty:
        risk_df = risk_df.copy()
        risk_df["fill_rgba"] = _hex_to_rgba_array(risk_df["risk_level"], _RISK_FILL_RGBA)
        layers.append(pdk.Layer(
            "H3HexagonLayer",
            data=risk_df,
            get_hexagon="h3_id",
            get_fill_color="fill_rgba",
            stroked=False,
            extruded=False,
            pickable=True,
            auto_highlight=True,
            id="risk_shade",
        ))

    # 2. Insight border — same hex shape, no fill, thick stroke coloured by tier
    if show_insight_border and not insight_df.empty:
        insight_df = insight_df.copy()
        insight_df["line_rgba"] = _hex_to_rgba_array(
            insight_df["priority_tier"], _INSIGHT_BORDER_RGBA,
        )
        layers.append(pdk.Layer(
            "H3HexagonLayer",
            data=insight_df,
            get_hexagon="h3_id",
            get_fill_color=[0, 0, 0, 0],
            get_line_color="line_rgba",
            stroked=True,
            filled=False,
            line_width_min_pixels=2,
            extruded=False,
            pickable=True,
            auto_highlight=False,
            id="insight_border",
        ))

    # 3. Event icons — Fire / Waste / Crowd / Flood / Construction /
    #    Industrial / Wind. Fixed pixel size so no icon dominates at
    #    airshed zoom levels (the IGP-North view at zoom 5).
    if show_event_icons and not event_df.empty:
        event_df = event_df.copy()
        event_df["icon_data"] = event_df["domain"].map(
            lambda d: {
                "url": _ICON_ATLAS.get(d, _ICON_ATLAS["fire"])["url"],
                "width": 96, "height": 96, "anchorY": 48,
            }
        )
        # Wind icons rotate by their `angle` column (degrees, deck.gl
        # convention: 0 = up/north, clockwise positive). Other icons
        # default to 0 (no rotation).
        if "angle" not in event_df.columns:
            event_df["angle"] = 0.0
        event_df["angle"] = event_df["angle"].fillna(0.0)
        layers.append(pdk.Layer(
            "IconLayer",
            data=event_df,
            get_icon="icon_data",
            get_position=["lon", "lat"],
            get_size=_ICON_PIXEL_SIZE,
            size_units="pixels",       # fixed pixel size at any zoom
            get_angle="angle",
            pickable=True,
            id="event_icons",
        ))

    return layers


# ── Cell detail side-panel ───────────────────────────────────────────────────

def _resolve_clicked_cell(h3_id: str, target_native_res: int = 8) -> tuple[str, str | None]:
    """When the user clicks a parent hex on a rolled-up airshed view,
    resolve it down to a single representative res-8 child for the
    dossier path.

    Strategy: among descendants at `target_native_res`, find the one
    that has the worst-priority open insight (critical > high > medium).
    If no descendants have insights, just pick the first descendant —
    the dossier still shows that cell's signals.

    Returns (effective_cell, originating_parent_or_None). When the
    clicked cell is already at target_native_res, returns (cell, None)
    so the existing single-cell path runs unchanged.
    """
    import h3
    clicked_res = h3.get_resolution(h3_id)
    if clicked_res >= target_native_res:
        return h3_id, None

    # Enumerate children at the target resolution
    try:
        children = list(h3.cell_to_children(h3_id, target_native_res))
    except Exception:
        return h3_id, None
    if not children:
        return h3_id, None

    # Query insights for any child; pick worst-priority + most-recent
    conn = _ro_conn()
    try:
        placeholders = ",".join("?" * len(children))
        row = conn.execute(
            f"""
            SELECT h3_id, priority_tier, created_at FROM h3_insights
            WHERE outcome_status = 'open'
              AND h3_id IN ({placeholders})
            ORDER BY
                CASE priority_tier
                    WHEN 'critical' THEN 0
                    WHEN 'high'     THEN 1
                    WHEN 'medium'   THEN 2
                    WHEN 'low'      THEN 3
                    ELSE 4 END,
                created_at DESC
            LIMIT 1
            """,
            children,
        ).fetchone()
    finally:
        conn.close()
    if row:
        return row["h3_id"], h3_id
    # No insight on any child — pick the first child (just so the dossier
    # has something to show; the parent context is preserved separately).
    return children[0], h3_id


def _render_cell_detail(h3_id: str, aoi_id: str) -> None:
    """Right-side panel content for a clicked cell. Resolves rolled-up
    parent hexes (airshed res-5 view) down to a representative res-8
    child so the dossier + insight panel show meaningful signals.

    The dossier needs a `city_id` (it joins to h3_metadata + h3_signals
    which still carry that column); we resolve the cell's primary city
    by spatial lookup when the parent AOI isn't itself a city kind.
    """
    from airos.os.cell_dossier import build_cell_dossier
    from airos.os.aoi_registry import get_aoi, aois_for_cell

    # If the user clicked a coarser parent hex (airshed view at res 5),
    # drill down to the worst-priority res-8 child for dossier context.
    effective_cell, clicked_parent = _resolve_clicked_cell(h3_id, target_native_res=8)

    if clicked_parent:
        st.caption(
            f"_Rolled-up view: showing the most-elevated descendant "
            f"`{effective_cell[:10]}…` of parent `{clicked_parent[:10]}…`._"
        )

    aoi_cfg = get_aoi(aoi_id)
    if aoi_cfg["kind"] == "city":
        # When viewing a city AOI, that's the dossier's reference city.
        city_id = aoi_id
    else:
        # For airshed / watershed / corridor AOIs the cell belongs to
        # some underlying city; pick the first city-kind AOI that
        # contains it. Falls back to the parent AOI if none found.
        city_containers = aois_for_cell(effective_cell, kind="city")
        city_id = city_containers[0] if city_containers else aoi_id

    try:
        dossier = build_cell_dossier(city_id, effective_cell)
    except Exception as exc:
        st.error(f"Failed to load cell dossier: {exc}")
        return

    # Replace h3_id with the effective one for the rest of this function
    h3_id = effective_cell

    meta = dossier.get("metadata") or {}
    st.markdown(f"#### {meta.get('area_name') or 'Cell'} · `{h3_id[:10]}…`")
    if meta.get("centroid_lat") and meta.get("centroid_lon"):
        st.caption(
            f"{float(meta['centroid_lat']):.4f}°N, "
            f"{float(meta['centroid_lon']):.4f}°E"
            + (f" · {meta.get('land_use_class')}" if meta.get('land_use_class') else "")
        )

    # Cause hypotheses (top 3)
    hyps = dossier.get("hypotheses") or []
    if hyps:
        st.markdown("**Cause hypotheses**")
        for h in hyps[:3]:
            st.caption(f"`{h['cause']}` — confidence {h.get('confidence', 0):.2f}")

    # Latest open insight on this cell (if any). Spatial cell lookup by
    # h3_id alone — no city_id filter, so an airshed-AOI click still
    # surfaces insights tagged with any constituent city's id.
    conn = _ro_conn()
    try:
        row = conn.execute(
            """
            SELECT insight_id, finding, priority_tier, confidence, created_at
            FROM h3_insights
            WHERE h3_id = ? AND outcome_status = 'open'
            ORDER BY created_at DESC LIMIT 1
            """,
            (h3_id,),
        ).fetchone()
    finally:
        conn.close()

    if row:
        st.markdown("**Open insight**")
        tier = row["priority_tier"] or "low"
        st.markdown(f"`{tier.upper()}` · confidence {row['confidence']:.2f}")
        st.write(row["finding"])
        st.caption(f"created {row['created_at']}")
    else:
        st.info("No open insight on this cell — signals only.")

    # POI summary (compact)
    pois = dossier.get("poi_summary") or {}
    if pois:
        st.markdown("**POIs**")
        st.caption(" · ".join(f"{k}: {v}" for k, v in pois.items() if v))


# ── Main entry ───────────────────────────────────────────────────────────────

_AOI_KIND_ICON: dict[str, str] = {
    "city":      "🏙️",
    "airshed":   "🌫️",
    "watershed": "💧",
    "corridor":  "🛣️",
    "port":      "⚓",
    "airport":   "✈️",
}


@st.cache_data(ttl=120, show_spinner=False)
def _airshed_summary(aoi_id: str) -> dict:
    """Thin cached wrapper around airshed_compositor.airshed_summary_stats."""
    from airos.os.airshed_compositor import airshed_summary_stats
    return airshed_summary_stats(aoi_id)


def _render_airshed_summary(aoi_id: str) -> None:
    """Compact airshed-level stats header (Phase 3 item 2 — composition).

    Surfaces aggregate signals you can't see in a per-cell view: avg PM2.5
    across the whole airshed, fire count over 24h, % cells at high/severe
    risk, and total exposed population. Computed on demand from the
    spatial lens — no airshed-level table, no extra storage.
    """
    s = _airshed_summary(aoi_id)
    if not s:
        return

    rows = []
    if s.get("avg_pm25") is not None:
        rows.append(f"PM2.5 avg **{s['avg_pm25']:.0f}** · "
                    f"max {s.get('max_pm25', 0):.0f} · "
                    f"p95 {s.get('p95_pm25', 0):.0f}")
    if s.get("fire_count_24h"):
        rows.append(f"🔥 **{s['fire_count_24h']}** fires 24h · "
                    f"ΣFRP {s.get('frp_total_24h', 0):.0f}")
    if s.get("high_risk_cells_pct") is not None:
        rows.append(f"**{s['high_risk_cells_pct']:.0f}%** cells "
                    f"at high/severe risk")
    if s.get("population_exposed_high"):
        rows.append(f"**{s['population_exposed_high']:,}** people in "
                    f"high-risk cells")
    if not rows:
        return
    st.markdown("**Airshed summary**")
    for line in rows:
        st.markdown(f"<small>{line}</small>", unsafe_allow_html=True)
    st.markdown("")


def _render_source_receptor(aoi_id: str) -> None:
    """Top-N source + receptor cells for non-city AOIs.

    A "source" cell is a net emitter (local PM > regional upwind PM —
    contributes more than it receives). A "receptor" cell is dominated
    by incoming regional load (high UPWIND_PM25_LOAD_K10). The split
    tells the airshed dispatcher who to enforce on (sources) versus
    who needs cross-jurisdiction coordination (receptors).
    """
    sources, receptors, scale = _load_source_receptor_ranking(aoi_id, top_n=8)
    if sources.empty and receptors.empty:
        st.caption(
            "_No PM25 / upwind signals yet — run an air ingest sweep first._"
        )
        return

    def _fmt_row(r: pd.Series, score_label: str) -> str:
        area = r.get("area_name") or "—"
        pm = r["pm25"] or 0
        up = r["upwind"] or 0
        return (
            f"<small><b>{area}</b> · {score_label} {r['score']:.1f}  "
            f"<span style='color:#888;'>(PM25 {pm:.0f}, upwind {up:.0f})</span></small>"
        )

    if not sources.empty:
        st.markdown("**🏭 Top emission sources**")
        st.caption(
            f"_Cells where local PM exceeds upwind incoming ({scale}) — "
            f"net contributors. Local enforcement targets._"
        )
        for _, r in sources.iterrows():
            st.markdown(_fmt_row(r, "net+"), unsafe_allow_html=True)
        st.markdown("")

    if not receptors.empty:
        st.markdown("**📥 Top receptors**")
        st.caption(
            f"_Cells receiving the most incoming pollution from upwind "
            f"({scale}). Need cross-jurisdiction coordination._"
        )
        for _, r in receptors.iterrows():
            st.markdown(_fmt_row(r, "in"), unsafe_allow_html=True)


def render_citymap_panel() -> None:
    """Full-screen AOI situational-awareness map. Registered as the
    default landing view in app.py. Selecting any AOI — city, airshed,
    watershed, corridor — renders the same overlays at the AOI's
    auto-derived resolution."""
    from airos.os.aoi_registry import (
        list_aois, get_aoi, bbox_of, resolution_of,
    )

    # Inject a small bit of CSS so the map feels full-bleed and the
    # selectbox overlay floats over the deck.
    st.markdown(
        """
        <style>
        /* Tighten the top padding so the map takes more screen */
        section.main > div.block-container { padding-top: 1rem; }
        /* Floating overlay row */
        .citymap-overlay-row { margin-bottom: 0.25rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Floating overlay row: AOI dropdown + layer toggles popover ───────
    col_aoi, col_layers, _spacer = st.columns([2.4, 1.6, 6.0])

    with col_aoi:
        aoi_ids = list_aois()
        if not aoi_ids:
            st.error("No AOIs configured — add one to data/config/aoi.yaml.")
            return
        # Build display label "<icon> <display_name>" per AOI; selector
        # value is the AOI id.
        def _aoi_label(aoi_id: str) -> str:
            cfg = get_aoi(aoi_id)
            return f"{_AOI_KIND_ICON.get(cfg['kind'], '📍')} {cfg['display_name']}"

        # Sort: non-city AOIs (airshed/watershed/corridor) first, then
        # cities — the biggest-picture view is the most useful default
        # for a "what's going on" map. Within each group, alphabetical
        # by display name.
        _kind_rank = {"airshed": 0, "watershed": 1, "corridor": 2,
                      "port": 3, "airport": 4, "city": 5}
        def _sort_key(aoi_id: str) -> tuple:
            cfg = get_aoi(aoi_id)
            return (_kind_rank.get(cfg["kind"], 9), cfg["display_name"])
        aoi_ids = sorted(aoi_ids, key=_sort_key)

        label_to_id = {_aoi_label(a): a for a in aoi_ids}
        labels = list(label_to_id.keys())
        # Restore previous selection if still valid; otherwise default
        # to the first AOI which is now the biggest non-city scope.
        prev = st.session_state.get("citymap_aoi_label")
        idx = labels.index(prev) if prev in label_to_id else 0
        label = st.selectbox(
            "AOI", labels, index=idx,
            key="citymap_aoi_selector", label_visibility="collapsed",
        )
        st.session_state["citymap_aoi_label"] = label
        aoi_id = label_to_id[label]
        aoi_cfg = get_aoi(aoi_id)

    with col_layers:
        with st.popover("🧭 Layers", use_container_width=True):
            show_risk    = st.checkbox("Risk shade (worst per cell)", value=True,
                                       key="citymap_show_risk")
            show_border  = st.checkbox("Insight border (high/medium)", value=True,
                                       key="citymap_show_border")
            show_icons   = st.checkbox("Event icons (fire/waste/crowd/flood)",
                                       value=True, key="citymap_show_icons")
            st.divider()
            # Hex resolution override. "Auto" uses the AOI's declared
            # resolution (res 5 for IGP-North airshed, res 8 for cities).
            # Manual values let the operator pull more detail into the
            # airshed view, or zoom out a city to neighbourhood-scale
            # parents. Coarser = fewer hexes / more aggregation.
            st.caption("**Hex resolution**")
            _res_choices = ["Auto", "5 (~250 km²)", "6 (~36 km²)",
                            "7 (~5 km²)", "8 (~0.7 km²)"]
            res_label = st.selectbox(
                "Hex resolution", _res_choices,
                key="citymap_resolution_choice",
                label_visibility="collapsed",
            )
            st.divider()
            st.caption("**Risk shade legend**")
            for tier in ("severe", "high", "moderate", "low", "good"):
                r, g, b, a = _RISK_FILL_RGBA[tier]
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;"
                    f"background:rgba({r},{g},{b},{a/255:.2f});"
                    f"border:1px solid #888;margin-right:6px;'></span>"
                    f"<small>{tier}</small>",
                    unsafe_allow_html=True,
                )
            st.caption("**Insight border**")
            for tier in ("critical", "high", "medium"):
                r, g, b, a = _INSIGHT_BORDER_RGBA[tier]
                st.markdown(
                    f"<span style='display:inline-block;width:14px;height:14px;"
                    f"border:3px solid rgba({r},{g},{b},{a/255:.2f});"
                    f"margin-right:6px;'></span><small>{tier}</small>",
                    unsafe_allow_html=True,
                )

    # ── Load data (spatial — Phase 1 AOI lens) ────────────────────────────
    risk_df    = _load_worst_risk_per_cell(aoi_id)
    insight_df = _load_open_insights_by_cell(aoi_id)
    event_df   = _load_event_points(aoi_id)

    # ── Roll cells up to the chosen H3 resolution ─────────────────────────
    # Cells ingest at H3 res 8 (~0.74 km²); an airshed view declares res 5
    # (~252 km²) so the operator can actually see the data at zoom 5.
    # Aggregate each layer to parent cells at the chosen resolution,
    # keeping the worst-severity child per parent (so a single hot res-8
    # cell makes its res-5 parent hot).
    #
    # Resolution choice:
    #   - "Auto" (default)  → use the AOI's declared resolution.
    #   - "5 / 6 / 7 / 8"   → manual override; lets the operator drill
    #                          into an airshed at res 8 or zoom out a
    #                          city to res 6. Coarser = fewer hexes.
    if res_label.startswith("Auto"):
        aoi_res = resolution_of(aoi_id)
    else:
        aoi_res = int(res_label.split()[0])
    insight_tier_rank = {"critical": 3, "high": 2, "medium": 1}
    risk_df    = _rollup_cells_to_resolution(
        risk_df, aoi_res,
        severity_col="risk_level", severity_rank=_RISK_RANK,
    )
    insight_df = _rollup_cells_to_resolution(
        insight_df, aoi_res,
        severity_col="priority_tier", severity_rank=insight_tier_rank,
    )
    event_df   = _rollup_icons_to_resolution(event_df, aoi_res)

    layers = _build_layers(
        risk_df, insight_df, event_df,
        show_risk_shade=show_risk,
        show_insight_border=show_border,
        show_event_icons=show_icons,
    )

    # ── Initial viewport: AOI bbox centroid + zoom derived from area ─────
    bbox = bbox_of(aoi_id)
    centre_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2.0
    centre_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2.0
    # Map the AOI's H3 resolution to a sensible default zoom (smaller
    # AOIs → finer res → higher zoom).
    zoom_by_resolution = {9: 13, 8: 11, 7: 9, 6: 7, 5: 5}
    zoom = zoom_by_resolution.get(resolution_of(aoi_id), 11)
    view_state = pdk.ViewState(
        latitude=centre_lat,
        longitude=centre_lon,
        zoom=zoom,
        pitch=0,
        bearing=0,
    )

    # Tooltip: name first (when available), then domain + risk. The
    # area_name comes from Nominatim reverse-geocoding of the cell
    # centroid; res-5 airshed cells get district / town-level names
    # ("Bilhaur", "Saharsa, Bihar"), res-8 city cells get
    # neighbourhood names ("Anand Vihar", "Indiranagar"). When the
    # geocoder hasn't run yet for a cell, area_name is "" and the
    # tooltip falls back to the H3 id alone.
    tooltip = {
        "html": (
            "<b>{area_name}</b><br/>"
            "<b>{dominant_domain}</b> &middot; risk: <b>{risk_level}</b>"
            "<br/>{dominant_issue}"
            "<br/><small>{h3_id}</small>"
        ),
        "style": {
            "backgroundColor": "rgba(20,20,28,0.92)",
            "color": "white",
            "padding": "6px 8px",
            "borderRadius": "6px",
            "fontSize": "12px",
        },
    }

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="light",
        tooltip=tooltip,
    )

    # ── Map + side panel layout ──────────────────────────────────────────
    map_col, side_col = st.columns([3.0, 1.0])
    with map_col:
        event = st.pydeck_chart(
            deck, use_container_width=True, height=760,
            on_select="rerun", selection_mode="single-object",
            key="citymap_deck",
        )

    # Resolve clicked cell from pydeck selection event
    clicked_h3: str | None = None
    if event is not None and hasattr(event, "selection"):
        sel = event.selection or {}
        objs = sel.get("objects") or {}
        # `objects` is a dict of layer_id → list[picked rows]
        for layer_id in ("risk_shade", "insight_border"):
            picks = objs.get(layer_id) or []
            if picks:
                row = picks[0]
                clicked_h3 = row.get("h3_id")
                break
        if not clicked_h3:
            picks = objs.get("event_icons") or []
            if picks:
                clicked_h3 = picks[0].get("h3_id")

    with side_col:
        if clicked_h3:
            _render_cell_detail(clicked_h3, aoi_id)
        else:
            n_cells   = len(risk_df)
            n_insight = len(insight_df)
            n_events  = len(event_df)
            kind_icon = _AOI_KIND_ICON.get(aoi_cfg["kind"], "📍")
            st.markdown(f"#### {kind_icon} {aoi_cfg['display_name']}")
            declared_res = resolution_of(aoi_id)
            res_note = (f"H3 res {aoi_res}"
                        + (f" (override; declared {declared_res})"
                           if aoi_res != declared_res else ""))
            st.caption(
                f"{aoi_cfg['kind']} · {res_note} · "
                f"{n_cells:,} hexes"
            )

            # Source/receptor ranking — only meaningful for AOIs that span
            # multiple districts (airshed / watershed / corridor). Cities
            # are usually a single emission/receiver zone so the split is
            # noisier than it is useful.
            if aoi_cfg["kind"] in ("airshed", "watershed", "corridor"):
                _render_airshed_summary(aoi_id)
                _render_source_receptor(aoi_id)
            if n_insight:
                tier_counts = insight_df["priority_tier"].value_counts().to_dict()
                bits = []
                for t in ("critical", "high", "medium"):
                    if tier_counts.get(t):
                        bits.append(f"{tier_counts[t]} {t}")
                st.caption("Open insights: " + ", ".join(bits) if bits else "Open insights: 0")
            else:
                st.caption("Open insights: 0")
            if n_events:
                ev_counts = event_df["domain"].value_counts().to_dict()
                st.caption("Active events: " + ", ".join(
                    f"{n} {d}" for d, n in ev_counts.items()
                ))
            st.divider()
            st.info("Click any cell on the map for details.")
