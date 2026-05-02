from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

# Fixed per-row blocked-use tokens (Phase 1 open-data; not domain schema enum).
STANDARD_BLOCKED_USES: list[str] = [
    "NOT_LEGAL_PROPERTY_RECORD",
    "NOT_PERMIT_VIOLATION_EVIDENCE",
    "FIELD_VERIFICATION_REQUIRED",
    "MUNICIPAL_INTEGRATION_REQUIRED_FOR_TAX_OR_ENFORCEMENT_USE",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_area_key(row: pd.Series) -> str:
    for col in ("ward_id", "area_id", "spatial_unit_id"):
        if col in row.index and pd.notna(row.get(col)) and str(row.get(col)).strip():
            return str(row.get(col)).strip()
    return "__unassigned__"


def _footprint_area_sq_m(row: pd.Series) -> float:
    for col in ("built_up_area_sq_m", "footprint_area_sq_m"):
        if col in row.index and pd.notna(row.get(col)):
            try:
                return float(row.get(col))
            except (TypeError, ValueError):
                pass
    if "value" in row.index and pd.notna(row.get("value")):
        unit = str(row.get("unit") or "").lower()
        if unit in {"sq_m", "m2", "m²"}:
            try:
                return float(row.get("value"))
            except (TypeError, ValueError):
                pass
    return 0.0


def _geometry_ok(row: pd.Series) -> bool:
    geom = row.get("geometry")
    if isinstance(geom, dict) and str(geom.get("type") or "") in {
        "Polygon",
        "MultiPolygon",
        "Point",
        "MultiPoint",
    }:
        return True
    return False


def _footprint_subset_for_area(df: pd.DataFrame | None, area_key: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    keys = df.apply(lambda r: _row_area_key(r) == area_key, axis=1)
    return df.loc[keys]


def _adequate_footprint_geometry(current_building_footprints: pd.DataFrame | None, area_key: str) -> bool:
    """
    Adequate if summed footprint area is positive OR a majority of rows carry polygon geometry.
    """
    sub = _footprint_subset_for_area(current_building_footprints, area_key)
    if sub.empty:
        return False
    area_sum = 0.0
    geom_hits = 0
    for _, row in sub.iterrows():
        area_sum += _footprint_area_sq_m(row)
        if _geometry_ok(row):
            geom_hits += 1
    n = len(sub)
    if area_sum > 1e-6:
        return True
    if n > 0 and geom_hits / n >= 0.5:
        return True
    return False


def _sources_from_df(df: pd.DataFrame | None) -> set[str]:
    if df is None or df.empty or "source" not in df.columns:
        return set()
    out: set[str] = set()
    for s in df["source"].dropna().astype(str).tolist():
        if s:
            out.add(s)
    return out


def _synthetic_from_df(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty:
        return False
    if "provenance" not in df.columns:
        return False
    for p in df["provenance"].dropna().tolist():
        if isinstance(p, dict) and (
            bool(p.get("synthetic")) or str(p.get("license", "")).lower() in {"demo_only", "synthetic"}
        ):
            return True
    return False


def _aggregate_footprints(df: pd.DataFrame | None) -> pd.DataFrame:
    """Return columns area_key, building_count, built_up_area_sq_m."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["area_key", "building_count", "built_up_area_sq_m"])
    keys: list[str] = []
    counts: list[int] = []
    areas: list[float] = []
    for _, row in df.iterrows():
        k = _row_area_key(row)
        keys.append(k)
        counts.append(1)
        areas.append(_footprint_area_sq_m(row))
    tmp = pd.DataFrame({"area_key": keys, "_c": counts, "_a": areas})
    g = tmp.groupby("area_key", as_index=False).agg(building_count=("_c", "sum"), built_up_area_sq_m=("_a", "sum"))
    return g


def _satellite_counts_by_area(sat: pd.DataFrame | None) -> dict[str, int]:
    if sat is None or sat.empty:
        return {}
    out: dict[str, int] = {}
    for _, row in sat.iterrows():
        k = _row_area_key(row)
        out[k] = out.get(k, 0) + 1
    return out


def _boundary_area_keys(boundary_units: pd.DataFrame | None) -> list[str]:
    if boundary_units is None or boundary_units.empty:
        return []
    keys: set[str] = set()
    for _, row in boundary_units.iterrows():
        keys.add(_row_area_key(row))
    return sorted(keys)


def _merge_area_keys(
    cur: pd.DataFrame,
    prev: pd.DataFrame | None,
    sat: pd.DataFrame | None,
    boundary_units: pd.DataFrame | None,
) -> list[str]:
    keys: set[str] = set()
    if cur is not None and not cur.empty:
        for _, row in cur.iterrows():
            keys.add(_row_area_key(row))
    if prev is not None and not prev.empty:
        for _, row in prev.iterrows():
            keys.add(_row_area_key(row))
    if sat is not None and not sat.empty:
        for _, row in sat.iterrows():
            keys.add(_row_area_key(row))
    for k in _boundary_area_keys(boundary_units):
        keys.add(k)
    if not keys:
        return ["__unassigned__"]
    return sorted(keys)


def _open_data_coverage_score(
    *,
    has_current: bool,
    has_previous: bool,
    has_satellite: bool,
    has_boundary: bool,
) -> float:
    score = 0.0
    if has_current:
        score += 0.35
    if has_previous:
        score += 0.30
    if has_satellite:
        score += 0.20
    if has_boundary:
        score += 0.15
    return round(min(1.0, score), 3)


def _readiness_for_row(
    *,
    global_has_current_footprints: bool,
    current_count: int,
    adequate_geometry: bool,
    has_previous_for_area: bool,
    has_satellite_for_area: bool,
) -> str:
    if not global_has_current_footprints:
        return "not_ready"
    if current_count > 0 and not adequate_geometry:
        return "not_ready"
    if current_count <= 0:
        return "partial"
    if adequate_geometry and (has_previous_for_area or has_satellite_for_area):
        return "ready_for_review"
    return "partial"


def _confidence_score(readiness: str, open_data_coverage: float) -> float | None:
    if readiness == "not_ready":
        return 0.12
    if readiness == "partial":
        return round(min(0.45, 0.25 + 0.2 * open_data_coverage), 3)
    return round(min(0.72, 0.45 + 0.3 * open_data_coverage), 3)


def build_built_environment_change_features(
    current_building_footprints: pd.DataFrame | None,
    previous_building_footprints: pd.DataFrame | None = None,
    satellite_change_signals: pd.DataFrame | None = None,
    boundary_units: pd.DataFrame | None = None,
    generated_at: str | None = None,
    lookback_window_days: int = 365,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Open-data Phase 1 feature scaffolding: built-environment change candidates and readiness.

    - Does not require municipal registry, permits, tax, or owner data.
    - Does not detect legal non-compliance; outputs are triage/readiness signals only.
    - Emits ``warning_flags`` (readiness/coverage) and a fixed four-token ``blocked_uses`` list per row.
    """
    gen = generated_at or _now()
    has_current_df = current_building_footprints is not None and not current_building_footprints.empty
    has_previous = previous_building_footprints is not None and not previous_building_footprints.empty
    has_satellite_df = satellite_change_signals is not None and not satellite_change_signals.empty
    has_boundary = boundary_units is not None and not boundary_units.empty

    cur_g = _aggregate_footprints(current_building_footprints if has_current_df else None)
    prev_g = _aggregate_footprints(previous_building_footprints if has_previous else None)
    sat_counts = _satellite_counts_by_area(satellite_change_signals if has_satellite_df else None)

    area_keys = _merge_area_keys(
        current_building_footprints if has_current_df else pd.DataFrame(),
        previous_building_footprints,
        satellite_change_signals,
        boundary_units,
    )

    sources: set[str] = set()
    sources |= _sources_from_df(current_building_footprints if has_current_df else None)
    sources |= _sources_from_df(previous_building_footprints if has_previous else None)
    sources |= _sources_from_df(satellite_change_signals if has_satellite_df else None)
    sources |= _sources_from_df(boundary_units if has_boundary else None)

    synthetic_used = any(
        _synthetic_from_df(df)
        for df in (
            current_building_footprints if has_current_df else None,
            previous_building_footprints if has_previous else None,
            satellite_change_signals if has_satellite_df else None,
            boundary_units if has_boundary else None,
        )
    )

    cur_map = {r["area_key"]: r for _, r in cur_g.iterrows()} if not cur_g.empty else {}
    prev_map = {r["area_key"]: r for _, r in prev_g.iterrows()} if not prev_g.empty else {}

    any_low_geometry = False
    rows: list[dict[str, Any]] = []
    for area_key in area_keys:
        cur_row = cur_map.get(area_key)
        prev_row = prev_map.get(area_key)

        cur_count = int(cur_row["building_count"]) if cur_row is not None else 0
        cur_area = float(cur_row["built_up_area_sq_m"]) if cur_row is not None else 0.0

        prev_count: int | None = int(prev_row["building_count"]) if prev_row is not None else None
        prev_area: float | None = float(prev_row["built_up_area_sq_m"]) if prev_row is not None else None

        adequate_geometry = _adequate_footprint_geometry(
            current_building_footprints if has_current_df else None, area_key
        )

        warnings: list[str] = []
        if prev_row is None:
            warnings.append("BASELINE_MISSING")
        if (not has_satellite_df) or (sat_counts.get(area_key, 0) == 0):
            warnings.append("SATELLITE_CHANGE_SIGNALS_MISSING")
        if cur_count > 0 and not adequate_geometry:
            warnings.append("LOW_GEOMETRY_COVERAGE")
            any_low_geometry = True
        if synthetic_used:
            warnings.append("SYNTHETIC_INPUT_PRESENT")

        if prev_count is not None:
            new_cand = max(0, cur_count - prev_count)
            rem_cand = max(0, prev_count - cur_count)
        else:
            new_cand = None
            rem_cand = None

        if prev_area is not None and prev_area > 0 and cur_area is not None:
            chg_sq = cur_area - prev_area
            chg_pct = chg_sq / prev_area * 100.0
        elif prev_area is not None and prev_area == 0 and cur_area and cur_area > 0:
            chg_sq = cur_area
            chg_pct = None
        else:
            chg_sq = None
            chg_pct = None

        sat_n = int(sat_counts.get(area_key, 0)) if has_satellite_df else None

        has_satellite_for_area = sat_n is not None and sat_n > 0

        cov = _open_data_coverage_score(
            has_current=(cur_count > 0) or (area_key in cur_map),
            has_previous=prev_row is not None,
            has_satellite=has_satellite_for_area,
            has_boundary=has_boundary,
        )

        readiness = _readiness_for_row(
            global_has_current_footprints=has_current_df,
            current_count=cur_count,
            adequate_geometry=adequate_geometry,
            has_previous_for_area=prev_row is not None,
            has_satellite_for_area=has_satellite_for_area,
        )

        ward_id = area_key if area_key != "__unassigned__" else None
        prov = {
            "sources": sorted(sources) if sources else [],
            "synthetic_used": bool(synthetic_used),
            "notes": "Open-data built-environment change scaffolding; not legal or tax evidence.",
        }

        rows.append(
            {
                "area_id": area_key,
                "ward_id": ward_id,
                "generated_at": gen,
                "lookback_window_days": int(lookback_window_days),
                "current_building_count": cur_count,
                "previous_building_count": prev_count,
                "new_building_candidate_count": new_cand,
                "removed_or_changed_building_candidate_count": rem_cand,
                "built_up_area_current_sq_m": cur_area,
                "built_up_area_previous_sq_m": prev_area,
                "built_up_area_change_sq_m": chg_sq,
                "built_up_area_change_pct": chg_pct,
                "satellite_change_signal_count": sat_n,
                "open_data_coverage_score": cov,
                "change_detection_readiness": readiness,
                "confidence_score": _confidence_score(readiness, cov),
                "source_count": int(len(sources)),
                "provenance_summary": prov,
                "warning_flags": sorted(set(warnings)),
                "blocked_uses": list(STANDARD_BLOCKED_USES),
            }
        )

    out = pd.DataFrame(rows)
    meta = {
        "rows_out": int(len(out)),
        "source_count": int(len(sources)),
        "has_current_footprints": bool(has_current_df),
        "has_previous_footprints": bool(has_previous),
        "has_satellite_signals": bool(has_satellite_df),
        "has_boundary_units": bool(has_boundary),
        "warning_flags_global": sorted(
            set(
                ([] if has_previous else ["BASELINE_MISSING"])
                + ([] if has_satellite_df else ["SATELLITE_CHANGE_SIGNALS_MISSING"])
                + (["SYNTHETIC_INPUT_PRESENT"] if synthetic_used else [])
                + (["LOW_GEOMETRY_COVERAGE"] if any_low_geometry else [])
            )
        ),
        "blocked_uses_template": list(STANDARD_BLOCKED_USES),
    }
    return out, meta