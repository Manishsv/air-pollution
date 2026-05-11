"""Fire monitoring pipeline — H3 aggregation of FIRMS VIIRS hotspots."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

import pandas as pd

from airos.os.rules import rules as _rules


# ── Risk thresholds — read from rules registry ─────────────────────────────

def _frp_thresholds() -> dict:
    return _rules.get("fire", "frp_risk_levels_mw", default={
        "severe": 100.0, "high": 30.0, "moderate": 10.0, "low": 5.0,
    })

_RISK_COLORS = {
    "none":     [200, 200, 200, 60],
    "low":      [255, 220, 80, 140],
    "moderate": [255, 140, 0, 180],
    "high":     [220, 60, 0, 210],
    "severe":   [140, 0, 0, 240],
}

_LEVEL_ORDER = ["none", "low", "moderate", "high", "severe"]


# ── Scoring ────────────────────────────────────────────────────────────────

def _frp_to_risk(total_frp: float) -> tuple[float, str]:
    saturation = _rules.get("fire", "frp_score_saturation_mw", default=500.0)
    score = min(1.0, math.log1p(total_frp) / math.log1p(saturation))
    thresholds = _frp_thresholds()
    for level in ("severe", "high", "moderate", "low"):
        if total_frp >= thresholds[level]:
            return round(score, 4), level
    return 0.0, "none"


# ── Dashboard builder ──────────────────────────────────────────────────────

def build_fire_dashboard(
    fire_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    """Aggregate FIRMS hotspots into H3 grid and build the dashboard payload."""
    now   = datetime.now(timezone.utc).isoformat()
    cells: list[dict] = []
    total_city_hotspots = 0
    max_frp_seen = 0.0

    if not fire_df.empty and {"latitude", "longitude", "frp"}.issubset(fire_df.columns):
        try:
            import h3
        except ImportError:
            h3 = None

        if h3:
            _floor = _rules.get("fire", "frp_detection_floor_mw", default=5.0)
            sig = fire_df[fire_df["frp"] >= _floor].copy()
            sig["h3_id"] = [
                h3.latlng_to_cell(float(lat), float(lon), h3_resolution)
                for lat, lon in zip(sig["latitude"], sig["longitude"])
            ]

            for h3_id, grp in sig.groupby("h3_id"):
                total_frp    = float(grp["frp"].sum())
                max_frp_cell = float(grp["frp"].max())
                count        = len(grp)
                avg_conf     = float(grp["detection_confidence"].mean()) if "detection_confidence" in grp.columns else 60.0
                in_city      = bool(grp["within_bbox"].any()) if "within_bbox" in grp.columns else False
                acq_dates    = sorted(grp["acq_date"].astype(str).unique().tolist()) if "acq_date" in grp.columns else []
                satellites   = sorted(grp["satellite"].astype(str).unique().tolist()) if "satellite" in grp.columns else []

                risk_score, risk_level = _frp_to_risk(total_frp)

                if in_city:
                    total_city_hotspots += count
                max_frp_seen = max(max_frp_seen, max_frp_cell)

                cells.append({
                    "h3_id":          h3_id,
                    "fire_count":     count,
                    "total_frp_mw":   round(total_frp, 2),
                    "max_frp_mw":     round(max_frp_cell, 2),
                    "avg_confidence": round(avg_conf, 1),
                    "risk_score":     risk_score,
                    "risk_level":     risk_level,
                    "within_city":    in_city,
                    "acq_dates":      acq_dates,
                    "satellites":     satellites,
                    "color":          _RISK_COLORS[risk_level],
                })

    cells.sort(key=lambda c: c["total_frp_mw"], reverse=True)

    active_levels = [c["risk_level"] for c in cells if c["risk_level"] != "none"]
    overall = max(active_levels, key=lambda l: _LEVEL_ORDER.index(l)) if active_levels else "none"

    n_sig = 0
    if not fire_df.empty and "frp" in fire_df.columns:
        n_sig = int((fire_df["frp"] >= _rules.get("fire", "frp_detection_floor_mw", default=5.0)).sum())

    return {
        "dashboard_id":   str(uuid.uuid4()),
        "generated_at":   now,
        "city_id":        city_id,
        "h3_resolution":  h3_resolution,
        "risk_cells":     cells,
        "risk_summary": {
            "overall_risk_level":  overall,
            "total_hotspots":      n_sig,
            "hotspots_in_city":    total_city_hotspots,
            "active_cells":        sum(1 for c in cells if c["risk_level"] != "none"),
            "city_cells":          sum(1 for c in cells if c["within_city"]),
            "max_frp_mw":          round(max_frp_seen, 2),
            "total_frp_mw":        round(sum(c["total_frp_mw"] for c in cells), 2),
        },
        "active_warnings": _build_warnings(overall, total_city_hotspots, max_frp_seen),
        "data_quality_flag": "live" if not fire_df.empty else "no_data",
    }


def _build_warnings(overall: str, n_city: int, max_frp: float) -> list[dict]:
    warnings = []
    if n_city > 0:
        warnings.append({
            "warning_id": "FIRE_WITHIN_CITY",
            "severity":   "error" if n_city >= _rules.get("fire", "in_city_alert_error_threshold", default=3) else "warning",
            "message":    f"{n_city} active fire hotspot(s) detected within city boundary.",
        })
    if overall in ("high", "severe"):
        warnings.append({
            "warning_id": "HIGH_FIRE_INTENSITY",
            "severity":   "warning",
            "message":    f"High fire intensity — max FRP {max_frp:.0f} MW. Expect PM2.5 elevation downwind.",
        })
    return warnings


# ── Decision packet builder ────────────────────────────────────────────────

def build_fire_decision_packets(
    fire_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    """Return decision packets for the top-N cells by total FRP."""
    dashboard = build_fire_dashboard(
        fire_df, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max
    )
    active = [c for c in dashboard["risk_cells"] if c["risk_level"] != "none"][:top_n]

    packets = []
    for c in active:
        acq_detail = ", ".join(c["acq_dates"][:2]) or "—"
        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "fire_assessment": {
                "risk_level":   c["risk_level"],
                "fire_count":   c["fire_count"],
                "total_frp_mw": c["total_frp_mw"],
                "max_frp_mw":   c["max_frp_mw"],
                "within_city":  c["within_city"],
            },
            "field_verification_required": c["risk_level"] in ("high", "severe"),
            "confidence": {
                "confidence_score":       c["risk_score"],
                "recommendation_allowed": c["risk_score"] >= 0.3,
            },
            "evidence": {
                "inputs": [
                    {"name": "total_frp_mw",   "value": c["total_frp_mw"],  "unit": "MW"},
                    {"name": "max_frp_mw",     "value": c["max_frp_mw"],    "unit": "MW"},
                    {"name": "fire_count",     "value": c["fire_count"],    "unit": "detections"},
                    {"name": "avg_confidence", "value": c["avg_confidence"],"unit": "%"},
                ],
            },
            "review_guidance": {
                "review_prompts": [
                    "Confirm fire via satellite imagery (Sentinel-2 or Google Maps).",
                    "Check prevailing wind direction — determines AQI impact corridor.",
                    "Assess proximity to residential areas, hospitals, and schools.",
                    "Verify whether this is a controlled agricultural burn or uncontrolled wildfire.",
                ],
                "when_not_to_act": [
                    "Detections with confidence < 40% in agricultural zones during harvest season may be controlled burns.",
                    "Single-pixel detections with FRP < 10 MW may be industrial heat sources.",
                    "Do not issue evacuation orders based solely on satellite detection.",
                ],
            },
            "safety_gates": [
                {
                    "gate":        "satellite_confirmation",
                    "required":    c["risk_level"] in ("high", "severe"),
                    "description": "Cross-verify with Sentinel-2 or Landsat before escalating.",
                },
                {
                    "gate":        "wind_direction_assessment",
                    "required":    True,
                    "description": "Check IMD wind forecast before issuing air quality advisory.",
                },
            ],
            "blocked_uses": [
                "automated_evacuation_order",
                "direct_resource_dispatch_without_field_verification",
            ],
            "data_source_status": [
                {
                    "source":  "firms_viirs",
                    "status":  "live",
                    "label":   "NASA FIRMS VIIRS SNPP",
                    "detail":  f"{c['fire_count']} detection(s) on {acq_detail}",
                }
            ],
        })
    return packets
