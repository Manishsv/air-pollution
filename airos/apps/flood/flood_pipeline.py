"""
Flood risk scoring pipeline.

Combines rainfall observations (IDW-interpolated to H3 grid) with
flood incident counts and drainage asset coverage to produce:
  - Per-H3-cell flood risk grid (flood_risk_dashboard consumer contract)
  - Top-N decision packets for highest-risk cells (flood_decision_packet contract)

Risk score formula
------------------
  rainfall_score  = min(rainfall_mm_per_hr / 20.0, 1.0)   # 20 mm/hr → max
  incident_score  = min(incident_count / 3.0, 1.0)         # 3+ incidents → max
  drainage_factor = max(0.75, 1.0 − asset_count × 0.05)    # up to 25% reduction
  flood_risk_score = (0.6 × rainfall_score + 0.4 × incident_score) × drainage_factor

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

from airos.os.rules import rules as _rules

logger = logging.getLogger(__name__)

_DECISION_PACKET_TOP_N = 5
_SPEC_ROOT = Path(__file__).resolve().parents[3] / "specifications"


# ── Haversine + IDW ───────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2)
    return R * 2 * np.arcsin(np.sqrt(a))


def _idw_interpolate(
    cell_lat: float,
    cell_lon: float,
    obs_lats: np.ndarray,
    obs_lons: np.ndarray,
    obs_vals: np.ndarray,
    power: float = 2.0,
) -> float:
    """IDW estimate for a cell from observation points. Returns NaN if no obs."""
    dists = np.array([_haversine_km(cell_lat, cell_lon, la, lo)
                      for la, lo in zip(obs_lats, obs_lons)])
    dists = np.maximum(dists, 0.05)         # 50 m floor
    weights = 1.0 / np.power(dists, power)
    total_w = weights.sum()
    if total_w == 0:
        return float("nan")
    return float(np.dot(weights, obs_vals) / total_w)


# ── H3 grid ───────────────────────────────────────────────────────────────

def build_h3_grid_from_bbox(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    h3_resolution: int,
) -> pd.DataFrame:
    """Return DataFrame with columns h3_id, centroid_lat, centroid_lon."""
    import h3

    bbox_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min], [lon_max, lat_min],
            [lon_max, lat_max], [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }
    cell_ids = list(h3.geo_to_cells(bbox_geojson, h3_resolution))
    rows = []
    for cid in cell_ids:
        clat, clon = h3.cell_to_latlng(cid)
        rows.append({"h3_id": cid, "centroid_lat": clat, "centroid_lon": clon})
    return pd.DataFrame(rows)


# ── Risk helpers ──────────────────────────────────────────────────────────

def _risk_level(score: float) -> str:
    t = _rules.get("flood", "risk_levels", default={"severe": 0.75, "high": 0.50, "moderate": 0.25})
    if score >= t["severe"]:   return "severe"
    if score >= t["high"]:     return "high"
    if score >= t["moderate"]: return "moderate"
    return "low"


def _risk_color(level: str) -> list[int]:
    return {
        "severe": [139, 0, 0, 210],
        "high":   [220, 50, 50, 190],
        "moderate": [255, 140, 0, 170],
        "low":    [100, 149, 237, 150],
    }.get(level, [173, 216, 230, 130])


def _overall_risk(cells_df: pd.DataFrame) -> str:
    """Return worst observed risk level across all cells."""
    for level in ("severe", "high", "moderate", "low"):
        if (cells_df["risk_level"] == level).any():
            return level
    return "low"


def _data_quality_flag(rainfall_df: pd.DataFrame) -> str:
    if rainfall_df.empty:
        return "unavailable"
    if (rainfall_df.get("quality_flag", pd.Series()) == "synthetic").any():
        return "synthetic"
    return "real"


def _sources(rainfall_df: pd.DataFrame, incidents_df: pd.DataFrame,
             assets_df: pd.DataFrame) -> list[str]:
    srcs = []
    if not rainfall_df.empty:
        ds = rainfall_df.get("data_source", pd.Series()).dropna().unique().tolist()
        srcs.extend(ds or ["openmeteo"])
    if not incidents_df.empty:
        srcs.append("flood_incidents")
    if not assets_df.empty:
        srcs.append("drainage_assets")
    return srcs or ["unavailable"]


def _source_status(
    rainfall_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    assets_df: pd.DataFrame,
) -> list[dict]:
    """
    Per-source status for display: live | stale | unavailable.

    live      — real-time feed, data current
    stale     — data present but synthetic/unverified/static registry
    unavailable — no data returned
    """
    statuses = []

    if rainfall_df.empty:
        statuses.append({
            "source": "rainfall", "label": "Rainfall API",
            "status": "unavailable", "detail": "No rainfall data returned",
        })
    else:
        qflags = set(rainfall_df.get("quality_flag", pd.Series()).dropna().tolist())
        is_synthetic = "synthetic" in qflags
        ds = (rainfall_df["data_source"].dropna().iloc[0]
              if "data_source" in rainfall_df.columns and len(rainfall_df) > 0
              else "openmeteo")
        ts = (str(rainfall_df["timestamp"].dropna().iloc[0])[:16]
              if "timestamp" in rainfall_df.columns and len(rainfall_df) > 0
              else "—")
        statuses.append({
            "source": "rainfall",
            "label": f"{ds} Rainfall API",
            "status": "stale" if is_synthetic else "live",
            "detail": (
                f"{'Synthetic demo' if is_synthetic else 'Real-time'} · "
                f"{len(rainfall_df)} grid points · {ts}"
            ),
        })

    if incidents_df.empty:
        statuses.append({
            "source": "incidents", "label": "Flood Incident Reports",
            "status": "unavailable", "detail": "No incident data",
        })
    else:
        statuses.append({
            "source": "incidents", "label": "Flood Incident Reports",
            "status": "stale",
            "detail": f"Unverified citizen reports · {len(incidents_df)} event(s)",
        })

    if assets_df.empty:
        statuses.append({
            "source": "drainage_assets", "label": "Drainage Asset Registry",
            "status": "unavailable", "detail": "No drainage asset data",
        })
    else:
        statuses.append({
            "source": "drainage_assets", "label": "Drainage Asset Registry",
            "status": "stale",
            "detail": f"Static registry · {len(assets_df)} asset(s)",
        })

    return statuses


def _computation_trace(
    h3_row: "pd.Series",
    dqf: str,
    n_rain_points: int,
) -> dict:
    """Explainable breakdown of the scoring formula for one H3 cell."""
    rain_val = float(h3_row["rainfall_mm_per_hr"] or 0.0)
    inc_count = int(h3_row["incident_count"])
    ast_count = int(h3_row["asset_count"])

    _rain_sat = _rules.get("flood", "rainfall_score_saturation_mm_hr", default=20.0)
    _inc_sat  = _rules.get("flood", "incident_score_saturation_count", default=3)
    _w        = _rules.get("flood", "score_weights", default={"rainfall": 0.6, "incident": 0.4})
    _df_min   = _rules.get("flood", "drainage_factor_min", default=0.75)
    _df_dec   = _rules.get("flood", "drainage_factor_decrement_per_asset", default=0.05)
    rainfall_score = min(rain_val / _rain_sat, 1.0)
    incident_score = min(inc_count / _inc_sat, 1.0)
    drainage_factor = max(_df_min, 1.0 - ast_count * _df_dec)
    final_score = (_w["rainfall"] * rainfall_score + _w["incident"] * incident_score) * drainage_factor

    return {
        "algorithm": "IDW-weighted flood risk scoring (v1)",
        "formula": f"flood_risk_score = ({_w['rainfall']} × rainfall_score + {_w['incident']} × incident_score) × drainage_factor",
        "steps": [
            {
                "name": "rainfall_score",
                "formula": f"min(rainfall_mm_per_hr / {_rain_sat}, 1.0)",
                "inputs": {"rainfall_mm_per_hr": round(rain_val, 3),
                           "interpolation": f"IDW from {n_rain_points} sample points"},
                "value": round(rainfall_score, 4),
                "weight": _w["rainfall"],
            },
            {
                "name": "incident_score",
                "formula": f"min(incident_count / {_inc_sat}, 1.0)",
                "inputs": {"incident_count_within_500m": inc_count},
                "value": round(incident_score, 4),
                "weight": 0.4,
            },
            {
                "name": "drainage_factor",
                "formula": "max(0.75, 1.0 - asset_count × 0.05)",
                "inputs": {"drainage_assets_within_500m": ast_count},
                "value": round(drainage_factor, 4),
                "note": "Reduces score by up to 25% when drainage assets are present",
            },
            {
                "name": "flood_risk_score",
                "formula": "(0.6 × rainfall_score + 0.4 × incident_score) × drainage_factor",
                "inputs": {
                    "rainfall_score": round(rainfall_score, 4),
                    "incident_score": round(incident_score, 4),
                    "drainage_factor": round(drainage_factor, 4),
                },
                "value": round(final_score, 4),
            },
        ],
        "data_quality_flag": dqf,
    }


# ── Core pipeline ─────────────────────────────────────────────────────────

def run_flood_pipeline(
    rainfall_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    assets_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
) -> dict:
    """
    Run the flood risk scoring pipeline.

    Parameters
    ----------
    rainfall_df : DataFrame
        Columns: latitude, longitude, rainfall_intensity_mm_per_hr, quality_flag.
        Empty DataFrame → data_quality_flag="unavailable", all cells score 0.
    incidents_df : DataFrame
        Columns: latitude, longitude, severity (optional).
        Empty → no incident contribution to risk scores.
    assets_df : DataFrame
        Columns: latitude, longitude.
        Empty → no drainage relief applied.

    Returns
    -------
    dict with keys:
        risk_cells      — DataFrame (h3_id, rainfall_mm_per_hr, incident_count,
                          asset_count, flood_risk_score, risk_level, color)
        data_quality_flag — "real" | "synthetic" | "unavailable"
        city_id
        summary         — counts by risk level + aggregate stats
    """
    h3_grid = build_h3_grid_from_bbox(lat_min, lon_min, lat_max, lon_max, h3_resolution)
    dqf = _data_quality_flag(rainfall_df)

    # ── Rainfall IDW ──────────────────────────────────────────────────────
    has_rain = (not rainfall_df.empty
                and "rainfall_intensity_mm_per_hr" in rainfall_df.columns
                and rainfall_df["rainfall_intensity_mm_per_hr"].notna().any())
    if has_rain:
        obs_lats = rainfall_df["latitude"].values
        obs_lons = rainfall_df["longitude"].values
        obs_rain = rainfall_df["rainfall_intensity_mm_per_hr"].values

    # ── Incident + asset arrays ───────────────────────────────────────────
    inc_lats = (incidents_df["latitude"].values
                if not incidents_df.empty and "latitude" in incidents_df.columns
                else np.array([]))
    inc_lons = (incidents_df["longitude"].values
                if not incidents_df.empty and "longitude" in incidents_df.columns
                else np.array([]))

    ast_lats = (assets_df["latitude"].values
                if not assets_df.empty and "latitude" in assets_df.columns
                else np.array([]))
    ast_lons = (assets_df["longitude"].values
                if not assets_df.empty and "longitude" in assets_df.columns
                else np.array([]))

    # ── Per-cell scoring ──────────────────────────────────────────────────
    rows = []
    for _, cell in h3_grid.iterrows():
        clat, clon = cell["centroid_lat"], cell["centroid_lon"]

        if has_rain:
            rain_val = _idw_interpolate(clat, clon, obs_lats, obs_lons, obs_rain)
            _rain_sat = _rules.get("flood", "rainfall_score_saturation_mm_hr", default=20.0)
            rain_score = min(rain_val / _rain_sat, 1.0)
        else:
            rain_val, rain_score = 0.0, 0.0

        _prox   = _rules.get("flood", "proximity_radius_km", default=0.5)
        _inc_sat = _rules.get("flood", "incident_score_saturation_count", default=3)
        inc_count = int(sum(
            1 for ilat, ilon in zip(inc_lats, inc_lons)
            if _haversine_km(clat, clon, ilat, ilon) <= _prox
        ))
        inc_score = min(inc_count / _inc_sat, 1.0)

        ast_count = int(sum(
            1 for alat, alon in zip(ast_lats, ast_lons)
            if _haversine_km(clat, clon, alat, alon) <= _prox
        ))
        _df_min = _rules.get("flood", "drainage_factor_min", default=0.75)
        _df_dec = _rules.get("flood", "drainage_factor_decrement_per_asset", default=0.05)
        drainage_factor = max(_df_min, 1.0 - ast_count * _df_dec)

        _w = _rules.get("flood", "score_weights", default={"rainfall": 0.6, "incident": 0.4})
        score = (_w["rainfall"] * rain_score + _w["incident"] * inc_score) * drainage_factor
        level = _risk_level(score)

        rows.append({
            "h3_id": cell["h3_id"],
            "rainfall_mm_per_hr": round(float(rain_val), 3) if has_rain else None,
            "incident_count": inc_count,
            "asset_count": ast_count,
            "flood_risk_score": round(score, 4),
            "risk_level": level,
            "color": _risk_color(level),
        })

    risk_cells = pd.DataFrame(rows)

    try:
        from airos.drivers.feature_store.writer import FeatureStoreWriter
        with FeatureStoreWriter() as fsw:
            fsw.write_flood_features(risk_cells, city_id=city_id, data_quality_flag=dqf)
    except Exception as _fse:
        logger.warning("feature_store write skipped: %s", _fse)

    counts = risk_cells["risk_level"].value_counts().to_dict()
    return {
        "risk_cells": risk_cells,
        "data_quality_flag": dqf,
        "city_id": city_id,
        "summary": {
            "total_cells": len(risk_cells),
            "severe_count": counts.get("severe", 0),
            "high_count": counts.get("high", 0),
            "moderate_count": counts.get("moderate", 0),
            "low_count": counts.get("low", 0),
            "max_rainfall_mm_per_hr": (
                float(risk_cells["rainfall_mm_per_hr"].max())
                if has_rain and not risk_cells["rainfall_mm_per_hr"].isna().all()
                else None
            ),
            "total_incident_count": len(incidents_df),
            "total_asset_count": len(assets_df),
        },
    }


# ── Consumer contract builders ────────────────────────────────────────────

def build_flood_risk_dashboard(
    rainfall_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    assets_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
) -> dict:
    """
    Build the flood_risk_dashboard consumer contract.

    Returns a dict that validates against
    specifications/consumer_contracts/flood_risk_dashboard.v1.schema.json.
    """
    now = datetime.now(timezone.utc).isoformat()
    pipeline = run_flood_pipeline(
        rainfall_df, incidents_df, assets_df,
        h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    risk_cells = pipeline["risk_cells"]
    summary = pipeline["summary"]
    dqf = pipeline["data_quality_flag"]
    synthetic_used = dqf == "synthetic"

    # ── Map layers ────────────────────────────────────────────────────────
    map_layers = [
        {"layer_id": "flood_risk_grid", "layer_type": "h3_hexagon",
         "title": "Flood Risk Grid (H3)"},
    ]
    if not incidents_df.empty:
        map_layers.append({
            "layer_id": "flood_incidents", "layer_type": "point",
            "title": "Reported Incidents",
        })
    if not assets_df.empty:
        map_layers.append({
            "layer_id": "drainage_assets", "layer_type": "point",
            "title": "Drainage Assets",
        })

    # ── Risk areas (top high/severe H3 cells exposed as named areas) ──────
    high_cells = risk_cells[risk_cells["risk_level"].isin(["high", "severe"])]
    risk_areas = [
        {
            "area_id": row["h3_id"],
            "risk_level": row["risk_level"],
            "confidence_score": round(row["flood_risk_score"], 3),
            "uncertainty": {
                "notes": "IDW-interpolated rainfall; low-lying terrain proxy unavailable",
            },
        }
        for _, row in high_cells.head(10).iterrows()
    ]
    if not risk_areas:
        top = risk_cells.nlargest(1, "flood_risk_score").iloc[0]
        risk_areas = [{
            "area_id": top["h3_id"],
            "risk_level": top["risk_level"],
            "confidence_score": round(top["flood_risk_score"], 3),
            "uncertainty": {"notes": "No high-risk cells detected; lowest-risk cell shown"},
        }]

    # ── Active warnings ───────────────────────────────────────────────────
    warnings = [{
        "warning_id": "decision_support_only",
        "severity": "error",
        "message": (
            "Decision support only. Do not issue emergency orders or public advisories "
            "from this output without authorised human review."
        ),
    }, {
        "warning_id": "low_lying_proxy_unavailable",
        "severity": "warning",
        "message": (
            "Low-lying terrain proxy not available. Risk may be underestimated in "
            "low-elevation areas. Field verification required."
        ),
    }]
    if dqf == "synthetic":
        warnings.append({
            "warning_id": "synthetic_data",
            "severity": "warning",
            "message": "Rainfall data is synthetic demo data. Do not use for operational decisions.",
        })
    if dqf == "unavailable":
        warnings.append({
            "warning_id": "data_unavailable",
            "severity": "error",
            "message": "Rainfall data unavailable. All risk scores are unreliable.",
        })

    # ── Recommended review queue ──────────────────────────────────────────
    review_queue = [
        {
            "packet_id": f"pkt_{row['h3_id'][:8]}",
            "priority": "high" if row["risk_level"] in ("high", "severe") else "medium",
            "reason": (
                f"{row['risk_level'].capitalize()} flood risk — "
                f"{row['incident_count']} nearby incident(s), "
                f"{row['rainfall_mm_per_hr'] or 0:.1f} mm/hr rainfall"
            ),
        }
        for _, row in high_cells.head(5).iterrows()
    ]
    if not review_queue:
        review_queue = [{
            "packet_id": "pkt_placeholder",
            "priority": "low",
            "reason": "No high-risk areas detected in current observation window.",
        }]

    # ── Risk cells list for map rendering ─────────────────────────────────
    risk_cells_list = [
        {
            "h3_id": r["h3_id"],
            "risk_level": r["risk_level"],
            "confidence_score": round(r["flood_risk_score"], 3),
        }
        for _, r in risk_cells.iterrows()
    ]

    return {
        "generated_at": now,
        "city_id": city_id,
        "data_quality_flag": dqf,
        "risk_summary": {
            "overall_risk_level": _overall_risk(risk_cells),
            "time_window": "now_to_next_3_hours",
            "headline": (
                f"{summary['high_count'] + summary['severe_count']} high/severe risk cells — "
                f"max rainfall {summary['max_rainfall_mm_per_hr'] or 0:.1f} mm/hr"
            ),
        },
        "map_layers": map_layers,
        "risk_cells": risk_cells_list,
        "risk_areas": risk_areas,
        "active_warnings": warnings,
        "data_quality_summary": {
            "synthetic_data_used": synthetic_used,
            "confidence_note": (
                "Risk scores are IDW-interpolated from a sparse 3×3 observation grid. "
                "Low-lying terrain proxy not available. Human review required."
            ),
        },
        "recommended_review_queue": review_queue,
        "provenance_summary": {
            "sources": _sources(rainfall_df, incidents_df, assets_df),
            "synthetic_used": synthetic_used,
        },
        "summary": summary,
    }


def build_flood_decision_packets(
    rainfall_df: pd.DataFrame,
    incidents_df: pd.DataFrame,
    assets_df: pd.DataFrame,
    h3_resolution: int,
    city_id: str,
    lat_min: float = 0.0,
    lon_min: float = 0.0,
    lat_max: float = 1.0,
    lon_max: float = 1.0,
    top_n: int = _DECISION_PACKET_TOP_N,
) -> list[dict]:
    """
    Build top-N flood_decision_packet consumer contracts for highest-risk H3 cells.

    Each returned dict validates against
    specifications/consumer_contracts/flood_decision_packet.v1.schema.json.
    Returns at least one packet even when all cells are low-risk.
    """
    now = datetime.now(timezone.utc).isoformat()
    pipeline = run_flood_pipeline(
        rainfall_df, incidents_df, assets_df,
        h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    risk_cells = pipeline["risk_cells"]
    dqf = pipeline["data_quality_flag"]
    top_cells = risk_cells.nlargest(max(top_n, 1), "flood_risk_score")

    src_status = _source_status(rainfall_df, incidents_df, assets_df)

    packets = []
    for _, row in top_cells.iterrows():
        uid = hashlib.sha1(f"flood_{row['h3_id']}_{now}".encode()).hexdigest()[:10]
        rain_val = row["rainfall_mm_per_hr"]
        primary_driver = (
            "rainfall_intensity" if rain_val and rain_val >= 5.0
            else "flood_incident" if row["incident_count"] > 0
            else "rainfall_accumulation"
        )
        block_reason = (
            "IDW-interpolated rainfall estimates require field verification "
            "before any operational action."
        )
        if dqf == "synthetic":
            block_reason = "Synthetic demo data — operational action blocked. " + block_reason
        if dqf == "unavailable":
            block_reason = "Rainfall data unavailable — all scores unreliable. " + block_reason

        trace = _computation_trace(row, dqf, len(rainfall_df))

        packets.append({
            "packet_id": f"pkt_{uid}",
            "domain_id": "flood_risk",
            "timestamp": now,
            "h3_id": row["h3_id"],
            "risk_assessment": {
                "risk_level": row["risk_level"],
                "time_window": "now_to_next_3_hours",
                "primary_driver": primary_driver,
            },
            "evidence": {
                "inputs": [
                    {"name": "rainfall_mm_per_hr",
                     "value": round(rain_val, 2) if rain_val is not None else None,
                     "unit": "mm/hr"},
                    {"name": "incident_count_500m",
                     "value": row["incident_count"]},
                    {"name": "drainage_asset_count_500m",
                     "value": row["asset_count"]},
                    {"name": "flood_risk_score",
                     "value": round(row["flood_risk_score"], 4)},
                ],
                "notes": (
                    f"IDW-interpolated from {len(rainfall_df)} rainfall sample points. "
                    f"Data quality: {dqf}."
                ),
            },
            "data_source_status": src_status,
            "computation_trace": trace,
            "provenance": {
                "sources": _sources(rainfall_df, incidents_df, assets_df),
                "city_id": city_id,
                "data_quality_flag": dqf,
            },
            "confidence": {
                "confidence_score": round(row["flood_risk_score"], 3),
                "recommendation_allowed": False,
                "recommendation_block_reason": block_reason,
            },
            "uncertainty": {
                "idw_interpolation": "Temperature peaks at observation points; areas without observations estimated by distance weighting.",
                "low_lying_proxy": "Low-lying terrain data unavailable; true inundation risk may differ.",
                "data_quality": dqf,
            },
            "recommended_action": (
                "Review rainfall data and incident reports. "
                "Dispatch field verification if risk level is high or severe. "
                "Do not treat IDW estimates as confirmed flood events."
            ),
            "review_guidance": {
                "review_prompts": [
                    "Has field verification confirmed active waterlogging at this location?",
                    "Are drainage assets in this cell functional and unblocked?",
                    "Are vulnerable populations, roads, or assets at immediate risk?",
                    "Is rainfall accumulation consistent with measured gauge data?",
                ],
                "when_not_to_act": [
                    "Do not issue emergency orders based solely on IDW-interpolated estimates.",
                    "Do not act on synthetic or unverified data without field confirmation.",
                    "Do not bypass field verification for emergency dispatch.",
                ],
            },
            "safety_gates": [{
                "gate_id": "field_verification_required",
                "status": "blocked",
                "message": (
                    "Field verification must be completed before any emergency dispatch "
                    "or public advisory action."
                ),
            }],
            "blocked_uses": [
                "automatic_emergency_dispatch_without_human_review",
                "treat_idw_estimates_as_confirmed_flood_events",
                "public_advisory_without_field_verification",
            ],
            "field_verification_required": True,
        })

    return packets
