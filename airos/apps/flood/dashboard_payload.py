from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _risk_level_placeholder(*, rainfall_mm_per_hour: float | None, incident_count: int, data_quality_score: float | None) -> str:
    """
    Conservative placeholder categories (non-operational).
    These are *not* validated flood predictions; they are triage labels for review.
    """
    if data_quality_score is not None and float(data_quality_score) < 0.5:
        return "unknown"
    if incident_count >= 3:
        return "high"
    if incident_count >= 1:
        return "moderate"
    if rainfall_mm_per_hour is None:
        return "unknown"
    r = float(rainfall_mm_per_hour)
    if r >= 50:
        return "high"
    if r >= 20:
        return "moderate"
    return "low"


def _queue_priority(risk_level: str) -> str:
    if risk_level == "high":
        return "high"
    if risk_level == "moderate":
        return "medium"
    return "low"


def _packet_id_stub(area_id: str, generated_at: str) -> str:
    raw = f"flood_risk|{area_id}|{generated_at}"
    return "pkt_stub_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_flood_risk_dashboard_payload(
    feature_rows: pd.DataFrame,
    *,
    generated_at: str | None = None,
    city_id: str | None = None,
    area_id: str | None = None,
) -> dict[str, Any]:
    """
    Build a flood risk dashboard consumer payload from flood feature rows.

    Output is strictly non-operational: it provides situational awareness and a conservative review queue.
    It does not create decision packets or recommendations.
    """
    gen = generated_at or _now()

    df = feature_rows.copy() if feature_rows is not None else pd.DataFrame()
    if df.empty:
        # Contract requires non-empty arrays; emit a single conservative placeholder row.
        df = pd.DataFrame(
            [
                {
                    "area_id": area_id or city_id or "__unassigned__",
                    "rainfall_mm_per_hour": None,
                    "incident_count": 0,
                    "drainage_asset_count": 0,
                    "data_quality_score": 0.0,
                    "source_count": 0,
                    "provenance_summary": {"sources": [], "synthetic_used": False},
                    "warning_flags": ["NO_FEATURE_ROWS"],
                }
            ]
        )

    # Aggregate a provenance summary across rows (contract-level).
    all_sources: set[str] = set()
    synthetic_used = False
    for ps in df.get("provenance_summary", []):
        if isinstance(ps, dict):
            for s in ps.get("sources") or []:
                if s:
                    all_sources.add(str(s))
            synthetic_used = synthetic_used or bool(ps.get("synthetic_used"))

    warning_flags: set[str] = set()
    if "warning_flags" in df.columns:
        for wf in df["warning_flags"].tolist():
            if isinstance(wf, list):
                warning_flags.update(str(x) for x in wf if x)

    if synthetic_used:
        warning_flags.add("SYNTHETIC_INPUT_PRESENT")

    # Build risk_areas (contract-required)
    risk_areas: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        rid = str(row.get("area_id") or area_id or city_id or "__unassigned__")
        rainfall = row.get("rainfall_mm_per_hour")
        incidents = int(row.get("incident_count") or 0)
        dqs = row.get("data_quality_score")
        risk_level = _risk_level_placeholder(rainfall_mm_per_hour=rainfall if isinstance(rainfall, (int, float)) else None, incident_count=incidents, data_quality_score=float(dqs) if dqs is not None else None)
        confidence_score = None
        try:
            confidence_score = float(dqs) if dqs is not None else None
        except Exception:
            confidence_score = None

        uncertainty_notes: list[str] = []
        if "LOW_LYING_PROXY_UNAVAILABLE" in warning_flags:
            uncertainty_notes.append("Low-lying/elevation proxy unavailable; risk labels are conservative placeholders.")
        if synthetic_used:
            uncertainty_notes.append("Synthetic inputs present; treat as review-only.")
        if risk_level == "unknown":
            uncertainty_notes.append("Insufficient confidence for risk categorization.")

        risk_areas.append(
            {
                "area_id": rid,
                "risk_level": risk_level,
                "confidence_score": confidence_score,
                "uncertainty": {"notes": " ".join(uncertainty_notes).strip()} if uncertainty_notes else {"notes": ""},
                "geometry_geojson": None,
            }
        )

    # Overall summary
    overall = "low"
    levels = [a.get("risk_level") for a in risk_areas]
    if "high" in levels:
        overall = "high"
    elif "moderate" in levels:
        overall = "moderate"
    elif "unknown" in levels:
        overall = "unknown"

    # Warnings (contract-required array; can be empty, but we add safety reminders)
    active_warnings: list[dict[str, str]] = [
        {
            "warning_id": "decision_support_only",
            "severity": "high",
            "message": "Flood outputs are decision support only. Field verification required before operational action unless separately authorized by emergency protocol.",
        }
    ]
    if "LOW_LYING_PROXY_UNAVAILABLE" in warning_flags:
        active_warnings.append(
            {
                "warning_id": "low_lying_proxy_unavailable",
                "severity": "medium",
                "message": "Low-lying/elevation risk proxy is unavailable; treat risk labels as conservative placeholders.",
            }
        )
    if synthetic_used:
        active_warnings.append(
            {
                "warning_id": "synthetic_inputs_present",
                "severity": "high",
                "message": "Synthetic or low-confidence inputs detected; restrict to review and verification tasks.",
            }
        )

    # Review queue: candidates only (no action orders), must be non-empty per contract.
    recommended_review_queue: list[dict[str, str]] = []
    for a in risk_areas:
        rid = str(a.get("area_id") or "")
        rl = str(a.get("risk_level") or "unknown")
        pr = _queue_priority(rl)
        reason = f"Review candidate (non-operational): risk_level={rl}."
        if rl in {"high", "moderate"}:
            reason = f"Review candidate (non-operational): elevated placeholder risk ({rl}); verify incidents and drainage constraints."
        recommended_review_queue.append({"packet_id": _packet_id_stub(rid, gen), "priority": pr, "reason": reason})

    # Map layers (contract-required, at least 1)
    map_layers = [
        {
            "layer_id": "flood_risk_areas",
            "layer_type": "polygon",
            "title": "Flood risk areas (placeholder categories)",
            "source_packet_ids": [q["packet_id"] for q in recommended_review_queue[:10]],
        }
    ]

    # Data quality summary (contract-required)
    confidence_note = f"Sources={len(all_sources)}; synthetic_used={bool(synthetic_used)}; flags={sorted(warning_flags)}"
    payload: dict[str, Any] = {
        "generated_at": gen,
        "risk_summary": {"overall_risk_level": overall, "time_window": "now_to_next_3_hours", "headline": f"Overall flood risk (placeholder): {overall}"},
        "map_layers": map_layers,
        "risk_areas": risk_areas,
        "active_warnings": active_warnings,
        "data_quality_summary": {"synthetic_data_used": bool(synthetic_used), "confidence_note": confidence_note},
        "recommended_review_queue": recommended_review_queue,
        "provenance_summary": {"sources": sorted(all_sources), "synthetic_used": bool(synthetic_used)},
    }

    # Contract requires city_id OR area_id at top level.
    if area_id:
        payload["area_id"] = area_id
    elif city_id:
        payload["city_id"] = city_id
    else:
        # fall back to the first area_id from computed rows
        payload["area_id"] = str(risk_areas[0]["area_id"])

    return payload

