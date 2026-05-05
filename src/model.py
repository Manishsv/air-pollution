from __future__ import annotations

"""
Legacy import path for sklearn PM2.5 training / inference.

Canonical: `urban_platform.models.sklearn_pm25`.
"""

from urban_platform.models.sklearn_pm25 import (  # noqa: F401
    ModelArtifacts,
    evaluate_regression,
    load_model,
    predict_latest,
    train_models,
    _time_split,
)
