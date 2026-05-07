"""Generate ward-level climate decision packets from ward aggregation output.

Implements the trigger → attribution → action → escalation logic defined in
docs/architecture/WARD_DECISION_CATALOGUE.md.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from .ward_aggregator import WardAggregationResult

# ── Urgency thresholds (aligned with catalogue) ───────────────────────────────

_URGENCY = {
    "immediate":  {"aqi": 0.80, "flood": 0.85, "heat": 0.85},
    "within_4h":  {"aqi": 0.60, "flood": 0.70, "heat": 0.75},
    "within_24h": {"aqi": 0.40, "flood": 0.50, "heat": 0.60},
}

_URGENCY_ORDER = {"immediate": 0, "within_4h": 1, "within_24h": 2, "plan": 3}

_DOMAIN_LABELS = {"air": "Air Quality", "flood": "Flood", "heat": "Heat", "cross_domain": "Cross-Domain"}


# ── Source attribution ────────────────────────────────────────────────────────

def _attribute_air(row: dict, hour: int) -> tuple[str, str, str]:
    """Return (attribution_key, plain_english, confidence)."""
    if 5 <= hour <= 8:
        return (
            "waste_burning",
            "Likely open waste burning — early morning spike in residential area",
            "medium",
        )
    if row.get("avg_aqi_score", 0) >= 0.70:
        return (
            "traffic_or_industrial",
            "Sustained high AQI — probable traffic congestion or industrial source",
            "medium",
        )
    return (
        "mixed_sources",
        "Moderate sustained AQI — mixed local sources",
        "low",
    )


def _attribute_flood(row: dict) -> tuple[str, str, str]:
    cell_count = max(row.get("cell_count", 1), 1)
    multi_frac = row.get("multi_risk_cell_count", 0) / cell_count
    if multi_frac >= 0.30:
        return (
            "drain_blockage",
            "High fraction of multi-risk cells — probable drain blockage or silting",
            "high",
        )
    if row.get("avg_flood_risk", 0) >= 0.80:
        return (
            "capacity_exceeded",
            "Ward-wide high risk — drainage capacity likely exceeded",
            "high",
        )
    return (
        "localised_blockage",
        "Elevated flood risk — localised drain blockage probable",
        "medium",
    )


def _attribute_heat(row: dict) -> tuple[str, str, str]:
    if row.get("avg_heat_risk", 0) >= 0.75:
        return (
            "uhi_green_cover_deficit",
            "Structural urban heat island — green cover deficit likely cause",
            "medium",
        )
    return (
        "surface_heat_absorption",
        "Elevated heat from dense built surfaces — albedo and green cover issue",
        "medium",
    )


# ── Urgency calculation ───────────────────────────────────────────────────────

def _score_urgency(aqi: Optional[float], flood: Optional[float], heat: Optional[float]) -> str:
    for level in ("immediate", "within_4h", "within_24h"):
        t = _URGENCY[level]
        if (aqi  is not None and aqi  >= t["aqi"]):   return level
        if (flood is not None and flood >= t["flood"]): return level
        if (heat  is not None and heat  >= t["heat"]):  return level
    return "plan"


# ── Packet ID (stable hash) ───────────────────────────────────────────────────

def _packet_id(ward_id: str, domain: str, ts: str) -> str:
    raw = f"ward|{domain}|{ward_id}|{ts}"
    return "pkt_ward_" + hashlib.sha1(raw.encode()).hexdigest()[:12]


# ── Per-ward decision generation ──────────────────────────────────────────────

def _decisions_for_ward(row: dict, timestamp_bucket: str, available_domains: list[str]) -> list[dict]:
    packets: list[dict] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        hour = int(timestamp_bucket[11:13])
    except Exception:
        hour = 12

    aqi   = row.get("avg_aqi_score")
    flood = row.get("avg_flood_risk")
    heat  = row.get("avg_heat_risk")
    comp  = row.get("composite_risk")
    qol   = row.get("qol_index")

    def _base(domain: str, decision_id: str, trigger_id: str) -> dict:
        return {
            "packet_id":        _packet_id(row["ward_id"], domain, timestamp_bucket),
            "domain":           domain,
            "decision_id":      decision_id,
            "trigger_id":       trigger_id,
            "ward_id":          row["ward_id"],
            "ward_name":        row.get("ward_name", ""),
            "city_id":          row.get("city_id", ""),
            "timestamp_bucket": timestamp_bucket,
            "generated_at":     generated_at,
            "status":           "open",
        }

    # ── Air quality ───────────────────────────────────────────────────────────
    if "air" in available_domains and aqi is not None and aqi >= 0.40:
        trigger    = "AQ-T1" if aqi >= 0.60 else "AQ-T3"
        decision   = "AQ-D1" if (5 <= hour <= 8) else ("AQ-D4" if aqi < 0.60 else "AQ-D2")
        src, plain, conf = _attribute_air(row, hour)
        escalate   = aqi >= 0.80 or decision == "AQ-D4"

        actions = {
            "AQ-D1": "Dispatch sanitation supervisor — locate and stop waste burning; issue no-burning notice to ward residents.",
            "AQ-D2": "Coordinate with traffic police on vehicle idling at main ward junctions; target peak hours.",
            "AQ-D4": "File chronic AQI pattern report for zonal review; recommend waste collection schedule increase.",
        }
        p = _base("air", decision, trigger)
        p.update({
            "urgency":             _score_urgency(aqi, None, None),
            "signal":              {"avg_aqi_score": aqi, "source_attribution": src, "attribution_plain": plain, "attribution_confidence": conf},
            "recommended_action":  actions.get(decision, "Investigate and monitor AQI source."),
            "escalation_required": escalate,
            "escalate_to":         "zonal_officer" if escalate else None,
            "evidence":            {"cell_count": row.get("cell_count"), "multi_risk_cells": row.get("multi_risk_cell_count"), "qol_health": row.get("qol_health")},
        })
        packets.append(p)

    # ── Flood ─────────────────────────────────────────────────────────────────
    if "flood" in available_domains and flood is not None and flood >= 0.50:
        trigger  = "FL-T3"
        decision = "FL-D3" if flood >= 0.80 else "FL-D1"
        src, plain, conf = _attribute_flood(row)
        escalate = flood >= 0.85 or row.get("multi_risk_cell_count", 0) >= 3

        actions = {
            "FL-D1": "Dispatch drain desilting crew to high-risk cells; photograph blockages and log in asset register.",
            "FL-D3": "Deploy sandbags and pumps to identified vulnerable points; issue waterlogging advisory to ward residents.",
            "FL-D5": "Close affected roads; request pump reallocation from zonal officer immediately.",
        }
        p = _base("flood", decision, trigger)
        p.update({
            "urgency":             _score_urgency(None, flood, None),
            "signal":              {"avg_flood_risk": flood, "source_attribution": src, "attribution_plain": plain, "attribution_confidence": conf},
            "recommended_action":  actions.get(decision, "Inspect and clear drain blockages in high-risk area."),
            "escalation_required": escalate,
            "escalate_to":         "zonal_officer" if escalate else None,
            "evidence":            {"cell_count": row.get("cell_count"), "multi_risk_cells": row.get("multi_risk_cell_count"), "elevated_cells": row.get("elevated_cell_count"), "qol_safety": row.get("qol_safety")},
        })
        packets.append(p)

    # ── Heat ──────────────────────────────────────────────────────────────────
    if "heat" in available_domains and heat is not None and heat >= 0.60:
        trigger  = "HT-T2" if heat >= 0.75 else "HT-T3"
        decision = "HT-D1" if heat >= 0.75 else "HT-D4"
        src, plain, conf = _attribute_heat(row)
        escalate = heat >= 0.85

        actions = {
            "HT-D1": "Activate nearest cooling centre; issue heat advisory to outdoor workers and street vendors in ward.",
            "HT-D2": "Issue mandatory rest advisory 12–3pm at all construction sites; deploy water stations.",
            "HT-D4": "Initiate ward tree-planting request; flag ward for cool zone designation review with zonal officer.",
        }
        p = _base("heat", decision, trigger)
        p.update({
            "urgency":             _score_urgency(None, None, heat),
            "signal":              {"avg_heat_risk": heat, "source_attribution": src, "attribution_plain": plain, "attribution_confidence": conf},
            "recommended_action":  actions.get(decision, "Issue heat advisory and activate cooling centre."),
            "escalation_required": escalate,
            "escalate_to":         "commissioner_heat_action_plan" if escalate else None,
            "evidence":            {"cell_count": row.get("cell_count"), "qol_thermal": row.get("qol_thermal")},
        })
        packets.append(p)

    # ── Cross-domain: compounding stress ──────────────────────────────────────
    domain_scores = [
        (aqi,   "air"),
        (flood, "flood"),
        (heat,  "heat"),
    ]
    elevated = sum(
        1 for v, d in domain_scores
        if v is not None and v >= 0.50 and d in available_domains
    )
    if elevated >= 2 and comp is not None and comp >= 0.60:
        p = _base("cross_domain", "XD-D1", "XD-T1")
        p.update({
            "urgency": "within_4h",
            "signal": {
                "avg_aqi_score":        aqi,
                "avg_flood_risk":       flood,
                "avg_heat_risk":        heat,
                "composite_risk":       comp,
                "elevated_domain_count": elevated,
                "source_attribution":   "compounding_climate_stress",
                "attribution_plain":    f"Ward under simultaneous stress across {elevated} climate domains.",
                "attribution_confidence": "high",
            },
            "recommended_action": (
                f"Ward under compounding stress across {elevated} domains "
                "(QoL index: {:.2f}). Elevate to priority intervention list; ".format(qol or 0) +
                "brief zonal officer for multi-department coordination."
            ),
            "escalation_required": True,
            "escalate_to":         "zonal_officer",
            "evidence":            {"qol_index": qol, "domains_present": row.get("domains_present"), "cell_count": row.get("cell_count"), "multi_risk_cells": row.get("multi_risk_cell_count")},
        })
        packets.append(p)

    return packets


# ── Public API ────────────────────────────────────────────────────────────────

def generate_ward_decisions(result: WardAggregationResult) -> list[dict]:
    """Generate decision packets for all wards in a WardAggregationResult.

    Returns packets sorted by urgency (immediate first), then ward_id.
    """
    if result.wards_df.empty:
        return []

    packets: list[dict] = []
    for _, row in result.wards_df.iterrows():
        packets.extend(
            _decisions_for_ward(row.to_dict(), result.timestamp_bucket, result.available_domains)
        )

    packets.sort(key=lambda p: (_URGENCY_ORDER.get(p["urgency"], 4), p["ward_id"]))
    return packets


def decisions_to_dataframe(packets: list[dict]) -> pd.DataFrame:
    """Flatten decision packets into a display-ready DataFrame."""
    if not packets:
        return pd.DataFrame()

    rows = []
    for p in packets:
        sig = p.get("signal", {})
        rows.append({
            "urgency":              p["urgency"],
            "domain":               _DOMAIN_LABELS.get(p["domain"], p["domain"]),
            "decision_id":          p["decision_id"],
            "ward_name":            p.get("ward_name", ""),
            "aqi_score":            sig.get("avg_aqi_score"),
            "flood_risk":           sig.get("avg_flood_risk"),
            "heat_risk":            sig.get("avg_heat_risk"),
            "likely_cause":         sig.get("attribution_plain", sig.get("source_attribution", "")),
            "recommended_action":   p.get("recommended_action", ""),
            "escalation_required":  p.get("escalation_required", False),
            "escalate_to":          p.get("escalate_to") or "—",
            "status":               p.get("status", "open"),
            "packet_id":            p["packet_id"],
            "ward_id":              p.get("ward_id", ""),
        })
    return pd.DataFrame(rows)
