from __future__ import annotations

from typing import Iterable, List, Optional

import pandas as pd

from .schemas import normalize_quality_flag, observation_required_columns


class SchemaValidationError(ValueError):
    pass


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> List[str]:
    have = set(df.columns)
    return [c for c in required if c not in have]


def validate_observations(df: pd.DataFrame, *, allow_extra_columns: bool = True) -> None:
    req = observation_required_columns()
    missing = _missing_columns(df, req)
    if missing:
        raise SchemaValidationError(f"Observation schema missing columns: {missing}")
    if not allow_extra_columns:
        extra = [c for c in df.columns if c not in set(req)]
        if extra:
            raise SchemaValidationError(f"Observation schema has extra columns: {extra}")

    if len(df) == 0:
        return

    # Basic type checks (best-effort; don't overconstrain early migration).
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        raise SchemaValidationError("Observation.timestamp must be datetime-like")

    # No nulls in critical identifiers
    for col in ["observation_id", "entity_id", "observed_property", "source"]:
        if df[col].isna().any():
            raise SchemaValidationError(f"Observation.{col} contains nulls")

    # Normalize quality_flag values into a small, provenance-friendly set.
    df["quality_flag"] = df["quality_flag"].astype(str).map(normalize_quality_flag)


def validate_nonempty(df: pd.DataFrame, *, name: str, min_rows: int = 1) -> None:
    if df is None or len(df) < int(min_rows):
        raise SchemaValidationError(f"{name} must have at least {min_rows} rows")


def assert_quality_gate(*, synthetic_ratio: float, max_synthetic_ratio: float, block_if_synthetic: bool) -> tuple[bool, str]:
    """
    Minimal reusable quality gate primitive.
    Returns (allowed, reason).
    """
    if block_if_synthetic and float(synthetic_ratio) > float(max_synthetic_ratio):
        return False, f"Synthetic data ratio {synthetic_ratio:.3f} exceeds max {max_synthetic_ratio:.3f}"
    return True, ""

