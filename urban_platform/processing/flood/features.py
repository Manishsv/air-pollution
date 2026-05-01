from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FloodFeatureBuildStats:
    rows_out: int
    source_count: int
    warning_flags: list[str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_str(x: Any) -> str:
    return "" if x is None else str(x)


def _json_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        return "{}"


def _extract_area_ids(
    *,
    rainfall_obs: pd.DataFrame | None,
    incident_events: pd.DataFrame | None,
    drainage_entities: pd.DataFrame | None,
) -> list[str]:
    """
    Best-effort area_id extraction for scaffolding:
    - Prefer ward_id from record_source_metadata (incidents/assets samples include this)
    - Fallback to city_id from feed_source_metadata
    - Otherwise return a single "__unassigned__" row
    """
    area_ids: set[str] = set()

    def from_record_meta(df: pd.DataFrame, col: str) -> None:
        if df is None or df.empty or col not in df.columns:
            return
        for v in df[col].dropna().tolist():
            if isinstance(v, dict) and v.get("ward_id"):
                area_ids.add(str(v.get("ward_id")))

    from_record_meta(incident_events, "record_source_metadata")

    # drainage entities store record metadata inside attributes
    if drainage_entities is not None and not drainage_entities.empty and "attributes" in drainage_entities.columns:
        for attrs in drainage_entities["attributes"].dropna().tolist():
            if isinstance(attrs, dict):
                rsm = attrs.get("record_source_metadata")
                if isinstance(rsm, dict) and rsm.get("ward_id"):
                    area_ids.add(str(rsm.get("ward_id")))

    # Fallback: use city_id from feed_source_metadata if present
    def from_feed_meta(df: pd.DataFrame) -> None:
        if df is None or df.empty or "feed_source_metadata" not in df.columns:
            return
        for v in df["feed_source_metadata"].dropna().tolist():
            if isinstance(v, dict) and v.get("city_id"):
                area_ids.add(str(v.get("city_id")))

    from_feed_meta(rainfall_obs if rainfall_obs is not None else pd.DataFrame())
    from_feed_meta(incident_events if incident_events is not None else pd.DataFrame())

    if not area_ids:
        return ["__unassigned__"]
    return sorted(area_ids)


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
    for df in dfs:
        if df is None or df.empty:
            continue
        # rainfall scaffolding keeps provenance in `provenance` column
        if "provenance" in df.columns:
            for p in df["provenance"].dropna().tolist():
                if isinstance(p, dict) and bool(p.get("synthetic")):
                    return True
        # assets keep provenance inside attributes
        if "attributes" in df.columns:
            for attrs in df["attributes"].dropna().tolist():
                if isinstance(attrs, dict):
                    prov = attrs.get("provenance")
                    if isinstance(prov, dict) and bool(prov.get("synthetic")):
                        return True
    return False


def build_flood_feature_rows(
    *,
    rainfall_obs: pd.DataFrame | None,
    incident_events: pd.DataFrame | None,
    drainage_entities: pd.DataFrame | None,
    generated_at: str | None = None,
) -> tuple[pd.DataFrame, FloodFeatureBuildStats]:
    """
    Build a simple, explicit flood feature table intended for early scaffolding.

    Output is a wide row-per-area (or row-per-h3 later) table with provenance and warning flags.

    Intended mapping to canonical platform objects:
    - These rows can later be emitted as multiple `platform_object: Feature` long-form entries
      (feature_name/value/unit/source/confidence), but we do not enforce that mapping here.
    """
    gen = generated_at or _now()
    warnings: list[str] = []

    sources = _source_list(rainfall_obs, incident_events, drainage_entities)
    synthetic_used = _synthetic_used(rainfall_obs, incident_events, drainage_entities)

    if synthetic_used:
        warnings.append("SYNTHETIC_INPUT_PRESENT")

    # Placeholder until elevation/DEM is integrated under a provider contract.
    warnings.append("LOW_LYING_PROXY_UNAVAILABLE")

    area_ids = _extract_area_ids(rainfall_obs=rainfall_obs, incident_events=incident_events, drainage_entities=drainage_entities)

    # Rainfall intensity summary (best-effort: mean of rainfall_intensity_mm_per_hr)
    rainfall_value = None
    if rainfall_obs is not None and not rainfall_obs.empty:
        sel = rainfall_obs.copy()
        if "observed_property" in sel.columns:
            sel = sel[sel["observed_property"].astype(str) == "rainfall_intensity_mm_per_hr"].copy()
        if not sel.empty and "value" in sel.columns:
            rainfall_value = pd.to_numeric(sel["value"], errors="coerce").dropna().mean()

    # Incident count/density (count only for scaffolding)
    incident_count = int(len(incident_events)) if incident_events is not None and not incident_events.empty else 0

    # Drainage asset count
    drainage_asset_count = int(len(drainage_entities)) if drainage_entities is not None and not drainage_entities.empty else 0

    # Data quality score (simple heuristic; does not override safety gates)
    # 1.0 baseline, downweight if synthetic is present.
    data_quality_score = 1.0 if not synthetic_used else 0.4

    prov_summary_obj = {
        "sources": sources,
        "synthetic_used": bool(synthetic_used),
        "notes": "Scaffolding summary; calibrate once authoritative sources and coverage metrics exist.",
    }

    rows: list[dict[str, Any]] = []
    for area_id in area_ids:
        rows.append(
            {
                "area_id": area_id,
                "h3_id": None,
                "generated_at": gen,
                "rainfall_mm_per_hour": None if rainfall_value is None else float(rainfall_value),
                "incident_count": int(incident_count),
                "drainage_asset_count": int(drainage_asset_count),
                "low_lying_proxy": None,
                "elevation_risk_proxy": None,
                "data_quality_score": float(data_quality_score),
                "source_count": int(len(sources)),
                "provenance_summary": prov_summary_obj,
                "warning_flags": warnings,
            }
        )

    out = pd.DataFrame(rows)
    return out, FloodFeatureBuildStats(rows_out=int(len(out)), source_count=int(len(sources)), warning_flags=warnings)

