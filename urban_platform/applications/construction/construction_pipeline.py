"""Construction Activity & Dust monitoring pipeline.

Aggregates Sentinel-2 BSI + Sentinel-5P NO2 signals into per-H3-cell
Construction Risk Assessments.

Construction Risk Index (CRI):
  0.00 – 0.20  minimal    bare ground within normal range
  0.20 – 0.40  low        light earthworks / cleared plot
  0.40 – 0.60  moderate   active construction — dust management required
  0.60 – 0.80  high       heavy construction — machinery + soil movement
  0.80 – 1.00  severe     mass earthworks / demolition — immediate dust control
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

_LEVEL_ORDER = ["minimal", "low", "moderate", "high", "severe"]

_CRI_COLORS = {
    "minimal":  [180, 180, 180,  60],
    "low":      [255, 230, 140, 150],
    "moderate": [230, 160,  40, 180],
    "high":     [200,  80,  10, 200],
    "severe":   [140,  20,  20, 220],
}

# Known active construction corridors per city (reference layer)
_KNOWN_CONSTRUCTION_ZONES: dict[str, list[dict]] = {
    "bangalore": [
        {"name": "ORR Phase 3 (Hebbal–Hosur)",  "lat": 12.9630, "lon": 77.6230, "activity": "metro_road"},
        {"name": "BMRCL Purple Line Ext.",        "lat": 12.9780, "lon": 77.5460, "activity": "metro"},
        {"name": "Whitefield IT Corridor",        "lat": 12.9698, "lon": 77.7499, "activity": "commercial"},
        {"name": "Devanahalli Aerospace SEZ",     "lat": 13.2070, "lon": 77.6280, "activity": "industrial"},
    ],
    "hyderabad": [
        {"name": "Outer Ring Road Phase II",      "lat": 17.4500, "lon": 78.3800, "activity": "road"},
        {"name": "HMRL Metro Phase II",           "lat": 17.4060, "lon": 78.4760, "activity": "metro"},
        {"name": "Shamshabad Pharma Cluster",     "lat": 17.2200, "lon": 78.4000, "activity": "industrial"},
    ],
    "chennai": [
        {"name": "Chennai Metro Phase II",        "lat": 13.0680, "lon": 80.2175, "activity": "metro"},
        {"name": "OMR IT Corridor Expansion",     "lat": 12.9150, "lon": 80.2270, "activity": "commercial"},
        {"name": "Porur–Poonamallee Road",        "lat": 13.0370, "lon": 80.1600, "activity": "road"},
    ],
    "mumbai": [
        {"name": "Mumbai Trans Harbour Link",     "lat": 18.9800, "lon": 72.9400, "activity": "road"},
        {"name": "Navi Mumbai Airport",           "lat": 18.9940, "lon": 73.0540, "activity": "airport"},
        {"name": "Bandra–Versova Sea Link",       "lat": 19.0760, "lon": 72.8180, "activity": "road"},
        {"name": "BKC BRT Corridor",              "lat": 19.0600, "lon": 72.8650, "activity": "road"},
    ],
    "delhi": [
        {"name": "DMRC Phase IV (Janakpuri–RK)",  "lat": 28.6220, "lon": 77.0840, "activity": "metro"},
        {"name": "Dwarka Expressway Extension",   "lat": 28.5800, "lon": 77.0200, "activity": "road"},
        {"name": "Aerocity Phase II",             "lat": 28.5562, "lon": 77.0889, "activity": "commercial"},
    ],
    "pune": [
        {"name": "Pune Metro Phase I",            "lat": 18.5390, "lon": 73.8620, "activity": "metro"},
        {"name": "Wakad–Hinjewadi IT Expansion",  "lat": 18.5920, "lon": 73.7200, "activity": "commercial"},
        {"name": "Ring Road Phase I",             "lat": 18.5000, "lon": 73.9500, "activity": "road"},
    ],
}

_ACTIVITY_LABELS = {
    "metro":      "Metro / Rail",
    "road":       "Road / Highway",
    "metro_road": "Metro + Road",
    "commercial": "Commercial Build",
    "industrial": "Industrial Zone",
    "airport":    "Airport / Runway",
}


def _cri_to_level(cri: float) -> str:
    if cri >= 0.80: return "severe"
    if cri >= 0.60: return "high"
    if cri >= 0.40: return "moderate"
    if cri >= 0.20: return "low"
    return "minimal"


def build_construction_dashboard(
    construction_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    now   = datetime.now(timezone.utc).isoformat()
    cells: list[dict] = []

    for h3_id, sig in construction_cells.items():
        cri   = sig.get("construction_risk_index", 0.0)
        level = _cri_to_level(cri)
        cells.append({
            "h3_id":                   h3_id,
            "construction_risk_index": cri,
            "risk_level":              level,
            "color":                   _CRI_COLORS[level],
            "bsi":                     sig.get("bsi", 0.0),
            "ndvi":                    sig.get("ndvi", 0.0),
            "no2_mol_m2":              sig.get("no2_mol_m2", 0.0),
            "bsi_score":               sig.get("bsi_score", 0.0),
            "no2_score":               sig.get("no2_score", 0.0),
            "ndvi_factor":             sig.get("ndvi_factor", 1.0),
        })

    cells.sort(key=lambda c: c["construction_risk_index"], reverse=True)

    n_severe   = sum(1 for c in cells if c["risk_level"] == "severe")
    n_high     = sum(1 for c in cells if c["risk_level"] == "high")
    n_moderate = sum(1 for c in cells if c["risk_level"] == "moderate")
    overall    = cells[0]["risk_level"] if cells else "minimal"

    return {
        "dashboard_id":            str(uuid.uuid4()),
        "generated_at":            now,
        "city_id":                 city_id,
        "h3_resolution":           h3_resolution,
        "risk_cells":              cells,
        "known_construction_zones": _KNOWN_CONSTRUCTION_ZONES.get(city_id, []),
        "risk_summary": {
            "overall_risk_level":    overall,
            "active_cells_total":    len(cells),
            "severe_cells":          n_severe,
            "high_cells":            n_high,
            "moderate_cells":        n_moderate,
            "max_cri":               round(cells[0]["construction_risk_index"], 4) if cells else 0.0,
            "avg_cri":               round(
                sum(c["construction_risk_index"] for c in cells) / len(cells), 4
            ) if cells else 0.0,
        },
        "active_warnings": _build_warnings(overall, n_severe, n_high, city_id),
        "data_quality_flag": "live" if cells else "no_data",
    }


def _build_warnings(overall: str, n_severe: int, n_high: int, city_id: str) -> list[dict]:
    warnings = []
    if n_severe > 0:
        warnings.append({
            "warning_id": "SEVERE_CONSTRUCTION_DUST",
            "severity":   "error",
            "message":    f"{n_severe} H3 cell(s) show severe construction activity — dust suppression likely inadequate.",
        })
    if n_high > 0:
        warnings.append({
            "warning_id": "HIGH_CONSTRUCTION_ACTIVITY",
            "severity":   "warning",
            "message":    f"{n_high} cell(s) show high construction activity — verify dust management compliance.",
        })
    if city_id == "delhi" and overall in ("high", "severe"):
        warnings.append({
            "warning_id": "DELHI_GRAP_TRIGGER",
            "severity":   "warning",
            "message":    "Heavy construction detected in Delhi — check GRAP stage for construction site restrictions.",
        })
    return warnings


def build_construction_decision_packets(
    construction_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    dashboard = build_construction_dashboard(
        construction_cells, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max,
    )
    active = [c for c in dashboard["risk_cells"] if c["risk_level"] not in ("minimal", "low")][:top_n]

    packets = []
    for c in active:
        dominant = (
            "heavy_earthworks" if c["bsi_score"] > 0.6 else
            "machinery_exhaust" if c["no2_score"] > 0.5 else
            "soil_disturbance"
        )
        cri   = c["construction_risk_index"]
        level = c["risk_level"]

        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "construction_assessment": {
                "risk_level":              level,
                "construction_risk_index": cri,
                "dominant_activity":       dominant,
                "bsi_score":               c["bsi_score"],
                "no2_score":               c["no2_score"],
            },
            "field_verification_required": level in ("high", "severe"),
            "confidence": {
                "confidence_score":       cri,
                "recommendation_allowed": cri >= 0.4,
            },
            "evidence": {
                "inputs": [
                    {"name": "construction_risk_index", "value": cri,               "unit": "0-1"},
                    {"name": "bsi",                     "value": c["bsi"],          "unit": "index"},
                    {"name": "ndvi",                    "value": c["ndvi"],         "unit": "index"},
                    {"name": "no2_mol_m2",              "value": c["no2_mol_m2"],   "unit": "mol/m²"},
                    {"name": "bsi_score",               "value": c["bsi_score"],    "unit": "0-1"},
                    {"name": "no2_score",               "value": c["no2_score"],    "unit": "0-1"},
                ],
            },
            "data_source_status": [
                {"source": "sentinel2_bsi",   "status": "live",
                 "label": "Sentinel-2 SR — BSI/NDVI",
                 "detail": f"BSI {c['bsi']:.3f}, NDVI {c['ndvi']:.3f}"},
                {"source": "sentinel5p_no2",  "status": "live",
                 "label": "Sentinel-5P TROPOMI — NO2",
                 "detail": f"NO2 {c['no2_mol_m2']:.2e} mol/m²"},
            ],
            "review_guidance": {
                "review_prompts": [
                    "Cross-reference with approved construction permit registry for this H3 cell.",
                    "Check dust suppression compliance — water spraying logs, barrier installation.",
                    "Verify NO2 elevation is construction-related vs. traffic corridor overlap.",
                    "Review proximity to residential zones, schools, or hospitals.",
                ],
                "when_not_to_act": [
                    "Post-harvest bare fields can show high BSI without construction — check land use.",
                    "Sandy or laterite soils have naturally higher BSI — compare against pre-construction baseline.",
                    "NO2 elevated near major roads may reflect traffic, not on-site machinery.",
                ],
            },
            "safety_gates": [
                {"gate": "permit_verification",   "required": True,
                 "description": "Confirm active construction permit exists for this H3 cell."},
                {"gate": "dust_suppression_check", "required": level == "severe",
                 "description": "Verify dust suppression measures in place before issuing notice."},
            ],
            "blocked_uses": [
                "automated_stop_work_order",
                "penalty_issuance_without_site_inspection",
            ],
        })
    return packets
