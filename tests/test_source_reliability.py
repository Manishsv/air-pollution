from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from urban_platform.quality.source_reliability import assess_source_reliability
from urban_platform.quality.observation_quality import apply_source_reliability_to_observations


def _base_obs(ts: pd.Timestamp, vals: list[float], *, entity_id: str = "s1", variable: str = "pm25") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "grid_id": ["x"] * len(vals),
            "timestamp": [ts + pd.Timedelta(hours=i) for i in range(len(vals))],
            "variable": [variable] * len(vals),
            "value": vals,
            "unit": ["u"] * len(vals),
            "source": ["openaq"] * len(vals),
            "confidence": [0.8] * len(vals),
            "quality_flag": ["ok"] * len(vals),
            "observation_id": [f"o{i}" for i in range(len(vals))],
            "entity_id": [entity_id] * len(vals),
            "entity_type": ["sensor"] * len(vals),
            "point_lat": [12.0] * len(vals),
            "point_lon": [77.0] * len(vals),
        }
    )


def test_reliability_healthy_complete_scores_high():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [10, 11, 12, 11, 10, 11, 12])
    rel = assess_source_reliability(obs, expected_frequency_minutes=60, lookback_hours=7, current_time=(start + pd.Timedelta(hours=7)).to_pydatetime())
    r = rel.iloc[0].to_dict()
    assert r["status"] in {"healthy", "degraded"}  # allow slight penalties if heuristics change
    assert float(r["reliability_score"]) >= 0.7


def test_reliability_stale_offline():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [10, 10, 10], entity_id="s2")
    now = (start + pd.Timedelta(hours=48)).to_pydatetime()
    rel = assess_source_reliability(obs, expected_frequency_minutes=60, lookback_hours=72, current_time=now)
    r = rel.iloc[0]
    assert str(r["status"]) == "offline"
    assert float(r["stale_hours"]) > 24.0


def test_reliability_flatline_detected():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [20, 20, 20, 20, 20, 20, 21], entity_id="s3")
    rel = assess_source_reliability(obs, expected_frequency_minutes=60, lookback_hours=7, current_time=(start + pd.Timedelta(hours=7)).to_pydatetime())
    r = rel.iloc[0]
    assert bool(r["flatline_detected"]) is True
    assert "flatline_detected" in str(r["reliability_issues"])


def test_reliability_impossible_pm25_detected():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [10, -1, 12], entity_id="s4")
    rel = assess_source_reliability(obs, expected_frequency_minutes=60, lookback_hours=3, current_time=(start + pd.Timedelta(hours=3)).to_pydatetime())
    r = rel.iloc[0]
    assert bool(r["impossible_value_detected"]) is True
    assert str(r["status"]) in {"suspect", "degraded"}


def test_reliability_duplicate_timestamps_detected():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [10, 11, 12, 13], entity_id="s5")
    obs.loc[1, "timestamp"] = obs.loc[0, "timestamp"]  # duplicate
    rel = assess_source_reliability(obs, expected_frequency_minutes=60, lookback_hours=4, current_time=(start + pd.Timedelta(hours=4)).to_pydatetime())
    r = rel.iloc[0]
    assert float(r["duplicate_timestamp_ratio"]) > 0.0


def test_apply_source_reliability_adjusts_confidence_and_flags_suspect():
    start = pd.Timestamp(datetime(2026, 1, 1, tzinfo=timezone.utc))
    obs = _base_obs(start, [10, 11], entity_id="s6")
    rel = pd.DataFrame(
        [
            {
                "entity_id": "s6",
                "variable": "pm25",
                "reliability_score": 0.5,
                "status": "suspect",
                "reliability_issues": "impossible_value_detected",
            }
        ]
    )
    out = apply_source_reliability_to_observations(obs, rel)
    assert "original_quality_flag" in out.columns
    assert float(out["confidence"].iloc[0]) == 0.8 * 0.5
    assert str(out["quality_flag"].iloc[0]) == "suspect"

