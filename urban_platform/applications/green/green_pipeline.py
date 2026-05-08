"""Urban Green Cover Change monitoring pipeline.

Aggregates Sentinel-2 NDVI/EVI change detection into per-H3-cell
green cover assessments.

Green Cover Change Index (GCCI):
  −1.0 to −0.6   severe_loss     large-scale clearing / demolition
  −0.6 to −0.2   high_loss       significant canopy removal
  −0.2 to −0.05  moderate_loss   moderate tree loss / thinning
  −0.05 to 0.05  stable          no meaningful change
   0.05 to 0.2   moderate_gain   new plantation / seasonal growth
   0.2 to 1.0    significant_gain dense regrowth / major greening
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

_CHANGE_COLORS = {
    "severe_loss":       [180,  20,  20, 230],
    "high_loss":         [230,  80,  20, 210],
    "moderate_loss":     [255, 160,  40, 180],
    "stable":            [100, 200,  80, 100],
    "moderate_gain":     [ 40, 160,  80, 170],
    "significant_gain":  [  0, 100,  40, 210],
}

_COVERAGE_COLORS = {
    "dense":    [  0, 120,  40, 180],
    "moderate": [ 80, 180,  80, 160],
    "sparse":   [180, 220, 100, 140],
    "bare":     [200, 180, 140,  80],
}

# Known urban green spaces per city (reference layer)
_KNOWN_GREEN_SPACES: dict[str, list[dict]] = {
    "bangalore": [
        {"name": "Cubbon Park",           "lat": 12.9763, "lon": 77.5929, "type": "park"},
        {"name": "Lalbagh Botanical",     "lat": 12.9507, "lon": 77.5848, "type": "park"},
        {"name": "Bannerghatta NP",       "lat": 12.8000, "lon": 77.5760, "type": "forest"},
        {"name": "Hesaraghatta Lake",     "lat": 13.1290, "lon": 77.4790, "type": "wetland"},
        {"name": "Ulsoor Lake Forest",    "lat": 12.9826, "lon": 77.6211, "type": "urban_green"},
    ],
    "hyderabad": [
        {"name": "KBR National Park",     "lat": 17.4156, "lon": 78.4347, "type": "forest"},
        {"name": "Mrugavani NP",          "lat": 17.3300, "lon": 78.3600, "type": "forest"},
        {"name": "Mahavir Harina Vanasthali","lat": 17.3700, "lon": 78.5000, "type": "forest"},
    ],
    "chennai": [
        {"name": "Guindy National Park",  "lat": 13.0069, "lon": 80.2206, "type": "forest"},
        {"name": "Adyar Estuary",         "lat": 13.0000, "lon": 80.2500, "type": "wetland"},
        {"name": "Pallikaranai Marsh",    "lat": 12.9300, "lon": 80.2200, "type": "wetland"},
    ],
    "mumbai": [
        {"name": "Sanjay Gandhi NP",      "lat": 19.2147, "lon": 72.9106, "type": "forest"},
        {"name": "Aarey Colony Forest",   "lat": 19.1630, "lon": 72.8730, "type": "forest"},
        {"name": "Mangrove Belt (Thane)", "lat": 19.1800, "lon": 73.0200, "type": "wetland"},
    ],
    "delhi": [
        {"name": "Lodhi Garden",          "lat": 28.5935, "lon": 77.2195, "type": "park"},
        {"name": "Yamuna Biodiversity Pk","lat": 28.7300, "lon": 77.2400, "type": "wetland"},
        {"name": "Delhi Ridge Forest",    "lat": 28.6800, "lon": 77.1400, "type": "forest"},
        {"name": "Asola Bhatti WLS",      "lat": 28.4900, "lon": 77.1700, "type": "forest"},
    ],
    "pune": [
        {"name": "Sinhagad Forest",       "lat": 18.3660, "lon": 73.7550, "type": "forest"},
        {"name": "Pashan Lake",           "lat": 18.5370, "lon": 73.7980, "type": "wetland"},
        {"name": "Katraj Snake Park",     "lat": 18.4500, "lon": 73.8600, "type": "park"},
    ],
}

_TYPE_ICON = {
    "park":        "🌳",
    "forest":      "🌲",
    "wetland":     "🌿",
    "urban_green": "🪴",
}


def _gcci_to_change_level(gcci: float) -> str:
    if gcci <= -0.6:  return "severe_loss"
    if gcci <= -0.2:  return "high_loss"
    if gcci <= -0.05: return "moderate_loss"
    if gcci >= 0.2:   return "significant_gain"
    if gcci >= 0.05:  return "moderate_gain"
    return "stable"


def build_green_dashboard(
    green_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    now   = datetime.now(timezone.utc).isoformat()
    cells: list[dict] = []

    for h3_id, g in green_cells.items():
        gcci       = g.get("green_cover_change_index", 0.0)
        change_lvl = _gcci_to_change_level(gcci)
        coverage   = g.get("coverage_class", "sparse")
        cells.append({
            "h3_id":                    h3_id,
            "green_cover_change_index": gcci,
            "change_level":             change_lvl,
            "coverage_class":           coverage,
            "color":                    _CHANGE_COLORS[change_lvl],
            "coverage_color":           _COVERAGE_COLORS.get(coverage, [100, 200, 80, 120]),
            "ndvi":                     g.get("ndvi", 0.0),
            "evi":                      g.get("evi", 0.0),
            "ndvi_baseline":            g.get("ndvi_baseline", 0.0),
            "ndvi_change":              g.get("ndvi_change", 0.0),
            "change_category":          g.get("change_category", "stable"),
        })

    # Sort: losses first (most negative GCCI), then gains
    cells.sort(key=lambda c: c["green_cover_change_index"])

    loss_cells = [c for c in cells if c["green_cover_change_index"] < -0.05]
    gain_cells = [c for c in cells if c["green_cover_change_index"] > 0.05]

    n_severe   = sum(1 for c in cells if c["change_level"] == "severe_loss")
    n_high     = sum(1 for c in cells if c["change_level"] == "high_loss")
    n_moderate = sum(1 for c in cells if c["change_level"] == "moderate_loss")
    n_gain     = sum(1 for c in cells if "gain" in c["change_level"])

    # Overall health: driven by worst loss
    overall = "stable"
    if n_severe > 0:       overall = "severe_loss"
    elif n_high > 0:       overall = "high_loss"
    elif n_moderate > 0:   overall = "moderate_loss"
    elif n_gain > 0:       overall = "gaining"

    return {
        "dashboard_id":       str(uuid.uuid4()),
        "generated_at":       now,
        "city_id":            city_id,
        "h3_resolution":      h3_resolution,
        "all_cells":          cells,
        "loss_cells":         loss_cells,
        "gain_cells":         gain_cells,
        "known_green_spaces": _KNOWN_GREEN_SPACES.get(city_id, []),
        "risk_summary": {
            "overall_status":   overall,
            "total_cells":      len(cells),
            "severe_loss":      n_severe,
            "high_loss":        n_high,
            "moderate_loss":    n_moderate,
            "stable":           sum(1 for c in cells if c["change_level"] == "stable"),
            "gain":             n_gain,
            "max_loss_gcci":    round(cells[0]["green_cover_change_index"], 4) if cells else 0.0,
            "avg_ndvi":         round(
                sum(c["ndvi"] for c in cells) / len(cells), 4
            ) if cells else 0.0,
        },
        "active_warnings": _build_warnings(overall, n_severe, n_high, city_id),
        "data_quality_flag": "live" if cells else "no_data",
    }


def _build_warnings(overall: str, n_severe: int, n_high: int, city_id: str) -> list[dict]:
    warnings = []
    if n_severe > 0:
        warnings.append({
            "warning_id": "SEVERE_GREEN_LOSS",
            "severity":   "error",
            "message":    f"{n_severe} H3 cell(s) show severe green cover loss — large-scale clearing detected.",
        })
    if n_high > 0:
        warnings.append({
            "warning_id": "HIGH_GREEN_LOSS",
            "severity":   "warning",
            "message":    f"{n_high} cell(s) show high canopy loss — verify construction activity or felling.",
        })
    if city_id == "mumbai" and overall in ("high_loss", "severe_loss"):
        warnings.append({
            "warning_id": "MUMBAI_AAREY_ALERT",
            "severity":   "warning",
            "message":    "Significant loss near Mumbai — cross-check with Aarey/Sanjay Gandhi NP buffer zones.",
        })
    if city_id == "bangalore" and overall in ("high_loss", "severe_loss"):
        warnings.append({
            "warning_id": "BANGALORE_TREE_FELLING",
            "severity":   "warning",
            "message":    "Canopy loss in Bangalore — check BBMP tree felling register and ORR widening zones.",
        })
    return warnings


def build_green_decision_packets(
    green_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    dashboard = build_green_dashboard(
        green_cells, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    # Only flag loss cells (not stable or gain — gain is positive)
    loss_cells = dashboard["loss_cells"][:top_n]

    packets = []
    for c in loss_cells:
        gcci      = c["green_cover_change_index"]
        level     = c["change_level"]
        coverage  = c["coverage_class"]
        ndvi_chg  = c["ndvi_change"]

        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "green_assessment": {
                "change_level":             level,
                "green_cover_change_index": gcci,
                "change_category":          c["change_category"],
                "coverage_class":           coverage,
                "ndvi_change":              ndvi_chg,
            },
            "field_verification_required": level in ("high_loss", "severe_loss"),
            "confidence": {
                "confidence_score":       abs(gcci),
                "recommendation_allowed": abs(gcci) >= 0.2,
            },
            "evidence": {
                "inputs": [
                    {"name": "green_cover_change_index", "value": gcci,           "unit": "−1 to 1"},
                    {"name": "ndvi_current",             "value": c["ndvi"],      "unit": "index"},
                    {"name": "ndvi_baseline",            "value": c["ndvi_baseline"], "unit": "index"},
                    {"name": "ndvi_change",              "value": ndvi_chg,       "unit": "delta"},
                    {"name": "evi_current",              "value": c["evi"],        "unit": "index"},
                ],
            },
            "data_source_status": [{
                "source": "sentinel2_ndvi",  "status": "live",
                "label": "Sentinel-2 SR — NDVI/EVI change",
                "detail": f"ΔNDVI {ndvi_chg:+.3f} vs. 12-month baseline, coverage: {coverage}",
            }],
            "review_guidance": {
                "review_prompts": [
                    "Cross-check against approved tree-felling / land conversion permits.",
                    "Verify change date against construction activity records in this H3 cell.",
                    "Check whether the area falls inside a green buffer zone or biodiversity-sensitive corridor.",
                    "Review satellite imagery for visual confirmation (cloud artifacts can cause false NDVI drops).",
                ],
                "when_not_to_act": [
                    "Seasonal deciduous leaf-fall in Oct–Dec produces NDVI drops that are not permanent loss.",
                    "Agricultural harvest cycles produce sharp NDVI drops on peri-urban farmland — check land use.",
                    "Cloud or haze contamination in the recent composite can depress NDVI — verify on clear-sky date.",
                ],
            },
            "safety_gates": [
                {"gate": "permit_cross_check",   "required": True,
                 "description": "Confirm no valid felling/construction permit covers this H3 cell before escalating."},
                {"gate": "imagery_verification",  "required": level == "severe_loss",
                 "description": "Review raw Sentinel-2 imagery visually before issuing enforcement notice."},
            ],
            "blocked_uses": [
                "automated_felling_violation_notice",
                "penalty_issuance_without_visual_confirmation",
            ],
        })
    return packets
