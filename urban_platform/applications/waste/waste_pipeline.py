"""Waste monitoring pipeline.

Combines three satellite signals into per-H3-cell waste risk:

  waste_burn      FIRMS VIIRS  FRP 5-30 MW inside/near city → probable urban waste burn
  landfill_fire   FIRMS VIIRS  Same H3 cell detected on ≥ 2 separate days → persistent site
  dump_site       Sentinel-2   NDVI < 0.15 in non-water urban cell → exposed waste/debris
  landfill_gas    Sentinel-5P  CH4 > background + 20 ppb → active landfill decomposition
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

# ── Thresholds ─────────────────────────────────────────────────────────────

_WASTE_BURN_FRP_MAX   = 30.0   # MW — above this → likely wildfire, not waste
_WASTE_BURN_FRP_MIN   =  5.0   # MW — minimum detectable
_PERSIST_DAYS_MIN     =  2     # days a cell must appear to be "persistent"
_NDVI_DUMP_THRESHOLD  =  0.15  # below → likely exposed waste
_CH4_BACKGROUND_PPB   = 1880.0
_CH4_ELEV_MODERATE    =   20.0 # ppb above background
_CH4_ELEV_HIGH        =   40.0

_LEVEL_ORDER = ["none", "low", "moderate", "high", "severe"]

_WASTE_TYPE_COLORS = {
    "none":           [200, 200, 200, 50],
    "waste_burn":     [255, 180, 0,   180],
    "landfill_fire":  [220, 80,  0,   210],
    "dump_site":      [139, 100, 20,  180],
    "landfill_gas":   [140, 0,   200, 170],
    "combined":       [140, 0,   0,   230],
}


# ── FIRMS waste signal extraction ──────────────────────────────────────────

def _extract_burn_signals(firms_df: pd.DataFrame, h3_resolution: int) -> dict[str, dict]:
    """Classify FIRMS detections as waste burns or persistent landfill fires.

    Returns {h3_id: {waste_type, fire_count, total_frp_mw, active_days, dates, in_city}}
    """
    if firms_df.empty or not {"latitude", "longitude", "frp"}.issubset(firms_df.columns):
        return {}

    try:
        import h3 as _h3
    except ImportError:
        return {}

    sig = firms_df[
        (firms_df["frp"] >= _WASTE_BURN_FRP_MIN) &
        (firms_df["frp"] <= _WASTE_BURN_FRP_MAX)
    ].copy()

    if sig.empty:
        return {}

    sig["h3_id"] = [
        _h3.latlng_to_cell(float(lat), float(lon), h3_resolution)
        for lat, lon in zip(sig["latitude"], sig["longitude"])
    ]

    cells: dict[str, dict] = {}
    for h3_id, grp in sig.groupby("h3_id"):
        dates    = sorted(grp["acq_date"].astype(str).unique().tolist()) if "acq_date" in grp.columns else []
        in_city  = bool(grp["within_bbox"].any()) if "within_bbox" in grp.columns else False
        n_days   = len(dates)
        total_frp = float(grp["frp"].sum())
        waste_type = "landfill_fire" if n_days >= _PERSIST_DAYS_MIN else "waste_burn"

        cells[h3_id] = {
            "waste_type":    waste_type,
            "fire_count":    len(grp),
            "total_frp_mw":  round(total_frp, 2),
            "active_days":   n_days,
            "dates":         dates,
            "within_city":   in_city,
        }
    return cells


# ── NDVI signal ────────────────────────────────────────────────────────────

def _classify_ndvi(ndvi_map: dict[str, float]) -> dict[str, dict]:
    """Return {h3_id: dump_site_info} for cells with low NDVI."""
    result = {}
    for h3_id, ndvi in ndvi_map.items():
        if ndvi < _NDVI_DUMP_THRESHOLD:
            severity = "high" if ndvi < 0.05 else "moderate" if ndvi < 0.10 else "low"
            result[h3_id] = {"ndvi": ndvi, "severity": severity}
    return result


# ── CH4 signal ─────────────────────────────────────────────────────────────

def _classify_ch4(ch4_map: dict[str, float]) -> dict[str, dict]:
    """Return {h3_id: landfill_gas_info} for cells with elevated CH4."""
    result = {}
    for h3_id, ch4 in ch4_map.items():
        elev = ch4 - _CH4_BACKGROUND_PPB
        if elev >= _CH4_ELEV_MODERATE:
            severity = "high" if elev >= _CH4_ELEV_HIGH else "moderate"
            result[h3_id] = {"ch4_ppb": ch4, "elevation_ppb": round(elev, 1), "severity": severity}
    return result


# ── Risk score ─────────────────────────────────────────────────────────────

def _compute_risk(burn: dict | None, dump: dict | None, gas: dict | None) -> tuple[float, str]:
    scores = []
    if burn:
        base = 0.4 if burn["waste_type"] == "waste_burn" else 0.65
        scores.append(min(1.0, base + math.log1p(burn["total_frp_mw"]) / math.log1p(30) * 0.35))
    if dump:
        scores.append({"low": 0.3, "moderate": 0.55, "high": 0.75}.get(dump["severity"], 0.3))
    if gas:
        scores.append({"moderate": 0.5, "high": 0.80}.get(gas["severity"], 0.3))

    if not scores:
        return 0.0, "none"
    score = max(scores)
    level = (
        "severe"   if score >= 0.85 else
        "high"     if score >= 0.65 else
        "moderate" if score >= 0.45 else
        "low"      if score >= 0.25 else
        "none"
    )
    return round(score, 4), level


def _dominant_type(burn: dict | None, dump: dict | None, gas: dict | None) -> str:
    if burn and dump and gas:
        return "combined"
    if burn:
        return burn["waste_type"]
    if dump:
        return "dump_site"
    if gas:
        return "landfill_gas"
    return "none"


# ── Dashboard builder ──────────────────────────────────────────────────────

def build_waste_dashboard(
    firms_df: pd.DataFrame,
    ndvi_map: dict[str, float],
    ch4_map: dict[str, float],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    burn_cells = _extract_burn_signals(firms_df, h3_resolution)
    dump_cells = _classify_ndvi(ndvi_map)
    gas_cells  = _classify_ch4(ch4_map)

    all_ids = set(burn_cells) | set(dump_cells) | set(gas_cells)
    cells: list[dict] = []

    for h3_id in all_ids:
        burn = burn_cells.get(h3_id)
        dump = dump_cells.get(h3_id)
        gas  = gas_cells.get(h3_id)

        risk_score, risk_level = _compute_risk(burn, dump, gas)
        dom_type = _dominant_type(burn, dump, gas)

        cells.append({
            "h3_id":          h3_id,
            "dominant_type":  dom_type,
            "risk_score":     risk_score,
            "risk_level":     risk_level,
            "color":          _WASTE_TYPE_COLORS.get(dom_type, _WASTE_TYPE_COLORS["none"]),
            # burn signal
            "waste_type":     burn["waste_type"]    if burn else None,
            "fire_count":     burn["fire_count"]    if burn else 0,
            "total_frp_mw":   burn["total_frp_mw"]  if burn else 0.0,
            "active_days":    burn["active_days"]   if burn else 0,
            "fire_dates":     burn["dates"]         if burn else [],
            "within_city":    burn["within_city"]   if burn else False,
            # dump signal
            "ndvi":           dump["ndvi"]          if dump else None,
            "dump_severity":  dump["severity"]      if dump else None,
            # gas signal
            "ch4_ppb":        gas["ch4_ppb"]        if gas else None,
            "ch4_elevation":  gas["elevation_ppb"]  if gas else None,
            "gas_severity":   gas["severity"]       if gas else None,
        })

    cells.sort(key=lambda c: c["risk_score"], reverse=True)

    active_levels = [c["risk_level"] for c in cells if c["risk_level"] != "none"]
    overall = max(active_levels, key=lambda l: _LEVEL_ORDER.index(l)) if active_levels else "none"

    n_burns      = sum(1 for c in cells if c["waste_type"] in ("waste_burn", "landfill_fire"))
    n_persistent = sum(1 for c in cells if c["waste_type"] == "landfill_fire")
    n_dumps      = sum(1 for c in cells if c["dump_severity"])
    n_gas        = sum(1 for c in cells if c["gas_severity"])

    return {
        "dashboard_id":  str(uuid.uuid4()),
        "generated_at":  now,
        "city_id":       city_id,
        "h3_resolution": h3_resolution,
        "risk_cells":    cells,
        "risk_summary": {
            "overall_risk_level":    overall,
            "waste_burn_cells":      n_burns,
            "persistent_burn_cells": n_persistent,
            "dump_site_cells":       n_dumps,
            "landfill_gas_cells":    n_gas,
            "total_active_cells":    len(cells),
        },
        "active_warnings": _build_warnings(overall, n_burns, n_persistent, n_dumps, n_gas),
        "data_quality_flag": "live" if (not firms_df.empty or ndvi_map or ch4_map) else "no_data",
        "signal_availability": {
            "firms": not firms_df.empty,
            "sentinel2_ndvi": bool(ndvi_map),
            "sentinel5p_ch4": bool(ch4_map),
        },
    }


def _build_warnings(
    overall: str, n_burns: int, n_persistent: int, n_dumps: int, n_gas: int
) -> list[dict]:
    warnings = []
    if n_persistent > 0:
        warnings.append({
            "warning_id": "PERSISTENT_LANDFILL_FIRE",
            "severity":   "error",
            "message":    f"{n_persistent} persistent fire site(s) detected — active on multiple days, likely landfill.",
        })
    if n_burns > 0:
        warnings.append({
            "warning_id": "WASTE_BURNING_DETECTED",
            "severity":   "warning",
            "message":    f"{n_burns} waste burn site(s) detected. Open burning elevates PM2.5 and toxic emissions.",
        })
    if n_dumps > 0:
        warnings.append({
            "warning_id": "DUMP_SITE_IDENTIFIED",
            "severity":   "warning",
            "message":    f"{n_dumps} H3 cell(s) show low NDVI consistent with open dump sites.",
        })
    if n_gas > 0:
        warnings.append({
            "warning_id": "LANDFILL_GAS_DETECTED",
            "severity":   "warning",
            "message":    f"{n_gas} cell(s) show elevated methane — active landfill decomposition.",
        })
    return warnings


# ── Decision packet builder ────────────────────────────────────────────────

def build_waste_decision_packets(
    firms_df: pd.DataFrame,
    ndvi_map: dict[str, float],
    ch4_map: dict[str, float],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    dashboard = build_waste_dashboard(
        firms_df, ndvi_map, ch4_map,
        h3_resolution, city_id,
        lat_min, lon_min, lat_max, lon_max,
    )
    active = [c for c in dashboard["risk_cells"] if c["risk_level"] != "none"][:top_n]

    packets = []
    for c in active:
        evidence_inputs = []
        if c["fire_count"]:
            evidence_inputs += [
                {"name": "waste_type",    "value": c["waste_type"],    "unit": "—"},
                {"name": "total_frp_mw",  "value": c["total_frp_mw"],  "unit": "MW"},
                {"name": "active_days",   "value": c["active_days"],   "unit": "days"},
            ]
        if c["ndvi"] is not None:
            evidence_inputs.append({"name": "ndvi", "value": c["ndvi"], "unit": "index"})
        if c["ch4_ppb"] is not None:
            evidence_inputs += [
                {"name": "ch4_ppb",       "value": c["ch4_ppb"],       "unit": "ppb"},
                {"name": "ch4_elevation", "value": c["ch4_elevation"],  "unit": "ppb above background"},
            ]

        data_sources = []
        if c["fire_count"]:
            data_sources.append({
                "source": "firms_viirs", "status": "live", "label": "NASA FIRMS VIIRS",
                "detail": f"{c['fire_count']} detection(s), {c['active_days']} day(s)",
            })
        if c["ndvi"] is not None:
            data_sources.append({
                "source": "sentinel2_ndvi", "status": "live", "label": "Sentinel-2 NDVI",
                "detail": f"NDVI {c['ndvi']:.3f}",
            })
        if c["ch4_ppb"] is not None:
            data_sources.append({
                "source": "sentinel5p_ch4", "status": "live", "label": "Sentinel-5P CH4",
                "detail": f"{c['ch4_ppb']:.0f} ppb (+{c['ch4_elevation']:.0f} ppb)",
            })

        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "waste_assessment": {
                "dominant_type":  c["dominant_type"],
                "risk_level":     c["risk_level"],
                "within_city":    c["within_city"],
                "signals_active": [
                    s for s, v in [
                        ("waste_burn",    c["fire_count"] > 0),
                        ("dump_site",     c["ndvi"] is not None),
                        ("landfill_gas",  c["ch4_ppb"] is not None),
                    ] if v
                ],
            },
            "field_verification_required": c["risk_level"] in ("high", "severe"),
            "confidence": {
                "confidence_score":       c["risk_score"],
                "recommendation_allowed": c["risk_score"] >= 0.3,
            },
            "evidence":        {"inputs": evidence_inputs},
            "data_source_status": data_sources,
            "review_guidance": {
                "review_prompts": [
                    "Confirm waste site via Google Maps satellite view or field visit.",
                    "Check whether this is a registered/authorized waste processing site.",
                    "Assess distance to residential areas and surface water bodies.",
                    "Review wind direction — smoke from waste burns carries toxic PM2.5 and dioxins.",
                ],
                "when_not_to_act": [
                    "Low NDVI in agricultural zones during dry season may be fallow fields.",
                    "Low-confidence FIRMS detections near industrial areas may be process heat.",
                    "Elevated CH4 near paddy fields during monsoon may be agricultural emissions.",
                ],
            },
            "safety_gates": [
                {
                    "gate":        "site_verification",
                    "required":    True,
                    "description": "Cross-verify satellite signal with street-level imagery before escalating.",
                },
                {
                    "gate":        "authorization_check",
                    "required":    c["risk_level"] in ("high", "severe"),
                    "description": "Check municipal records for authorized waste processing facilities at this location.",
                },
            ],
            "blocked_uses": [
                "automated_penalty_issuance",
                "direct_site_closure_without_field_verification",
            ],
        })
    return packets
