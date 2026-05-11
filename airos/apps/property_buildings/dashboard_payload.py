from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_truthy_num(x: Any) -> bool:
    try:
        return x is not None and float(x) == float(x)
    except Exception:
        return False


def build_property_building_dashboard_payload(
    feature_rows: pd.DataFrame,
    *,
    generated_at: str | None = None,
    city_id: str | None = None,
    area_id: str | None = None,
) -> dict[str, Any]:
    """
    Build the property/buildings dashboard consumer payload from feature scaffolding rows.

    TODO(open-data Phase 1): optionally ingest rows from
    ``build_built_environment_change_features`` (``open_data_features``) alongside or instead of
    legacy registry-shaped feature rows; this builder still uses coverage keys named for the older
    multi-feed scaffold and does not require municipal inputs for validation.

    This is intentionally verification-first and non-operational:
    - No parcel↔footprint↔permit matching.
    - No enforcement/tax action recommendations.
    - Review candidates are placeholders until matching logic exists under specs + safety gates.
    """
    gen = generated_at or _now()

    df = feature_rows.copy() if feature_rows is not None else pd.DataFrame()
    if df.empty:
        df = pd.DataFrame(
            [
                {
                    "area_id": area_id or city_id or "__unassigned__",
                    "generated_at": gen,
                    "property_registry_record_count": 0,
                    "building_footprint_record_count": 0,
                    "building_permit_record_count": 0,
                    "land_use_record_count": 0,
                    "provenance_summary": {"sources": [], "synthetic_used": False},
                    "warning_flags": ["NO_FEATURE_ROWS"],
                }
            ]
        )

    # Aggregate provenance across rows
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
            elif isinstance(wf, str) and wf:
                warning_flags.add(wf)

    # Coverage summary: sum counts across rows (scaffolding)
    def sum_int(col: str) -> int:
        if col not in df.columns:
            return 0
        return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    coverage_summary = {
        "property_registry_records": sum_int("property_registry_record_count"),
        "building_footprint_records": sum_int("building_footprint_record_count"),
        "building_permit_records": sum_int("building_permit_record_count"),
        "land_use_records": sum_int("land_use_record_count"),
    }

    # No matching implemented => we cannot claim real mismatches.
    mismatch_summary = {
        "total_candidates": 0,
        "high_priority": 0,
        "notes": "Matching not implemented; candidates are not generated in this layer.",
    }

    # Contract requires at least 1 map layer.
    map_layers = [
        {
            "layer_id": "property_buildings_review_candidates",
            "layer_type": "points",
            "title": "Property/building review candidates (not yet generated)",
        }
    ]

    # Candidates remain empty until matching exists; keep warnings explicit.
    review_candidates: list[dict[str, Any]] = []

    active_warnings: list[dict[str, str]] = [
        {
            "warning_id": "verification_candidates_only",
            "severity": "high",
            "message": "Property/building outputs are verification candidates only. Do not use for enforcement, penalties, demolition, or tax reassessment without authorized human process and field verification.",
        },
        {
            "warning_id": "matching_not_implemented",
            "severity": "medium",
            "message": "Matching between registry, footprints, permits, and land-use is not implemented in this layer; mismatch candidates are not generated.",
        },
    ]
    if synthetic_used or "SYNTHETIC_INPUT_PRESENT" in warning_flags:
        active_warnings.append(
            {
                "warning_id": "synthetic_inputs_present",
                "severity": "high",
                "message": "Synthetic or demo inputs detected; restrict to contract validation and review-only workflows.",
            }
        )

    confidence_note = f"Sources={len(all_sources)}; synthetic_used={bool(synthetic_used)}; flags={sorted(warning_flags)}"

    payload: dict[str, Any] = {
        "generated_at": gen,
        "coverage_summary": coverage_summary,
        "mismatch_summary": mismatch_summary,
        "map_layers": map_layers,
        "review_candidates": review_candidates,
        "data_quality_summary": {
            "synthetic_data_used": bool(synthetic_used),
            "confidence_note": confidence_note,
        },
        "provenance_summary": {"sources": sorted(all_sources), "synthetic_used": bool(synthetic_used)},
        "active_warnings": active_warnings,
    }

    if area_id:
        payload["area_id"] = area_id
    elif city_id:
        payload["city_id"] = city_id
    else:
        payload["area_id"] = str(df.iloc[0].get("area_id") or "__unassigned__")

    return payload

