"""Lightweight sanity checks for sensor siting normalization logic."""

from __future__ import annotations

import pandas as pd

from src.sensor_siting import _normalize_01


def test_normalize_01_handles_constant_series() -> None:
    s = pd.Series([5.0, 5.0, 5.0])
    out = _normalize_01(s)
    assert (out == 0.5).all()


def test_normalize_01_handles_range() -> None:
    s = pd.Series([0.0, 10.0])
    out = _normalize_01(s)
    assert abs(float(out.iloc[0]) - 0.0) < 1e-9
    assert abs(float(out.iloc[1]) - 1.0) < 1e-9
