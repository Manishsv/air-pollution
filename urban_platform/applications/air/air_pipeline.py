"""
Air quality scoring pipeline.

Combines PM2.5 observations (IDW-interpolated to H3 grid) to produce:
  - Per-H3-cell AQI grid (air_quality_dashboard consumer contract)
  - Top-N decision packets for highest-AQI cells (air_quality_decision_packet contract)

Scoring formula
---------------
  aqi_score = min(pm25_ugm3 / 120.0, 1.0)   # 120 µg/m³ (Poor ceiling) → 1.0

India AQI categories (PM2.5 µg/m³):
  Good:        0–30
  Satisfactory: 30–60
  Moderate:    60–90
  Poor:        90–120
  Very Poor:   120–250
  Severe:      >250

All outputs are **indicative** (IDW-interpolated, synthetic fallbacks) and
require human review before any operational or public-facing action.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from urban_platform.applications.flood.flood_pipeline import (
    build_h3_grid_from_bbox,
    _haversine_km,
    _idw_interpolate,
)

logger = logging.getLogger(__name__)

_DECISION_PACKET_TOP_N = 5
_SPEC_ROOT = Path(__file__).resolve().parents[3] / "specifications"


# ── AQI helpers ───────────────────────────────────────────────────────────

def _aqi_category(pm25: float) -> str:
    if pm25 >= 250:
        return "severe"
    if pm25 >= 120:
        return "very_poor"
    if pm25 >= 90:
        return "poor"
    if pm25 >= 60:
        return "moderate"
    if pm25 >= 30:
        return "satisfactory"
    return "good"


def _aqi_color(cat: str) -> list:
    return {
        "good":         [34, 139, 34, 180],
        "satisfactory": [144, 238, 0, 180],
        "moderate":     [255, 215, 0, 190],
        "poor":         [255, 140, 0, 200],
        "very_poor":    [200, 40, 40, 210],
        "severe":       [128, 0, 32, 230],
    }.get(cat, [128, 128, 128, 150])


def _worst_category(cells_df: pd.DataFrame) -> str:
    order = ["severe", "very_poor", "poor", "moderate", "satisfactory", "good"]
    for cat in order:
        if (cells_df["aqi_category"] == cat).any():
            return cat
    return "good"


def _data_quality_flag(aq_df: pd.DataFrame) -> str:
    if aq_df.empty:
        return "unavailable"
    if (aq_df.get("quality_flag", pd.Series()) == "synthetic").any():
        return "synthetic"
    return "real"


def _sources(aq_df: pd.DataFrame) -> list:
    srcs = []
    if not aq_df.empty:
        ds = aq_df.get("data_source", pd.Series()).dropna().unique().tolist()
        srcs.extend(ds or ["openmeteo_aq"])
    return srcs or ["unavailable"]


def _source_status(aq_df: pd.DataFrame) -> list:
    """
    Per-source status for display: live | stale | unavailable.

    live      — real-time feed, data current
    stale     — data present but synthetic/unverified
    unavailable — no data returned
    """
    statuses = []

    if aq_df.empty:
        statuses.append({
            "source": "air_quality", "label": "Air Quality API",
            "status": "unavailable", "detail": "No air quality data returned",
        })
    else:
        qflags = set(aq_df.get("quality_flag", pd.Series()).dropna().tolist())
        is_synthetic = "synthetic" in qflags
        ds = (aq_df["data_source"].dropna().iloc[0]
              if "data_source" in aq_df.columns and len(aq_df) > 0
              else "openmeteo_aq")
        ts = (str(aq_df["timestamp"].dropna().iloc[0])[:16]
              if "timestamp" in aq_df.columns and len(aq_df) > 0
              else "—")
        statuses.append({
            "source": "air_quality",
            "label": f"{ds} Air Quality API",
            "status": "stale" if is_synthetic else "live",
            "detail": (
                f"{'Synthetic demo' if is_synthetic else 'Real-time'} · "
                f"{len(aq_df)} grid points · {ts}"
            ),
        })

    return statuses


def _computation_trace(
    h3_row: "pd.Series",
    dqf: str,
    n_aq_points: int,
) -> dict:
    """Explainable breakdown of the scoring formula for one H3 cell."""
    pm25_val = float(h3_row["pm25_ugm3"] or 0.0)
    aqi_score = min(pm25_val / 120.0, 1.0)

    return {
        "algorithm": "IDW-weighted AQI scoring (v1)",
        "formula": "aqi_score = min(pm25_ugm3 / 120.0, 1.0)",
        "steps": [
            {
                "name": "pm25_idw_interpolated",
                "formula": "IDW from observation points",
                "inputs": {
                    "pm25_ugm3": round(pm25_val, 3),
                    "interpolation": f"IDW from {n_aq_points} sample points",
                },
                "value": round(pm25_val, 4),
            },
            {
                "name": "aqi_score",
                "formula": "min(pm25_ugm3 / 120.0, 1.0)",
                "inputs": {"pm25_ugm3": round(pm25_val, 3)},
                "value": round(aqi_score, 4),
                "weight": 1.0,
            },
        ],
        "data_quality_flag": dqf,
    }


# ── Core pipeline ─────────────────────────────────────────────────────────

def run_air_quality_pipeline(
    aq_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
) -> dict:
    """
    Run the air quality scoring pipeline.

    Parameters
    ----------
    aq_df : DataFrame
        Columns: latitude, longitude, pm25_ugm3, quality_flag.
        Empty DataFrame → data_quality_flag="unavailable", all cells score 0.

    Returns
    -------
    dict with keys:
        risk_cells      — DataFrame (h3_id, pm25_ugm3, aqi_score, aqi_category, color)
        data_quality_flag — "real" | "synthetic" | "unavailable"
        city_id
        summary         — counts by AQI category + aggregate stats
    """
    h3_grid = build_h3_grid_from_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)
    dqf = _data_quality_flag(aq_df)

    # ── PM2.5 IDW ─────────────────────────────────────────────────────────
    has_aq = (not aq_df.empty
              and "pm25_ugm3" in aq_df.columns
              and aq_df["pm25_ugm3"].notna().any())
    if has_aq:
        obs_lats = aq_df["latitude"].values
        obs_lons = aq_df["longitude"].values
        obs_pm25 = aq_df["pm25_ugm3"].values

    # ── Per-cell scoring ──────────────────────────────────────────────────
    rows = []
    for _, cell in h3_grid.iterrows():
        clat, clon = cell["centroid_lat"], cell["centroid_lon"]

        if has_aq:
            pm25_val = _idw_interpolate(clat, clon, obs_lats, obs_lons, obs_pm25)
            score = min(pm25_val / 120.0, 1.0)
        else:
            pm25_val, score = 0.0, 0.0

        cat = _aqi_category(float(pm25_val))

        rows.append({
            "h3_id": cell["h3_id"],
            "pm25_ugm3": round(float(pm25_val), 3) if has_aq else None,
            "aqi_score": round(score, 4),
            "aqi_category": cat,
            "color": _aqi_color(cat),
        })

    risk_cells = pd.DataFrame(rows)

    try:
        from urban_platform.feature_store.writer import FeatureStoreWriter
        with FeatureStoreWriter() as fsw:
            fsw.write_air_features(risk_cells, city_id=city_id, data_quality_flag=dqf)
    except Exception as _fse:
        logger.warning("feature_store write skipped: %s", _fse)

    counts = risk_cells["aqi_category"].value_counts().to_dict()
    return {
        "risk_cells": risk_cells,
        "data_quality_flag": dqf,
        "city_id": city_id,
        "summary": {
            "total_cells": len(risk_cells),
            "severe_count": counts.get("severe", 0),
            "very_poor_count": counts.get("very_poor", 0),
            "poor_count": counts.get("poor", 0),
            "moderate_count": counts.get("moderate", 0),
            "satisfactory_count": counts.get("satisfactory", 0),
            "good_count": counts.get("good", 0),
            "max_pm25_ugm3": (
                float(risk_cells["pm25_ugm3"].max())
                if has_aq and not risk_cells["pm25_ugm3"].isna().all()
                else None
            ),
            "avg_pm25_ugm3": (
                float(risk_cells["pm25_ugm3"].mean())
                if has_aq and not risk_cells["pm25_ugm3"].isna().all()
                else None
            ),
            "station_count": len(aq_df),
        },
    }


# ── Consumer contract builders ────────────────────────────────────────────

def build_air_quality_dashboard(
    aq_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
) -> dict:
    """
    Build the air_quality_dashboard consumer contract.

    Returns a dict that validates against
    specifications/consumer_contracts/air_quality_dashboard.v1.schema.json.
    """
    now = datetime.now(timezone.utc).isoformat()
    pipeline = run_air_quality_pipeline(
        aq_df, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    risk_cells = pipeline["risk_cells"]
    summary = pipeline["summary"]
    dqf = pipeline["data_quality_flag"]
    synthetic_used = dqf == "synthetic"

    # ── Map layers ────────────────────────────────────────────────────────
    map_layers = [
        {"layer_id": "air_quality_grid", "layer_type": "h3_hexagon",
         "title": "Air Quality Grid (H3)"},
    ]

    # ── Risk areas (top poor/very_poor/severe H3 cells) ───────────────────
    high_cells = risk_cells[risk_cells["aqi_category"].isin(["poor", "very_poor", "severe"])]
    risk_areas = [
        {
            "area_id": row["h3_id"],
            "aqi_category": row["aqi_category"],
            "confidence_score": round(row["aqi_score"], 3),
            "uncertainty": {
                "notes": "IDW-interpolated PM2.5; sparse 3×3 observation grid",
            },
        }
        for _, row in high_cells.head(10).iterrows()
    ]
    if not risk_areas:
        top = risk_cells.nlargest(1, "aqi_score").iloc[0]
        risk_areas = [{
            "area_id": top["h3_id"],
            "aqi_category": top["aqi_category"],
            "confidence_score": round(top["aqi_score"], 3),
            "uncertainty": {"notes": "No poor+ AQI cells detected; lowest-risk cell shown"},
        }]

    # ── Active warnings ───────────────────────────────────────────────────
    warnings = [{
        "warning_id": "decision_support_only",
        "severity": "error",
        "message": (
            "Decision support only. Do not issue public health advisories or "
            "emergency orders from this output without authorised human review."
        ),
    }, {
        "warning_id": "idw_sparse_grid",
        "severity": "warning",
        "message": (
            "PM2.5 estimates are IDW-interpolated from a sparse 3×3 observation grid. "
            "Local pollution hotspots may not be captured. Field verification required."
        ),
    }]
    if dqf == "synthetic":
        warnings.append({
            "warning_id": "synthetic_data",
            "severity": "warning",
            "message": "Air quality data is synthetic demo data. Do not use for operational decisions.",
        })
    if dqf == "unavailable":
        warnings.append({
            "warning_id": "data_unavailable",
            "severity": "error",
            "message": "Air quality data unavailable. All AQI scores are unreliable.",
        })

    # ── Recommended review queue ──────────────────────────────────────────
    review_queue = [
        {
            "packet_id": f"pkt_{row['h3_id'][:8]}",
            "priority": "high" if row["aqi_category"] in ("very_poor", "severe") else "medium",
            "reason": (
                f"{row['aqi_category'].replace('_', ' ').capitalize()} AQI — "
                f"PM2.5 {row['pm25_ugm3'] or 0:.1f} µg/m³"
            ),
        }
        for _, row in high_cells.head(5).iterrows()
    ]
    if not review_queue:
        review_queue = [{
            "packet_id": "pkt_placeholder",
            "priority": "low",
            "reason": "No poor+ AQI areas detected in current observation window.",
        }]

    # ── Risk cells list for map rendering ─────────────────────────────────
    risk_cells_list = [
        {
            "h3_id": r["h3_id"],
            "aqi_category": r["aqi_category"],
            "confidence_score": round(r["aqi_score"], 3),
        }
        for _, r in risk_cells.iterrows()
    ]

    return {
        "generated_at": now,
        "city_id": city_id,
        "data_quality_flag": dqf,
        "risk_summary": {
            "overall_aqi_category": _worst_category(risk_cells),
            "time_window": "last_24_hours",
            "headline": (
                f"{summary['poor_count'] + summary['very_poor_count'] + summary['severe_count']} "
                f"poor+ AQI cells — max PM2.5 {summary['max_pm25_ugm3'] or 0:.1f} µg/m³"
            ),
        },
        "map_layers": map_layers,
        "risk_cells": risk_cells_list,
        "risk_areas": risk_areas,
        "active_warnings": warnings,
        "data_quality_summary": {
            "synthetic_data_used": synthetic_used,
            "confidence_note": (
                "AQI scores are IDW-interpolated from a sparse 3×3 observation grid. "
                "IDW estimates are not official CPCB AQI readings. Human review required."
            ),
        },
        "recommended_review_queue": review_queue,
        "provenance_summary": {
            "sources": _sources(aq_df),
            "synthetic_used": synthetic_used,
        },
        "summary": summary,
    }


def build_air_quality_decision_packets(
    aq_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
    top_n: int = _DECISION_PACKET_TOP_N,
) -> list:
    """
    Build top-N air_quality_decision_packet consumer contracts for highest-AQI H3 cells.

    Each returned dict validates against
    specifications/consumer_contracts/air_quality_decision_packet.v1.schema.json.
    Returns at least one packet even when all cells are good AQI.
    """
    now = datetime.now(timezone.utc).isoformat()
    pipeline = run_air_quality_pipeline(
        aq_df, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    risk_cells = pipeline["risk_cells"]
    dqf = pipeline["data_quality_flag"]
    top_cells = risk_cells.nlargest(max(top_n, 1), "aqi_score")

    src_status = _source_status(aq_df)

    block_reason = (
        "IDW-interpolated PM2.5 estimates require field verification "
        "before any operational action."
    )
    if dqf == "synthetic":
        block_reason = "Synthetic demo data — operational action blocked. " + block_reason
    if dqf == "unavailable":
        block_reason = "Air quality data unavailable — all scores unreliable. " + block_reason

    packets = []
    for _, row in top_cells.iterrows():
        uid = hashlib.sha1(f"aq_{row['h3_id']}_{now}".encode()).hexdigest()[:10]
        pm25_val = row["pm25_ugm3"]

        trace = _computation_trace(row, dqf, len(aq_df))

        packets.append({
            "packet_id": f"pkt_{uid}",
            "domain_id": "air_quality",
            "timestamp": now,
            "h3_id": row["h3_id"],
            "aqi_assessment": {
                "aqi_category": row["aqi_category"],
                "primary_pollutant": "pm25",
                "time_window": "last_24_hours",
            },
            "evidence": {
                "inputs": [
                    {"name": "pm25_ugm3",
                     "value": round(pm25_val, 2) if pm25_val is not None else None,
                     "unit": "µg/m³"},
                    {"name": "aqi_score",
                     "value": round(row["aqi_score"], 4)},
                ],
                "notes": (
                    f"IDW-interpolated from {len(aq_df)} air quality sample points. "
                    f"Data quality: {dqf}."
                ),
            },
            "data_source_status": src_status,
            "computation_trace": trace,
            "provenance": {
                "sources": _sources(aq_df),
                "city_id": city_id,
                "data_quality_flag": dqf,
            },
            "confidence": {
                "confidence_score": round(row["aqi_score"], 3),
                "recommendation_allowed": False,
                "recommendation_block_reason": block_reason,
            },
            "review_guidance": {
                "review_prompts": [
                    "Has field measurement confirmed elevated PM2.5 at this location?",
                    "Are vulnerable populations (elderly, children, respiratory patients) present?",
                    "Is PM2.5 elevation consistent with nearby CPCB monitoring stations?",
                    "Are there known pollution sources (industrial, traffic) in this cell?",
                ],
                "when_not_to_act": [
                    "Do not issue public health advisories based solely on IDW-interpolated estimates.",
                    "Do not act on synthetic or unverified data without field confirmation.",
                    "Do not replace official CPCB AQI readings with these IDW estimates.",
                ],
            },
            "safety_gates": [{
                "gate_id": "field_verification_required",
                "status": "blocked",
                "message": (
                    "Field verification or official CPCB reading must be confirmed before "
                    "any public health advisory or emergency action."
                ),
            }],
            "blocked_uses": [
                "automatic_public_health_advisory_without_review",
                "replace_official_cpcb_aqi_readings",
                "emergency_closure_orders_without_human_authorization",
            ],
            "field_verification_required": True,
        })

    return packets
