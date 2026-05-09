"""
Air Quality SDK Walkthrough
============================

A read-only tour of the air quality use case using the AirOS SDK
(urban_platform.sdk) and the air quality pipeline public surface.

Run from repo root:
    python examples/sdk/air_quality_walkthrough.py
"""

from __future__ import annotations

import os
import sys

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import pandas as pd

import urban_platform.sdk as sdk
from urban_platform.applications.air.air_pipeline import (
    build_h3_grid_from_bbox,
    build_air_quality_dashboard,
    build_air_quality_decision_packets,
)


# ── 1. Platform inventory ─────────────────────────────────────────────────

print("\n=== 1. Platform inventory ===")
app_ids = sdk.list_app_ids()
print("App IDs:", app_ids)
assert "air_quality_review" in app_ids, "air_quality_review not registered"

contract_keys = sdk.list_contract_keys()
print("Contract keys include:")
for k in contract_keys:
    if "air_quality" in k or "aqi" in k:
        print(f"  {k}")
assert "consumer_air_quality_dashboard" in contract_keys
assert "consumer_air_quality_decision_packet" in contract_keys


# ── 2. App descriptor & safety gates ─────────────────────────────────────

print("\n=== 2. App descriptor & safety gates ===")
descriptor = sdk.get_app_descriptor("air_quality_review")
safety = descriptor["safety"]
print("review_support_only:   ", safety["review_support_only"])
print("human_review_required: ", safety["human_review_required"])
print("blocked_uses:          ", safety["blocked_uses"])

assert safety["review_support_only"] is True
assert safety["human_review_required"] is True
assert len(safety["blocked_uses"]) > 0


# ── 3. Consumer contract schemas ─────────────────────────────────────────

print("\n=== 3. Consumer contract schemas ===")
dashboard_schema = sdk.get_contract_schema("consumer_air_quality_dashboard")
print("Dashboard required fields:", dashboard_schema.get("required"))
assert "generated_at" in dashboard_schema.get("required", [])
assert "risk_summary" in dashboard_schema.get("required", [])
assert "provenance_summary" in dashboard_schema.get("required", [])

packet_schema = sdk.get_contract_schema("consumer_air_quality_decision_packet")
print("Decision packet required fields:", packet_schema.get("required"))
assert "packet_id" in packet_schema.get("required", [])
assert "safety_gates" in packet_schema.get("required", [])
assert "field_verification_required" in packet_schema.get("required", [])


# ── 4. Synthetic AQ observations ──────────────────────────────────────────

print("\n=== 4. Synthetic AQ observations (offline demo) ===")

# Build a synthetic 3×3 grid of AQ observations — same structure
# as fetch_air_quality_observations() returns for live OpenMeteo data.
BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
lats = [BBOX["lat_min"], (BBOX["lat_min"] + BBOX["lat_max"]) / 2, BBOX["lat_max"]]
lons = [BBOX["lon_min"], (BBOX["lon_min"] + BBOX["lon_max"]) / 2, BBOX["lon_max"]]
pm25_vals = [
    [145.0, 95.0, 65.0],
    [110.0, 75.0, 45.0],
    [80.0,  50.0, 25.0],
]
aq_rows = []
for i, lat in enumerate(lats):
    for j, lon in enumerate(lons):
        pm25 = pm25_vals[i][j]
        aq_rows.append({
            "station_id": f"demo_{lat:.3f}_{lon:.3f}",
            "latitude": lat, "longitude": lon,
            "timestamp": "2026-05-07T06:00:00Z",
            "pm25_ugm3": pm25,
            "pm10_ugm3": round(pm25 * 1.6, 1),
            "european_aqi": None,
            "data_source": "openmeteo_aq", "quality_flag": "real",
        })
aq_df = pd.DataFrame(aq_rows)
print(f"AQ observations: {len(aq_df)} records (3×3 grid)")
print("Columns:", list(aq_df.columns))
assert len(aq_df) == 9


# ── 5. H3 grid ────────────────────────────────────────────────────────────

print("\n=== 5. H3 grid from bbox ===")
h3_grid = build_h3_grid_from_bbox(**BBOX, h3_resolution=9)
print(f"H3 grid (res=9): {len(h3_grid)} cells")
assert len(h3_grid) > 100, "Expected >100 H3 cells at resolution 9"
assert set(h3_grid.columns) >= {"h3_id", "centroid_lat", "centroid_lon"}


# ── 6. AQ dashboard ───────────────────────────────────────────────────────

print("\n=== 6. Air quality dashboard ===")
dashboard = build_air_quality_dashboard(
    aq_df=aq_df,
    h3_resolution=9,
    city_id="bangalore_demo",
    **BBOX,
)
print("city_id:                ", dashboard["city_id"])
print("data_quality_flag:      ", dashboard["data_quality_flag"])
print("overall_aqi_category:   ", dashboard["risk_summary"]["overall_aqi_category"])
print("headline:               ", dashboard["risk_summary"]["headline"])
print("active_warnings:        ", len(dashboard["active_warnings"]), "warning(s)")
print("risk_cells:             ", len(dashboard["risk_cells"]), "cells")
print("poor+ cells:            ",
      sum(1 for c in dashboard["risk_cells"] if c["aqi_category"] in ("poor", "very_poor", "severe")))

assert dashboard["city_id"] == "bangalore_demo"
assert dashboard["data_quality_flag"] == "real"
assert dashboard["risk_summary"]["overall_aqi_category"] in (
    "good", "satisfactory", "moderate", "poor", "very_poor", "severe"
)
assert len(dashboard["risk_areas"]) >= 1
assert len(dashboard["active_warnings"]) >= 1
assert dashboard["provenance_summary"]["sources"]


# ── 7. Decision packets ───────────────────────────────────────────────────

print("\n=== 7. Decision packets (top-5 highest AQI cells) ===")
packets = build_air_quality_decision_packets(
    aq_df=aq_df,
    h3_resolution=9,
    city_id="bangalore_demo",
    **BBOX,
    top_n=5,
)
print(f"Decision packets: {len(packets)}")
for p in packets[:3]:
    print(f"  packet={p['packet_id']}  h3={p['h3_id'][:14]}  "
          f"aqi={p['aqi_assessment']['aqi_category']}  "
          f"rec_allowed={p['confidence']['recommendation_allowed']}")

assert len(packets) > 0
assert all(p["domain_id"] == "air_quality" for p in packets)
assert all(p["confidence"]["recommendation_allowed"] is False for p in packets)
assert all(p["field_verification_required"] is True for p in packets)
assert all(len(p["safety_gates"]) >= 1 for p in packets)


# ── 8. Safety gate conformance ────────────────────────────────────────────

print("\n=== 8. Safety gate conformance ===")
print("recommendation_allowed is always False:", all(
    p["confidence"]["recommendation_allowed"] is False for p in packets
))
print("field_verification_required is always True:", all(
    p["field_verification_required"] is True for p in packets
))
print("All packets have safety_gates:", all(
    len(p["safety_gates"]) >= 1 for p in packets
))
print("All packets have blocked_uses:", all(
    len(p["blocked_uses"]) >= 1 for p in packets
))

# Unavailable AQ data → data_quality_flag="unavailable"
empty_aq = pd.DataFrame(columns=[
    "station_id", "latitude", "longitude", "timestamp",
    "pm25_ugm3", "pm10_ugm3", "european_aqi",
    "data_source", "quality_flag",
])
d_empty = build_air_quality_dashboard(
    aq_df=empty_aq,
    h3_resolution=9, city_id="test", **BBOX,
)
assert d_empty["data_quality_flag"] == "unavailable", (
    f"Expected 'unavailable', got '{d_empty['data_quality_flag']}'"
)
print("Empty AQ data → data_quality_flag='unavailable' ✓")


print("\n=== Walkthrough complete ===")
