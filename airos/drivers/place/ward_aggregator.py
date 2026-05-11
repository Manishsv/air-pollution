"""Aggregate feature store H3-level data to ward-level quality of life metrics."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from .ward_registry import load_wards
from .h3_to_ward import assign_wards

logger = logging.getLogger(__name__)

# Quality-of-life component weights
_QOL_WEIGHTS = {
    "safety":  0.40,   # flood risk → safety
    "health":  0.35,   # air quality → health
    "thermal": 0.25,   # heat risk → thermal comfort
}


@dataclass
class WardAggregationResult:
    wards_df: pd.DataFrame       # one row per ward, WARD_FEATURE_COLUMNS
    city_id: str
    timestamp_bucket: str
    available_domains: List[str] = field(default_factory=list)
    ward_count: int = 0


def aggregate_city_wards(
    city_id: str,
    timestamp_bucket: Optional[str] = None,
) -> WardAggregationResult:
    """Read cross-domain features from the feature store, join to ward boundaries,
    and compute ward-level quality-of-life index.

    Returns WardAggregationResult with empty wards_df if no data is available.
    """
    try:
        from airos.drivers.feature_store.reader import FeatureStoreReader
        reader = FeatureStoreReader()
        cross = reader.cross_domain_query(city_id=city_id, timestamp_bucket=timestamp_bucket)
        reader.close()
    except Exception as exc:
        logger.warning("Feature store read failed for %s: %s", city_id, exc)
        return WardAggregationResult(
            wards_df=pd.DataFrame(), city_id=city_id,
            timestamp_bucket=timestamp_bucket or "",
        )

    if cross.cells_df.empty:
        return WardAggregationResult(
            wards_df=pd.DataFrame(), city_id=city_id,
            timestamp_bucket=cross.timestamp_bucket,
            available_domains=cross.available_domains,
        )

    wards = load_wards(city_id)
    if not wards:
        return WardAggregationResult(
            wards_df=pd.DataFrame(), city_id=city_id,
            timestamp_bucket=cross.timestamp_bucket,
        )

    cells = assign_wards(cross.cells_df, wards)
    ward_df = _aggregate(cells, cross.available_domains, cross.timestamp_bucket, city_id)

    return WardAggregationResult(
        wards_df=ward_df,
        city_id=city_id,
        timestamp_bucket=cross.timestamp_bucket,
        available_domains=cross.available_domains,
        ward_count=len(ward_df),
    )


def _aggregate(
    cells: pd.DataFrame,
    available_domains: List[str],
    timestamp_bucket: str,
    city_id: str,
) -> pd.DataFrame:
    """Group by ward_id and compute aggregate risk + QoL metrics."""
    rows = []
    for ward_id, group in cells.groupby("ward_id"):
        if ward_id == "unassigned":
            continue

        n = len(group)
        avg_flood = _mean(group, "flood_risk_score")
        avg_aqi   = _mean(group, "aqi_score")
        avg_heat  = _mean(group, "heat_risk_score")
        composite = _mean(group, "composite_risk_score")
        elevated  = int((group.get("elevated_domain_count", pd.Series([], dtype=int)) >= 1).sum())
        multi     = int((group.get("elevated_domain_count", pd.Series([], dtype=int)) >= 2).sum())

        # QoL components: 1 − risk (higher = better)
        qol_safety  = (1.0 - avg_flood)  if avg_flood  is not None else None
        qol_health  = (1.0 - avg_aqi)    if avg_aqi    is not None else None
        qol_thermal = (1.0 - avg_heat)   if avg_heat   is not None else None

        # Weighted QoL index over available domains
        qol_index = _weighted_qol(qol_safety, qol_health, qol_thermal, available_domains)

        rows.append({
            "ward_id":            ward_id,
            "city_id":            city_id,
            "ward_name":          group["ward_name"].iloc[0],
            "cell_count":         n,
            "avg_flood_risk":     _round(avg_flood),
            "avg_aqi_score":      _round(avg_aqi),
            "avg_heat_risk":      _round(avg_heat),
            "composite_risk":     _round(composite),
            "elevated_cell_count":elevated,
            "multi_risk_cell_count": multi,
            "qol_safety":         _round(qol_safety),
            "qol_health":         _round(qol_health),
            "qol_thermal":        _round(qol_thermal),
            "qol_index":          _round(qol_index),
            "domains_present":    ", ".join(available_domains),
            "timestamp_bucket":   timestamp_bucket,
        })

    return pd.DataFrame(rows).sort_values("qol_index", ascending=True).reset_index(drop=True)


def _mean(df: pd.DataFrame, col: str) -> Optional[float]:
    if col not in df.columns:
        return None
    vals = df[col].dropna()
    return float(vals.mean()) if not vals.empty else None


def _round(v: Optional[float], dp: int = 3) -> Optional[float]:
    return round(v, dp) if v is not None else None


def _weighted_qol(
    safety: Optional[float],
    health: Optional[float],
    thermal: Optional[float],
    available_domains: List[str],
) -> Optional[float]:
    total_w, total_v = 0.0, 0.0
    if safety  is not None and "flood" in available_domains:
        total_w += _QOL_WEIGHTS["safety"];  total_v += _QOL_WEIGHTS["safety"]  * safety
    if health  is not None and "air"   in available_domains:
        total_w += _QOL_WEIGHTS["health"];  total_v += _QOL_WEIGHTS["health"]  * health
    if thermal is not None and "heat"  in available_domains:
        total_w += _QOL_WEIGHTS["thermal"]; total_v += _QOL_WEIGHTS["thermal"] * thermal
    return (total_v / total_w) if total_w > 0 else None
