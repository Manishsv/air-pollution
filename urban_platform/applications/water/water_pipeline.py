"""Water Quality monitoring pipeline.

Aggregates Sentinel-2 water quality signals into per-H3-cell risk assessments.

Water Quality Index (WQI) — composite of three sub-indices:
  Turbidity  (NDTI)  suspended sediment, sewage discharge
  Algal      (CI)    chlorophyll-a proxy, algal bloom intensity
  Foam/Scum  (FAI)   floating algae, industrial foam, sewage froth
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

_LEVEL_ORDER = ["good", "moderate", "poor", "severe"]

_WQI_COLORS = {
    "good":     [30,  144, 255, 160],   # clear blue
    "moderate": [255, 200,  50, 180],   # yellow
    "poor":     [220,  80,  20, 200],   # orange
    "severe":   [120,   0,  80, 220],   # dark purple (algal bloom / sewage)
}

# Known significant urban water bodies per city (for reference layer)
_KNOWN_WATER_BODIES: dict[str, list[dict]] = {
    "bangalore": [
        {"name": "Bellandur Lake",  "lat": 12.9352, "lon": 77.6648, "risk": "high"},
        {"name": "Varthur Lake",    "lat": 12.9469, "lon": 77.7340, "risk": "high"},
        {"name": "Ulsoor Lake",     "lat": 12.9826, "lon": 77.6211, "risk": "moderate"},
        {"name": "Hebbal Lake",     "lat": 13.0450, "lon": 77.5940, "risk": "moderate"},
        {"name": "Madiwala Lake",   "lat": 12.9175, "lon": 77.6160, "risk": "moderate"},
    ],
    "hyderabad": [
        {"name": "Hussain Sagar",   "lat": 17.4239, "lon": 78.4738, "risk": "moderate"},
        {"name": "Osman Sagar",     "lat": 17.3700, "lon": 78.3300, "risk": "low"},
        {"name": "Himayat Sagar",   "lat": 17.3300, "lon": 78.3800, "risk": "low"},
    ],
    "chennai": [
        {"name": "Chembarambakkam", "lat": 13.0600, "lon": 80.0600, "risk": "moderate"},
        {"name": "Puzhal Lake",     "lat": 13.1600, "lon": 80.1800, "risk": "low"},
        {"name": "Pallikaranai Marsh","lat": 12.9300, "lon": 80.2200, "risk": "moderate"},
    ],
    "mumbai": [
        {"name": "Powai Lake",      "lat": 19.1270, "lon": 72.9060, "risk": "moderate"},
        {"name": "Vihar Lake",      "lat": 19.1500, "lon": 72.9200, "risk": "low"},
        {"name": "Tulsi Lake",      "lat": 19.1600, "lon": 72.9100, "risk": "low"},
    ],
    "delhi": [
        {"name": "Yamuna River",    "lat": 28.6200, "lon": 77.2500, "risk": "high"},
        {"name": "Najafgarh Lake",  "lat": 28.6100, "lon": 76.9700, "risk": "moderate"},
    ],
    "pune": [
        {"name": "Mula-Mutha River","lat": 18.5200, "lon": 73.8600, "risk": "moderate"},
        {"name": "Khadakwasla Dam", "lat": 18.4300, "lon": 73.7500, "risk": "low"},
    ],
}


def _wqi_to_level(wqi: float) -> str:
    if wqi >= 0.75:  return "severe"
    if wqi >= 0.50:  return "poor"
    if wqi >= 0.25:  return "moderate"
    return "good"


def build_water_dashboard(
    water_cells: dict[str, dict],  # from gee_water.fetch_water_quality
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cells: list[dict] = []

    for h3_id, wq in water_cells.items():
        wqi   = wq.get("water_quality_index", 0.0)
        level = _wqi_to_level(wqi)
        cells.append({
            "h3_id":               h3_id,
            "water_quality_index": wqi,
            "quality_level":       level,
            "color":               _WQI_COLORS[level],
            "mndwi":               wq.get("mndwi", 0),
            "ndti":                wq.get("ndti", 0),
            "ci":                  wq.get("ci", 1),
            "fai":                 wq.get("fai", 0),
            "turbidity_score":     wq.get("turbidity_score", 0),
            "algal_score":         wq.get("algal_score", 0),
            "foam_score":          wq.get("foam_score", 0),
        })

    cells.sort(key=lambda c: c["water_quality_index"], reverse=True)

    n_severe   = sum(1 for c in cells if c["quality_level"] == "severe")
    n_poor     = sum(1 for c in cells if c["quality_level"] == "poor")
    n_moderate = sum(1 for c in cells if c["quality_level"] == "moderate")
    overall    = cells[0]["quality_level"] if cells else "good"

    return {
        "dashboard_id":    str(uuid.uuid4()),
        "generated_at":    now,
        "city_id":         city_id,
        "h3_resolution":   h3_resolution,
        "risk_cells":      cells,
        "known_water_bodies": _KNOWN_WATER_BODIES.get(city_id, []),
        "risk_summary": {
            "overall_quality_level": overall,
            "water_cells_total":     len(cells),
            "severe_cells":          n_severe,
            "poor_cells":            n_poor,
            "moderate_cells":        n_moderate,
            "max_wqi":               round(cells[0]["water_quality_index"], 4) if cells else 0.0,
            "avg_wqi":               round(
                sum(c["water_quality_index"] for c in cells) / len(cells), 4
            ) if cells else 0.0,
        },
        "active_warnings": _build_warnings(overall, n_severe, n_poor, city_id),
        "data_quality_flag": "live" if cells else "no_data",
    }


def _build_warnings(overall: str, n_severe: int, n_poor: int, city_id: str) -> list[dict]:
    warnings = []
    if n_severe > 0:
        warnings.append({
            "warning_id": "SEVERE_WATER_POLLUTION",
            "severity":   "error",
            "message":    f"{n_severe} H3 cell(s) show severe water pollution — algal bloom or sewage discharge likely.",
        })
    if n_poor > 0:
        warnings.append({
            "warning_id": "POOR_WATER_QUALITY",
            "severity":   "warning",
            "message":    f"{n_poor} cell(s) show poor water quality — elevated turbidity or algal indicators.",
        })
    # City-specific known hotspots
    if city_id == "bangalore" and overall in ("poor", "severe"):
        warnings.append({
            "warning_id": "BANGALORE_LAKE_ALERT",
            "severity":   "warning",
            "message":    "Bellandur/Varthur lake system historically active — verify foam/fire events.",
        })
    return warnings


def build_water_decision_packets(
    water_cells: dict[str, dict],
    h3_resolution: int,
    city_id: str,
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    top_n: int = 10,
) -> list[dict]:
    dashboard = build_water_dashboard(
        water_cells, h3_resolution, city_id, lat_min, lon_min, lat_max, lon_max
    )
    active = [c for c in dashboard["risk_cells"] if c["quality_level"] != "good"][:top_n]

    packets = []
    for c in active:
        dominant = (
            "foam_scum"  if c["foam_score"]     > 0.5 else
            "algal_bloom" if c["algal_score"]   > 0.5 else
            "turbidity"
        )
        packets.append({
            "packet_id": str(uuid.uuid4()),
            "h3_id":     c["h3_id"],
            "city_id":   city_id,
            "water_assessment": {
                "quality_level":       c["quality_level"],
                "water_quality_index": c["water_quality_index"],
                "dominant_issue":      dominant,
                "turbidity_score":     c["turbidity_score"],
                "algal_score":         c["algal_score"],
                "foam_score":          c["foam_score"],
            },
            "field_verification_required": c["quality_level"] in ("poor", "severe"),
            "confidence": {
                "confidence_score":       c["water_quality_index"],
                "recommendation_allowed": c["water_quality_index"] >= 0.3,
            },
            "evidence": {
                "inputs": [
                    {"name": "water_quality_index", "value": c["water_quality_index"], "unit": "0-1"},
                    {"name": "mndwi",               "value": c["mndwi"],               "unit": "index"},
                    {"name": "ndti_turbidity",      "value": c["ndti"],                "unit": "index"},
                    {"name": "ci_chlorophyll",      "value": c["ci"],                  "unit": "ratio"},
                    {"name": "fai_floating_algae",  "value": c["fai"],                 "unit": "index"},
                ],
            },
            "data_source_status": [{
                "source": "sentinel2_wq", "status": "live",
                "label": "Sentinel-2 SR — Water Quality",
                "detail": f"WQI {c['water_quality_index']:.3f}, dominant: {dominant}",
            }],
            "review_guidance": {
                "review_prompts": [
                    "Confirm water body identity — cross-reference with lake/river registry.",
                    "Check for upstream discharge sources (sewage treatment plants, industrial outlets).",
                    "Assess proximity to drinking water intakes or recreational zones.",
                    "Review rainfall in prior 48h — high runoff can spike turbidity without sewage cause.",
                ],
                "when_not_to_act": [
                    "Post-rainfall turbidity spikes (NDTI elevated, CI normal) are typically transient.",
                    "Seasonal algal growth in summer is expected — compare against historical baseline.",
                    "Cloud shadow artefacts can produce false MNDWI positives — verify on clear-sky date.",
                ],
            },
            "safety_gates": [
                {"gate": "water_body_verification",  "required": True,
                 "description": "Confirm this H3 cell contains a mapped water body before escalating."},
                {"gate": "discharge_source_check",   "required": c["quality_level"] == "severe",
                 "description": "Identify upstream discharge point before issuing pollution notice."},
            ],
            "blocked_uses": [
                "automated_discharge_notice",
                "direct_recreational_closure_without_lab_confirmation",
            ],
        })
    return packets
