"""
Flood Risk SDK Walkthrough
==========================

A read-only tour of the flood risk use case using the AirOS SDK
(urban_platform.sdk) and the flood pipeline public surface.

Run from repo root:
    python examples/sdk/flood_risk_walkthrough.py
"""

from __future__ import annotations

import os
import sys

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import pandas as pd

import urban_platform.sdk as sdk
from urban_platform.applications.flood.flood_pipeline import (
    build_h3_grid_from_bbox,
    build_flood_risk_dashboard,
    build_flood_decision_packets,
)


# ── 1. Platform inventory ─────────────────────────────────────────────────

print("\n=== 1. Platform inventory ===")
app_ids = sdk.list_app_ids()
print("App IDs:", app_ids)
assert "flood_risk_review" in app_ids, "flood_risk_review not registered"

contract_keys = sdk.list_contract_keys()
print("Contract keys include:")
for k in contract_keys:
    if "flood" in k or "rainfall" in k or "field" in k or "drainage" in k or "incident" in k:
        print(f"  {k}")
assert "consumer_flood_risk_dashboard" in contract_keys
assert "consumer_flood_decision_packet" in contract_keys
assert "consumer_field_verification_task" in contract_keys


# ── 2. App descriptor & safety gates ─────────────────────────────────────

print("\n=== 2. App descriptor & safety gates ===")
descriptor = sdk.get_app_descriptor("flood_risk_review")
safety = descriptor["safety"]
print("review_support_only:   ", safety["review_support_only"])
print("human_review_required: ", safety["human_review_required"])
print("blocked_uses:          ", safety["blocked_uses"])

assert safety["review_support_only"] is True
assert safety["human_review_required"] is True
assert len(safety["blocked_uses"]) > 0


# ── 3. Consumer contract schemas ─────────────────────────────────────────

print("\n=== 3. Consumer contract schemas ===")
dashboard_schema = sdk.get_contract_schema("consumer_flood_risk_dashboard")
print("Dashboard required fields:", dashboard_schema.get("required"))
assert "generated_at" in dashboard_schema.get("required", [])
assert "risk_summary" in dashboard_schema.get("required", [])
assert "provenance_summary" in dashboard_schema.get("required", [])

packet_schema = sdk.get_contract_schema("consumer_flood_decision_packet")
print("Decision packet required fields:", packet_schema.get("required"))
assert "packet_id" in packet_schema.get("required", [])
assert "safety_gates" in packet_schema.get("required", [])
assert "field_verification_required" in packet_schema.get("required", [])


# ── 4. Connector — rainfall observations ──────────────────────────────────

print("\n=== 4. Synthetic rainfall observations (offline demo) ===")

# Build a synthetic 3×3 grid of rainfall observations — same structure
# as fetch_rainfall_observations() returns for live OpenMeteo data.
BBOX = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
lats = [BBOX["lat_min"], (BBOX["lat_min"] + BBOX["lat_max"]) / 2, BBOX["lat_max"]]
lons = [BBOX["lon_min"], (BBOX["lon_min"] + BBOX["lon_max"]) / 2, BBOX["lon_max"]]
intensities = [
    [1.0, 3.0, 8.0],
    [2.0, 6.0, 18.0],
    [0.5, 12.0, 35.0],
]
rain_rows = []
for i, lat in enumerate(lats):
    for j, lon in enumerate(lons):
        r = intensities[i][j]
        rain_rows.append({
            "station_id": f"demo_{lat:.3f}_{lon:.3f}",
            "latitude": lat, "longitude": lon,
            "timestamp": "2026-05-07T06:00:00Z",
            "rainfall_intensity_mm_per_hr": r,
            "rainfall_accumulation_3h_mm": round(r * 3, 1),
            "data_source": "openmeteo", "quality_flag": "real",
        })
rainfall_df = pd.DataFrame(rain_rows)
print(f"Rainfall observations: {len(rainfall_df)} records (3×3 grid)")
print("Columns:", list(rainfall_df.columns))
assert len(rainfall_df) == 9

# Synthetic incidents
incidents_df = pd.DataFrame([
    {"latitude": 13.06, "longitude": 77.67, "severity": "high",
     "incident_type": "waterlogging", "quality_flag": "unverified"},
    {"latitude": 12.97, "longitude": 77.65, "severity": "moderate",
     "incident_type": "waterlogging", "quality_flag": "unverified"},
])
print(f"Incidents: {len(incidents_df)} records")

# No drainage assets (empty DataFrame is valid)
assets_df = pd.DataFrame()


# ── 5. H3 grid ────────────────────────────────────────────────────────────

print("\n=== 5. H3 grid from bbox ===")
h3_grid = build_h3_grid_from_bbox(**BBOX, h3_resolution=9)
print(f"H3 grid (res=9): {len(h3_grid)} cells")
assert len(h3_grid) > 100, "Expected >100 H3 cells at resolution 9"
assert set(h3_grid.columns) >= {"h3_id", "centroid_lat", "centroid_lon"}


# ── 6. Pipeline outputs ───────────────────────────────────────────────────

print("\n=== 6. Flood risk dashboard ===")
dashboard = build_flood_risk_dashboard(
    rainfall_df=rainfall_df,
    incidents_df=incidents_df,
    assets_df=assets_df,
    h3_resolution=9,
    city_id="bangalore_demo",
    **BBOX,
)
print("city_id:           ", dashboard["city_id"])
print("data_quality_flag: ", dashboard["data_quality_flag"])
print("overall_risk_level:", dashboard["risk_summary"]["overall_risk_level"])
print("headline:          ", dashboard["risk_summary"]["headline"])
print("active_warnings:   ", len(dashboard["active_warnings"]), "warning(s)")
print("risk_cells:        ", len(dashboard["risk_cells"]), "cells")
print("high/severe cells: ",
      sum(1 for c in dashboard["risk_cells"] if c["risk_level"] in ("high", "severe")))

assert dashboard["city_id"] == "bangalore_demo"
assert dashboard["data_quality_flag"] == "real"
assert dashboard["risk_summary"]["overall_risk_level"] in ("low", "moderate", "high", "severe")
assert len(dashboard["risk_areas"]) >= 1
assert len(dashboard["active_warnings"]) >= 1
assert dashboard["provenance_summary"]["sources"]


# ── 7. Decision packets ───────────────────────────────────────────────────

print("\n=== 7. Decision packets (top-5 high-risk cells) ===")
packets = build_flood_decision_packets(
    rainfall_df=rainfall_df,
    incidents_df=incidents_df,
    assets_df=assets_df,
    h3_resolution=9,
    city_id="bangalore_demo",
    **BBOX,
    top_n=5,
)
print(f"Decision packets: {len(packets)}")
for p in packets[:3]:
    print(f"  packet={p['packet_id']}  h3={p['h3_id'][:14]}  "
          f"risk={p['risk_assessment']['risk_level']}  "
          f"rec_allowed={p['confidence']['recommendation_allowed']}")

assert len(packets) > 0
assert all(p["domain_id"] == "flood_risk" for p in packets)
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

# Unavailable rainfall → data_quality_flag="unavailable"
empty_rain = pd.DataFrame(columns=[
    "station_id", "latitude", "longitude", "timestamp",
    "rainfall_intensity_mm_per_hr", "rainfall_accumulation_3h_mm",
    "data_source", "quality_flag",
])
d_empty = build_flood_risk_dashboard(
    rainfall_df=empty_rain, incidents_df=pd.DataFrame(), assets_df=pd.DataFrame(),
    h3_resolution=9, city_id="test", **BBOX,
)
assert d_empty["data_quality_flag"] == "unavailable", (
    f"Expected 'unavailable', got '{d_empty['data_quality_flag']}'"
)
print("Empty rainfall → data_quality_flag='unavailable' ✓")


print("\n=== Walkthrough complete ===")
