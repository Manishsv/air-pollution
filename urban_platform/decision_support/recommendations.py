from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd

from src.recommendations import attach_recommendations as _legacy_attach


def generate_recommendations(
    predictions: pd.DataFrame,
    *,
    pm25_categories: Dict[str, Tuple[float, float]],
    recommendation_allowed: bool,
    recommendation_block_reason: str,
    model_warning_flags: str = "",
) -> pd.DataFrame:
    """
    Generate human-readable recommendations (thin wrapper).
    """
    return _legacy_attach(
        predictions,
        pm25_categories=pm25_categories,
        recommendation_allowed=recommendation_allowed,
        recommendation_block_reason=recommendation_block_reason,
        model_warning_flags=model_warning_flags,
    )

