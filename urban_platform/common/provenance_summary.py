from __future__ import annotations

from typing import Any, Dict


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def build_provenance_summary(metrics: Dict[str, Any] | None, data_audit: Dict[str, Any] | None) -> dict:
    """
    Build a minimal, stakeholder-safe provenance summary for surfacing in outputs.

    Required output keys:
      - percent_cells_interpolated
      - percent_cells_synthetic
      - percent_low_confidence (derived from confidence_score < 0.4 across cells; supplied via metrics when available)
      - number_of_real_aq_stations
      - avg_nearest_station_distance_km
      - recommendation_allowed
      - recommendation_block_reason
    """
    m = metrics or {}
    a = data_audit or {}

    # Primary sources for coverage mix and station distance live in data_audit.
    percent_cells_interpolated = _as_float(a.get("percent_cells_interpolated"), 0.0)
    percent_cells_synthetic = _as_float(a.get("percent_cells_synthetic"), 0.0)
    number_of_real_aq_stations = _as_int(a.get("number_of_real_aq_stations"), 0)
    avg_nearest_station_distance_km = _as_float(a.get("avg_nearest_station_distance_km"), float("nan"))
    recommendation_allowed = bool(a.get("recommendation_allowed", True))
    recommendation_block_reason = str(a.get("recommendation_block_reason") or "")

    # Percent low-confidence is derived from confidence_score < 0.4 across cells.
    # The canonical place we persist this is metrics["provenance_low_confidence_ratio"].
    percent_low_confidence = None
    for k in ["provenance_low_confidence_ratio", "percent_low_confidence", "low_confidence_ratio"]:
        if k in m:
            try:
                percent_low_confidence = float(m.get(k))
            except Exception:
                percent_low_confidence = None
            break

    return {
        "percent_cells_interpolated": percent_cells_interpolated,
        "percent_cells_synthetic": percent_cells_synthetic,
        "percent_low_confidence": percent_low_confidence,
        "number_of_real_aq_stations": number_of_real_aq_stations,
        "avg_nearest_station_distance_km": avg_nearest_station_distance_km,
        "recommendation_allowed": recommendation_allowed,
        "recommendation_block_reason": recommendation_block_reason,
    }

