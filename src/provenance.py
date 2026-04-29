from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd


PROVENANCE_COLS = [
    "aq_source_type",  # real | interpolated | synthetic | unavailable
    "weather_source_type",  # real | synthetic | unavailable
    "fire_source_type",  # real | unavailable
    "osm_source_type",  # osm | unavailable
    "interpolation_method",
    "nearest_station_distance_km",
    "station_count_used",
    "data_quality_score",
    "warning_flags",
]


def normalize_warning_flags(flags: Iterable[str] | str | None) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    uniq = []
    seen = set()
    for f in flags:
        if not f:
            continue
        f = str(f).strip()
        if f and f not in seen:
            seen.add(f)
            uniq.append(f)
    return "; ".join(uniq)


def add_warning_flag(existing: str, flag: str) -> str:
    if not flag:
        return existing or ""
    if not existing:
        return flag
    parts = [p.strip() for p in existing.split(";") if p.strip()]
    if flag in parts:
        return existing
    parts.append(flag)
    return "; ".join(parts)


def compute_data_quality_score(
    *,
    aq_source_type: str,
    weather_source_type: str,
    fire_source_type: str,
    nearest_station_distance_km: Optional[float],
    station_count_used: Optional[int],
) -> float:
    """
    Simple, conservative 0..1 score intended for honest gating + UI.
    It is not a scientific uncertainty metric.
    """
    score = 1.0

    aq = (aq_source_type or "unavailable").lower()
    if aq == "real":
        score *= 1.0
    elif aq == "interpolated":
        score *= 0.6
    elif aq == "synthetic":
        score *= 0.0
    else:  # unavailable
        score *= 0.0

    wx = (weather_source_type or "unavailable").lower()
    if wx == "real":
        score *= 1.0
    elif wx == "synthetic":
        score *= 0.8
    else:
        score *= 0.5

    fire = (fire_source_type or "unavailable").lower()
    if fire == "real":
        score *= 1.0
    else:
        # fire often optional; don't penalize too hard
        score *= 0.95

    if nearest_station_distance_km is not None and np.isfinite(nearest_station_distance_km):
        # degrade after 5km, strongly after 10km
        if nearest_station_distance_km > 10:
            score *= 0.6
        elif nearest_station_distance_km > 5:
            score *= 0.8

    if station_count_used is not None:
        if station_count_used < 3:
            score *= 0.8
        if station_count_used <= 1:
            score *= 0.6

    return float(max(0.0, min(1.0, score)))


def ensure_provenance_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in PROVENANCE_COLS:
        if c not in out.columns:
            out[c] = np.nan
    if "warning_flags" in out.columns:
        out["warning_flags"] = out["warning_flags"].fillna("").astype(str)
    return out


def dataset_provenance_summary(df: pd.DataFrame) -> dict:
    """
    Small helper to embed provenance summary into metrics/HTML.
    """
    df = ensure_provenance_columns(df)
    def vc(col: str):
        return df[col].fillna("unavailable").astype(str).value_counts().to_dict()

    return {
        "aq_source_type_counts": vc("aq_source_type"),
        "weather_source_type_counts": vc("weather_source_type"),
        "fire_source_type_counts": vc("fire_source_type"),
        "osm_source_type_counts": vc("osm_source_type"),
    }

