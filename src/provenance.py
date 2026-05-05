from __future__ import annotations

"""
Legacy import path for provenance helpers.

Canonical implementation lives in `urban_platform.common.provenance`.
"""

from urban_platform.common.provenance import (  # noqa: F401
    PROVENANCE_COLS,
    add_warning_flag,
    compute_data_quality_score,
    dataset_provenance_summary,
    ensure_provenance_columns,
    normalize_warning_flags,
)
