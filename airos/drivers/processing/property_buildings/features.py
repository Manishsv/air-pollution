from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class PropertyBuildingsFeatureBuildStats:
    rows_out: int
    source_count: int
    warning_flags: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        return "{}"


def _source_list(*dfs: pd.DataFrame | None) -> list[str]:
    sources: set[str] = set()
    for df in dfs:
        if df is None or df.empty or "source" not in df.columns:
            continue
        for s in df["source"].dropna().astype(str).tolist():
            if s:
                sources.add(s)
    return sorted(sources)


def _synthetic_used(*dfs: pd.DataFrame | None) -> bool:
    """
    Best-effort: detect synthetic signals from a `provenance` dict column if present.
    """
    for df in dfs:
        if df is None or df.empty:
            continue
        if "provenance" not in df.columns:
            continue
        for p in df["provenance"].dropna().tolist():
            if isinstance(p, dict) and (
                bool(p.get("synthetic")) or str(p.get("license", "")).lower() == "demo_only"
            ):
                return True
    return False


def _extract_area_ids(*dfs: pd.DataFrame | None) -> list[str]:
    """
    Extract area ids from any provided input tables.

    For early scaffolding, we accept either `area_id` or `ward_id` columns and return a unique list.
    """
    area_ids: set[str] = set()
    for df in dfs:
        if df is None or df.empty:
            continue
        for col in ("area_id", "ward_id"):
            if col in df.columns:
                for v in df[col].dropna().astype(str).tolist():
                    if v:
                        area_ids.add(v)
    if not area_ids:
        return ["__unassigned__"]
    return sorted(area_ids)


def build_property_buildings_feature_rows(
    *,
    property_registry: pd.DataFrame | None,
    building_footprints: pd.DataFrame | None,
    building_permits: pd.DataFrame | None,
    land_use: pd.DataFrame | None,
    generated_at: str | None = None,
) -> tuple[pd.DataFrame, PropertyBuildingsFeatureBuildStats]:
    """
    Build a lightweight property/buildings feature table for scaffolding.

    - No matching logic (parcel↔footprint↔permit alignment) is performed here.
    - No enforcement/tax recommendations are generated here.
    - Output is intended for later mapping into canonical `platform_object: Feature` records.
    """
    gen = generated_at or _now()
    warnings: list[str] = []

    if all(df is None or df.empty for df in (property_registry, building_footprints, building_permits, land_use)):
        warnings.append("NO_INPUTS_PROVIDED")

    warnings.append("MATCHING_NOT_IMPLEMENTED")
    warnings.append("ENFORCEMENT_AND_TAX_ACTIONS_BLOCKED_BY_POLICY")

    sources = _source_list(property_registry, building_footprints, building_permits, land_use)
    synthetic_used = _synthetic_used(property_registry, building_footprints, building_permits, land_use)
    if synthetic_used:
        warnings.append("SYNTHETIC_INPUT_PRESENT")

    prov_summary_obj = {
        "sources": sources,
        "synthetic_used": bool(synthetic_used),
        "notes": "Scaffolding only; no identity resolution performed; verification-first.",
    }

    area_ids = _extract_area_ids(property_registry, building_footprints, building_permits, land_use)

    # Simple coverage counts for scaffolding.
    pr_count = int(len(property_registry)) if property_registry is not None and not property_registry.empty else 0
    bf_count = int(len(building_footprints)) if building_footprints is not None and not building_footprints.empty else 0
    bp_count = int(len(building_permits)) if building_permits is not None and not building_permits.empty else 0
    lu_count = int(len(land_use)) if land_use is not None and not land_use.empty else 0

    # Placeholder feature stubs aligned to the domain spec (property_buildings.v1.yaml).
    # We do not compute mismatch scores yet.
    rows: list[dict[str, Any]] = []
    for area_id in area_ids:
        rows.append(
            {
                "area_id": area_id,
                "generated_at": gen,
                "property_registry_record_count": pr_count,
                "building_footprint_record_count": bf_count,
                "building_permit_record_count": bp_count,
                "land_use_record_count": lu_count,
                "mismatch_score_property_building": None,
                "under_assessment_candidate_flag": None,
                "provenance_summary": prov_summary_obj,
                "warning_flags": warnings,
            }
        )

    out = pd.DataFrame(rows)
    return (
        out,
        PropertyBuildingsFeatureBuildStats(
            rows_out=int(len(out)),
            source_count=int(len(sources)),
            warning_flags=warnings,
        ),
    )

