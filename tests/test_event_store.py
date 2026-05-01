from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from urban_platform.fabric.event_store import build_event_store, persist_event_store
from urban_platform.api import local as api


def _packet(*, packet_id: str, h3_id: str, ts: datetime, category: str, confidence_score: float, allowed: bool, warning_flags: str = "") -> dict:
    return {
        "packet_id": packet_id,
        "h3_id": h3_id,
        "timestamp": ts.isoformat(),
        "confidence_level": "low" if confidence_score < 0.4 else "high",
        "actionability_level": "blocked" if not allowed else "verify_only",
        "prediction": {"pm25_category_india": category},
        "confidence": {"confidence_score": confidence_score, "recommendation_allowed": allowed, "recommendation_block_reason": "demo"},
        "provenance": {"warning_flags": warning_flags, "station_count_used": 1},
        "recommended_action": "demo_action",
        "audit_context": {"avg_nearest_station_distance_km": 12.0},
        "provenance_summary": {"number_of_real_aq_stations": 1},
    }


def test_event_store_is_created_and_links_to_packet(tmp_path: Path):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    packets = [
        _packet(packet_id="p1", h3_id="h3a", ts=ts, category="poor", confidence_score=0.2, allowed=False, warning_flags="SYNTHETIC_AQ_USED"),
    ]
    rel = pd.DataFrame([{"entity_id": "s1", "variable": "pm25", "status": "degraded", "reliability_score": 0.6, "reliability_issues": "stale_data"}])
    df = build_event_store(decision_packets=packets, reliability_df=rel)
    assert not df.empty
    assert (df["source_packet_id"].fillna("") == "p1").any()

    out = persist_event_store(df, base_path=tmp_path, write_json=True)
    assert out["event_store_parquet"].exists()
    assert out["event_store_json"].exists()


def test_get_events_filters(tmp_path: Path):
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    packets = [
        _packet(packet_id="p1", h3_id="h3a", ts=ts, category="poor", confidence_score=0.2, allowed=False),
        _packet(packet_id="p2", h3_id="h3b", ts=ts + timedelta(hours=1), category="good", confidence_score=0.9, allowed=True),
    ]
    df = build_event_store(decision_packets=packets, reliability_df=pd.DataFrame())
    persist_event_store(df, base_path=tmp_path, write_json=False)

    all_events = api.get_events(base_dir=tmp_path)
    assert len(all_events) >= 1

    only_blocked = api.get_events(event_type="recommendation_blocked", base_dir=tmp_path)
    assert (only_blocked["event_type"].astype(str) == "recommendation_blocked").all()

    start = ts + timedelta(minutes=30)
    later = api.get_events(start_time=start, base_dir=tmp_path)
    assert (pd.to_datetime(later["timestamp"], utc=True) >= pd.to_datetime(start, utc=True)).all()


def test_empty_event_store_handled_safely(tmp_path: Path):
    df = pd.DataFrame()
    persist_event_store(df, base_path=tmp_path, write_json=False)
    out = api.get_events(base_dir=tmp_path)
    assert isinstance(out, pd.DataFrame)
