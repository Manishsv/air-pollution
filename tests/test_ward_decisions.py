from __future__ import annotations

import pandas as pd
import pytest

from urban_platform.place.ward_decisions import (
    generate_ward_decisions,
    decisions_to_dataframe,
    _score_urgency,
    _packet_id,
)
from urban_platform.place.ward_aggregator import WardAggregationResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_result(rows: list[dict], domains: list[str] | None = None) -> WardAggregationResult:
    return WardAggregationResult(
        wards_df=pd.DataFrame(rows),
        city_id="bangalore_demo",
        timestamp_bucket="2026-05-07T06:00",
        available_domains=["flood", "air", "heat"] if domains is None else domains,
        ward_count=len(rows),
    )


def _ward(ward_id="w01", ward_name="Ward 1", aqi=None, flood=None, heat=None,
          composite=None, multi_risk=0, cell_count=10) -> dict:
    return {
        "ward_id":              ward_id,
        "ward_name":            ward_name,
        "city_id":              "bangalore_demo",
        "avg_aqi_score":        aqi,
        "avg_flood_risk":       flood,
        "avg_heat_risk":        heat,
        "composite_risk":       composite,
        "multi_risk_cell_count": multi_risk,
        "elevated_cell_count":  0,
        "cell_count":           cell_count,
        "qol_index":            0.5,
        "qol_safety":           None,
        "qol_health":           None,
        "qol_thermal":          None,
        "domains_present":      "flood, air, heat",
    }


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_wards_df_returns_no_packets():
    result = WardAggregationResult(
        wards_df=pd.DataFrame(), city_id="bangalore_demo",
        timestamp_bucket="2026-05-07T06:00",
    )
    assert generate_ward_decisions(result) == []


def test_no_domains_returns_no_packets():
    result = _make_result([_ward(aqi=0.8, flood=0.8, heat=0.8)], domains=[])
    assert generate_ward_decisions(result) == []


# ── Air quality trigger ────────────────────────────────────────────────────────

def test_high_aqi_generates_air_packet():
    result = _make_result([_ward(aqi=0.65)], domains=["air"])
    packets = generate_ward_decisions(result)
    assert any(p["domain"] == "air" for p in packets)


def test_low_aqi_below_threshold_no_packet():
    result = _make_result([_ward(aqi=0.30)], domains=["air"])
    packets = generate_ward_decisions(result)
    assert not any(p["domain"] == "air" for p in packets)


def test_early_morning_aqi_spike_attributes_waste_burning():
    result = WardAggregationResult(
        wards_df=pd.DataFrame([_ward(aqi=0.70)]),
        city_id="bangalore_demo",
        timestamp_bucket="2026-05-07T06:00",   # hour=6, in 5–8 window
        available_domains=["air"],
    )
    packets = generate_ward_decisions(result)
    air_pkt = next(p for p in packets if p["domain"] == "air")
    assert air_pkt["signal"]["source_attribution"] == "waste_burning"
    assert air_pkt["decision_id"] == "AQ-D1"


def test_midday_high_aqi_attributes_traffic_or_industrial():
    result = WardAggregationResult(
        wards_df=pd.DataFrame([_ward(aqi=0.75)]),
        city_id="bangalore_demo",
        timestamp_bucket="2026-05-07T13:00",   # hour=13, outside waste burning window
        available_domains=["air"],
    )
    packets = generate_ward_decisions(result)
    air_pkt = next(p for p in packets if p["domain"] == "air")
    assert air_pkt["signal"]["source_attribution"] == "traffic_or_industrial"


# ── Flood trigger ──────────────────────────────────────────────────────────────

def test_high_flood_risk_generates_flood_packet():
    result = _make_result([_ward(flood=0.75)], domains=["flood"])
    packets = generate_ward_decisions(result)
    assert any(p["domain"] == "flood" for p in packets)


def test_low_flood_risk_no_packet():
    result = _make_result([_ward(flood=0.40)], domains=["flood"])
    packets = generate_ward_decisions(result)
    assert not any(p["domain"] == "flood" for p in packets)


def test_high_multi_risk_cells_attributes_drain_blockage():
    result = _make_result([_ward(flood=0.72, multi_risk=4, cell_count=10)], domains=["flood"])
    packets = generate_ward_decisions(result)
    flood_pkt = next(p for p in packets if p["domain"] == "flood")
    assert flood_pkt["signal"]["source_attribution"] == "drain_blockage"


def test_very_high_flood_risk_recommends_sandbags():
    result = _make_result([_ward(flood=0.85)], domains=["flood"])
    packets = generate_ward_decisions(result)
    flood_pkt = next(p for p in packets if p["domain"] == "flood")
    assert flood_pkt["decision_id"] == "FL-D3"


# ── Heat trigger ──────────────────────────────────────────────────────────────

def test_high_heat_risk_generates_heat_packet():
    result = _make_result([_ward(heat=0.78)], domains=["heat"])
    packets = generate_ward_decisions(result)
    assert any(p["domain"] == "heat" for p in packets)


def test_low_heat_risk_no_packet():
    result = _make_result([_ward(heat=0.45)], domains=["heat"])
    packets = generate_ward_decisions(result)
    assert not any(p["domain"] == "heat" for p in packets)


def test_structural_heat_generates_uhi_attribution():
    result = _make_result([_ward(heat=0.80)], domains=["heat"])
    packets = generate_ward_decisions(result)
    heat_pkt = next(p for p in packets if p["domain"] == "heat")
    assert heat_pkt["signal"]["source_attribution"] == "uhi_green_cover_deficit"


# ── Cross-domain trigger ──────────────────────────────────────────────────────

def test_two_elevated_domains_generates_cross_domain_packet():
    result = _make_result([_ward(aqi=0.65, flood=0.72, composite=0.68)])
    packets = generate_ward_decisions(result)
    assert any(p["domain"] == "cross_domain" for p in packets)


def test_single_elevated_domain_no_cross_domain_packet():
    result = _make_result([_ward(aqi=0.65, flood=0.30, heat=0.30, composite=0.42)])
    packets = generate_ward_decisions(result)
    assert not any(p["domain"] == "cross_domain" for p in packets)


def test_cross_domain_packet_requires_escalation():
    result = _make_result([_ward(aqi=0.70, flood=0.75, composite=0.72)])
    packets = generate_ward_decisions(result)
    xd = next(p for p in packets if p["domain"] == "cross_domain")
    assert xd["escalation_required"] is True
    assert xd["escalate_to"] == "zonal_officer"


# ── Urgency ───────────────────────────────────────────────────────────────────

def test_urgency_immediate_for_very_high_aqi():
    assert _score_urgency(0.85, None, None) == "immediate"


def test_urgency_within_4h_for_moderate_high_flood():
    assert _score_urgency(None, 0.72, None) == "within_4h"


def test_urgency_within_24h_for_low_heat():
    assert _score_urgency(None, None, 0.62) == "within_24h"


def test_urgency_plan_for_all_below_threshold():
    assert _score_urgency(0.20, 0.20, 0.20) == "plan"


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_packets_sorted_immediate_first():
    rows = [
        _ward("w01", "Ward 1", aqi=0.45),           # within_24h
        _ward("w02", "Ward 2", aqi=0.85),           # immediate
        _ward("w03", "Ward 3", flood=0.72),          # within_4h
    ]
    result = _make_result(rows, domains=["air", "flood"])
    packets = generate_ward_decisions(result)
    urgencies = [p["urgency"] for p in packets]
    order = {"immediate": 0, "within_4h": 1, "within_24h": 2, "plan": 3}
    assert urgencies == sorted(urgencies, key=lambda u: order.get(u, 4))


# ── Packet ID stability ───────────────────────────────────────────────────────

def test_packet_id_is_stable():
    pid1 = _packet_id("ward_01", "air", "2026-05-07T06:00")
    pid2 = _packet_id("ward_01", "air", "2026-05-07T06:00")
    assert pid1 == pid2


def test_packet_id_differs_by_domain():
    pid_air   = _packet_id("ward_01", "air",   "2026-05-07T06:00")
    pid_flood = _packet_id("ward_01", "flood", "2026-05-07T06:00")
    assert pid_air != pid_flood


# ── decisions_to_dataframe ────────────────────────────────────────────────────

def test_decisions_to_dataframe_empty():
    df = decisions_to_dataframe([])
    assert df.empty


def test_decisions_to_dataframe_columns():
    result = _make_result([_ward(aqi=0.65, flood=0.72, composite=0.68)])
    packets = generate_ward_decisions(result)
    df = decisions_to_dataframe(packets)
    expected = {"urgency", "domain", "decision_id", "ward_name", "likely_cause",
                "recommended_action", "escalation_required", "status"}
    assert expected.issubset(set(df.columns))


def test_decisions_to_dataframe_row_count_matches_packets():
    result = _make_result([_ward(aqi=0.65, flood=0.72, composite=0.68)])
    packets = generate_ward_decisions(result)
    df = decisions_to_dataframe(packets)
    assert len(df) == len(packets)
