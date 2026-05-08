"""Urban Noise Risk monitoring pipeline.

Noise cannot be measured directly by satellite. This pipeline builds a
Noise Risk Index (NRI) from three proxy signals already available:

  1. Source proximity   — haversine distance from known airports, major junctions,
                          railway yards, and industrial clusters (hardcoded reference layer)
  2. Construction CRI   — active earthworks / machinery (from Sentinel-2 BSI pipeline)
  3. Fire activity      — FIRMS FRP; high-FRP urban fires = waste burning + industrial noise

NRI (0–1) → dB proxy:
  low       NRI < 0.25   < 53 dB   WHO residential day limit
  moderate  NRI 0.25–0.5  53–60 dB  WHO transport
  high      NRI 0.5–0.75  60–70 dB  Industrial zone
  severe    NRI > 0.75   > 70 dB   Near airport / major interchange

WHO Environmental Noise Guidelines (2018):
  Road traffic   53 dB  (day)  |  45 dB  (night)
  Aircraft       45 dB  (day)  |  40 dB  (night)
  Railway        54 dB  (day)  |  44 dB  (night)
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

import pandas as pd

# ── Known noise sources per city ───────────────────────────────────────────
# weight = source strength 0–1, radius_km = influence radius

_NOISE_SOURCES: dict[str, list[dict]] = {
    "bangalore": [
        {"name": "BIAL Airport",            "lat": 13.1979, "lon": 77.7063, "type": "airport",     "weight": 1.0, "radius_km": 8},
        {"name": "Silk Board Junction",      "lat": 12.9172, "lon": 77.6220, "type": "traffic",     "weight": 0.7, "radius_km": 2},
        {"name": "KR Market / City Railway", "lat": 12.9760, "lon": 77.5760, "type": "railway",     "weight": 0.6, "radius_km": 2},
        {"name": "Peenya Industrial Area",   "lat": 13.0280, "lon": 77.5190, "type": "industrial",  "weight": 0.75,"radius_km": 3},
        {"name": "Marathahalli Bridge",      "lat": 12.9592, "lon": 77.7010, "type": "traffic",     "weight": 0.65,"radius_km": 2},
        {"name": "Electronic City Toll",     "lat": 12.8425, "lon": 77.6773, "type": "traffic",     "weight": 0.55,"radius_km": 2},
    ],
    "hyderabad": [
        {"name": "RGIA Airport",             "lat": 17.2403, "lon": 78.4294, "type": "airport",     "weight": 1.0, "radius_km": 8},
        {"name": "Secunderabad Railway",     "lat": 17.4399, "lon": 78.4983, "type": "railway",     "weight": 0.65,"radius_km": 2},
        {"name": "LB Nagar Junction",        "lat": 17.3430, "lon": 78.5520, "type": "traffic",     "weight": 0.60,"radius_km": 2},
        {"name": "Patancheru Industrial",    "lat": 17.5300, "lon": 78.2700, "type": "industrial",  "weight": 0.80,"radius_km": 4},
    ],
    "chennai": [
        {"name": "MAA Airport",              "lat": 13.0827, "lon": 80.2707, "type": "airport",     "weight": 1.0, "radius_km": 7},
        {"name": "Koyambedu Bus Terminal",   "lat": 13.0694, "lon": 80.1948, "type": "traffic",     "weight": 0.65,"radius_km": 2},
        {"name": "Chennai Central Railway",  "lat": 13.0827, "lon": 80.2755, "type": "railway",     "weight": 0.70,"radius_km": 2},
        {"name": "Manali Industrial",        "lat": 13.1700, "lon": 80.2600, "type": "industrial",  "weight": 0.85,"radius_km": 4},
    ],
    "mumbai": [
        {"name": "CSIA Airport T1/T2",       "lat": 19.0896, "lon": 72.8656, "type": "airport",     "weight": 1.0, "radius_km": 8},
        {"name": "Dharavi",                  "lat": 19.0432, "lon": 72.8548, "type": "industrial",  "weight": 0.70,"radius_km": 2},
        {"name": "Andheri Station",          "lat": 19.1197, "lon": 72.8468, "type": "railway",     "weight": 0.65,"radius_km": 2},
        {"name": "Nhava Sheva Port",         "lat": 18.9465, "lon": 72.9431, "type": "industrial",  "weight": 0.90,"radius_km": 5},
        {"name": "Eastern Freeway / Sion",   "lat": 19.0500, "lon": 72.8700, "type": "traffic",     "weight": 0.60,"radius_km": 2},
    ],
    "delhi": [
        {"name": "IGI Airport T1/T2/T3",     "lat": 28.5562, "lon": 77.0889, "type": "airport",     "weight": 1.0, "radius_km": 10},
        {"name": "ISBT Kashmere Gate",       "lat": 28.6679, "lon": 77.2285, "type": "traffic",     "weight": 0.70,"radius_km": 2},
        {"name": "New Delhi Railway Station","lat": 28.6431, "lon": 77.2194, "type": "railway",     "weight": 0.70,"radius_km": 2},
        {"name": "Okhla Industrial Estate",  "lat": 28.5370, "lon": 77.2680, "type": "industrial",  "weight": 0.80,"radius_km": 3},
        {"name": "NH-48 (Delhi–Gurugram)",   "lat": 28.5200, "lon": 77.1200, "type": "traffic",     "weight": 0.75,"radius_km": 3},
    ],
    "pune": [
        {"name": "Pune Airport",             "lat": 18.5822, "lon": 73.9197, "type": "airport",     "weight": 1.0, "radius_km": 6},
        {"name": "Swargate Bus Stand",       "lat": 18.5028, "lon": 73.8588, "type": "traffic",     "weight": 0.60,"radius_km": 2},
        {"name": "Pune Railway Station",     "lat": 18.5285, "lon": 73.8742, "type": "railway",     "weight": 0.65,"radius_km": 2},
        {"name": "Bhosari MIDC",             "lat": 18.6500, "lon": 73.8500, "type": "industrial",  "weight": 0.80,"radius_km": 3},
    ],
}

_SOURCE_TYPE_COLORS = {
    "airport":    [255,  50,  50, 220],
    "traffic":    [255, 160,  30, 200],
    "railway":    [120, 120, 255, 200],
    "industrial": [180,  60, 180, 200],
}

_NRI_COLORS = {
    "low":      [ 80, 200, 120, 100],
    "moderate": [255, 210,  60, 160],
    "high":     [230, 100,  20, 200],
    "severe":   [180,  20,  20, 230],
}

_NRI_DB_PROXY = {
    "low":      "< 53 dB",
    "moderate": "53–60 dB",
    "high":     "60–70 dB",
    "severe":   "> 70 dB",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _proximity_score(cell_lat: float, cell_lon: float, sources: list[dict]) -> tuple[float, str]:
    """Return (max_proximity_score 0-1, name of closest significant source)."""
    best_score  = 0.0
    best_source = "—"
    for src in sources:
        dist_km = _haversine_km(cell_lat, cell_lon, src["lat"], src["lon"])
        if dist_km <= src["radius_km"]:
            score = src["weight"] * max(0.0, 1.0 - dist_km / src["radius_km"])
            if score > best_score:
                best_score  = score
                best_source = src["name"]
    return round(best_score, 3), best_source


def _nri_to_level(nri: float) -> str:
    if nri >= 0.75: return "severe"
    if nri >= 0.50: return "high"
    if nri >= 0.25: return "moderate"
    return "low"


# ── Core builder ───────────────────────────────────────────────────────────

def build_noise_risk(
    h3_ids: tuple,
    city_id: str,
    construction_cells: dict,
    firms_df: pd.DataFrame,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict[str, dict]:
    """Compute NRI per H3 cell from proxy signals.

    Returns {h3_id: noise_dict}.
    """
    import h3

    sources = _NOISE_SOURCES.get(city_id, [])

    # Build FIRMS lookup: h3_id → total FRP for cells in this bbox
    fire_h3_frp: dict[str, float] = {}
    if not firms_df.empty and "latitude" in firms_df.columns:
        sig = firms_df[firms_df.get("frp", pd.Series(dtype=float)) >= 5] if "frp" in firms_df.columns else firms_df
        for _, row in sig.iterrows():
            try:
                cid = h3.latlng_to_cell(float(row["latitude"]), float(row["longitude"]), 9)
                fire_h3_frp[cid] = fire_h3_frp.get(cid, 0.0) + float(row.get("frp", 0))
            except Exception:
                pass

    result: dict[str, dict] = {}
    for h3_id in h3_ids:
        cell_lat, cell_lon = h3.cell_to_latlng(h3_id)

        prox_score, nearest_source = _proximity_score(cell_lat, cell_lon, sources)

        # Construction boost: CRI from construction pipeline
        construction_score = construction_cells.get(h3_id, {}).get(
            "construction_risk_index", 0.0
        ) * 0.6  # construction contributes up to 0.6 of its CRI to noise

        # Fire boost: log-scaled FRP presence
        frp = fire_h3_frp.get(h3_id, 0.0)
        fire_score = min(0.4, math.log1p(frp) / math.log1p(100)) if frp > 0 else 0.0

        # NRI: source proximity dominates; construction + fire add to it
        nri = min(1.0, prox_score + construction_score * 0.3 + fire_score * 0.2)
        nri = round(nri, 4)

        # Only return cells with meaningful noise risk
        if nri < 0.10 and prox_score == 0.0:
            continue

        result[h3_id] = {
            "noise_risk_index":   nri,
            "risk_level":         _nri_to_level(nri),
            "proximity_score":    prox_score,
            "construction_score": round(construction_score, 3),
            "fire_score":         round(fire_score, 3),
            "nearest_source":     nearest_source,
            "db_proxy":           _NRI_DB_PROXY[_nri_to_level(nri)],
        }

    return result


def build_noise_dashboard(
    noise_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    now   = datetime.now(timezone.utc).isoformat()
    cells: list[dict] = []

    for h3_id, n in noise_cells.items():
        level = n.get("risk_level", "low")
        cells.append({
            "h3_id":             h3_id,
            "noise_risk_index":  n["noise_risk_index"],
            "risk_level":        level,
            "color":             _NRI_COLORS[level],
            "proximity_score":   n["proximity_score"],
            "construction_score":n["construction_score"],
            "fire_score":        n["fire_score"],
            "nearest_source":    n["nearest_source"],
            "db_proxy":          n["db_proxy"],
        })

    cells.sort(key=lambda c: c["noise_risk_index"], reverse=True)

    n_severe   = sum(1 for c in cells if c["risk_level"] == "severe")
    n_high     = sum(1 for c in cells if c["risk_level"] == "high")
    n_moderate = sum(1 for c in cells if c["risk_level"] == "moderate")
    overall    = cells[0]["risk_level"] if cells else "low"

    return {
        "dashboard_id":    str(uuid.uuid4()),
        "generated_at":    now,
        "city_id":         city_id,
        "h3_resolution":   h3_resolution,
        "risk_cells":      cells,
        "noise_sources":   _NOISE_SOURCES.get(city_id, []),
        "risk_summary": {
            "overall_risk_level": overall,
            "total_cells":        len(cells),
            "severe_cells":       n_severe,
            "high_cells":         n_high,
            "moderate_cells":     n_moderate,
            "max_nri":            round(cells[0]["noise_risk_index"], 4) if cells else 0.0,
            "avg_nri":            round(sum(c["noise_risk_index"] for c in cells) / len(cells), 4) if cells else 0.0,
        },
        "active_warnings": _build_warnings(overall, n_severe, n_high, city_id),
        "data_quality_flag": "proxy" if cells else "no_data",
    }


def _build_warnings(overall: str, n_severe: int, n_high: int, city_id: str) -> list[dict]:
    warnings = []
    if n_severe > 0:
        warnings.append({
            "warning_id": "SEVERE_NOISE_RISK",
            "severity":   "error",
            "message":    f"{n_severe} H3 cell(s) exceed 70 dB proxy — near airport or major interchange.",
        })
    if n_high > 0:
        warnings.append({
            "warning_id": "HIGH_NOISE_RISK",
            "severity":   "warning",
            "message":    f"{n_high} cell(s) in 60–70 dB range — industrial or heavy construction noise.",
        })
    warnings.append({
        "warning_id": "NOISE_PROXY_CAVEAT",
        "severity":   "info",
        "message":    "NRI is a proxy index, not a measured noise level. Use as a prioritisation signal only.",
    })
    return warnings


def build_noise_decision_packets(
    noise_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    dashboard = build_noise_dashboard(
        noise_cells, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    active = [c for c in dashboard["risk_cells"] if c["risk_level"] in ("high", "severe")][:top_n]

    packets = []
    for c in active:
        nri   = c["noise_risk_index"]
        level = c["risk_level"]
        src   = c["nearest_source"]

        dominant = (
            "airport_proximity"      if c["proximity_score"] > 0.6 else
            "construction_machinery" if c["construction_score"] > 0.3 else
            "industrial_fire"        if c["fire_score"] > 0.2 else
            "traffic_corridor"
        )

        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "noise_assessment": {
                "risk_level":       level,
                "noise_risk_index": nri,
                "dominant_source":  dominant,
                "db_proxy":         c["db_proxy"],
                "nearest_source":   src,
            },
            "field_verification_required": level == "severe",
            "confidence": {
                "confidence_score":       nri,
                "recommendation_allowed": nri >= 0.5,
                "caveat":                 "NRI is proxy-based — actual noise measurement required for enforcement.",
            },
            "evidence": {
                "inputs": [
                    {"name": "noise_risk_index",   "value": nri,                    "unit": "0–1 proxy"},
                    {"name": "proximity_score",    "value": c["proximity_score"],   "unit": "0–1"},
                    {"name": "construction_score", "value": c["construction_score"],"unit": "0–1"},
                    {"name": "fire_score",         "value": c["fire_score"],        "unit": "0–1"},
                    {"name": "nearest_source",     "value": src,                    "unit": "name"},
                    {"name": "db_proxy",           "value": c["db_proxy"],          "unit": "dB estimate"},
                ],
            },
            "data_source_status": [
                {"source": "noise_proximity_model", "status": "proxy",
                 "label": "Noise proxy model",
                 "detail": f"NRI {nri:.3f}, dominant: {dominant}, nearest: {src}"},
                {"source": "sentinel2_bsi",  "status": "live",
                 "label": "Construction activity (Sentinel-2 BSI)"},
                {"source": "firms_viirs",    "status": "live",
                 "label": "Fire/industrial activity (NASA FIRMS)"},
            ],
            "review_guidance": {
                "review_prompts": [
                    "Deploy noise meter at H3 centroid for at least 15-minute LAeq measurement.",
                    "Cross-check with nearest noise-sensitive receptor — school, hospital, residential zone.",
                    "Identify primary source: airport flight path, road class, or construction permit.",
                    "Check time-of-day: day/night WHO limits differ by 8–10 dB.",
                ],
                "when_not_to_act": [
                    "NRI is a proxy — do not issue noise violation notices without actual dB measurement.",
                    "Airport proximity NRI is structural (not actionable at city level) — flag for DGCA/AAI.",
                    "Construction noise is time-of-day regulated; check if site is within permitted hours.",
                ],
            },
            "safety_gates": [
                {"gate": "acoustic_measurement",  "required": True,
                 "description": "Obtain calibrated noise meter reading before any enforcement action."},
                {"gate": "source_identification", "required": level == "severe",
                 "description": "Identify specific noise source before issuing abatement notice."},
            ],
            "blocked_uses": [
                "automated_noise_violation_notice",
                "penalty_without_calibrated_measurement",
            ],
        })
    return packets
