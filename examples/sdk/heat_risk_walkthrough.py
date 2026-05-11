"""
Urban Heat Risk SDK Walkthrough — read-only demo.

Demonstrates the urban heat risk use case using only airos.os.sdk public
surface. No store writes; safe to run offline.

Run from repo root:
    python examples/sdk/heat_risk_walkthrough.py
"""

from __future__ import annotations

import json
import os
import sys

# Ensure repo root is on sys.path when running this file directly.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import pandas as pd

import airos.os.sdk as sdk
from airos.apps.heat.heat_pipeline import (
    build_h3_grid_from_bbox,
    build_heat_risk_dashboard,
    build_intervention_candidates,
)
from airos.drivers.connectors.heat.openmeteo import fetch_temperature_observations
from airos.drivers.connectors.heat.osm_green_cover import compute_green_cover

# ── 1. Inventory ──────────────────────────────────────────────────────────

def section_inventory() -> None:
    print("\n=== 1. Platform inventory ===")
    app_ids = sdk.list_app_ids()
    assert "urban_heat_risk_review" in app_ids, "urban_heat_risk_review not in inventory"
    print(f"  Apps registered: {app_ids}")

    contract_keys = sdk.list_contract_keys()
    heat_keys = [k for k in contract_keys if "heat" in k]
    print(f"  Heat contract keys: {heat_keys}")
    assert "heat_risk_dashboard" in heat_keys
    assert "heat_intervention_candidates" in heat_keys


# ── 2. App descriptor & safety gates ─────────────────────────────────────

def section_app_descriptor() -> dict:
    print("\n=== 2. App descriptor & safety gates ===")
    descriptor = sdk.get_app_descriptor("urban_heat_risk_review")
    safety = descriptor.get("safety", {})
    print(f"  review_support_only: {safety.get('review_support_only')}")
    print(f"  human_review_required: {safety.get('human_review_required')}")
    print(f"  blocked_uses: {safety.get('blocked_uses', [])}")

    assert safety.get("review_support_only") is True, "Expected review_support_only=true"
    assert safety.get("human_review_required") is True, "Expected human_review_required=true"
    assert len(safety.get("blocked_uses", [])) > 0, "Expected non-empty blocked_uses"
    return descriptor


# ── 3. Contract schemas ───────────────────────────────────────────────────

def section_contracts() -> None:
    print("\n=== 3. Consumer contract schemas ===")
    for key in ("heat_risk_dashboard", "heat_intervention_candidates"):
        schema = sdk.get_contract_schema(key)
        required = schema.get("required", [])
        print(f"  {key}: required={required}")
        assert len(required) > 0, f"Schema {key} has no required fields"


# ── 4. Synthetic pipeline outputs ────────────────────────────────────────

def _synthetic_temperature_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "station_id": "synthetic_12.87_77.49",
            "latitude": 12.87, "longitude": 77.49,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 28.0,
            "apparent_temperature_c": 30.0,
            "relative_humidity_pct": 72.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
        {
            "station_id": "synthetic_12.97_77.59",
            "latitude": 12.97, "longitude": 77.59,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 32.5,
            "apparent_temperature_c": 36.0,
            "relative_humidity_pct": 60.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
        {
            "station_id": "synthetic_13.07_77.69",
            "latitude": 13.07, "longitude": 77.69,
            "timestamp": "2026-05-07T06:00:00Z",
            "temperature_c": 27.0,
            "apparent_temperature_c": 29.0,
            "relative_humidity_pct": 82.0,
            "data_source": "openmeteo",
            "quality_flag": "real",
        },
    ])


def section_pipeline_outputs() -> tuple[dict, dict]:
    print("\n=== 4. Pipeline outputs ===")
    bbox = dict(lat_min=12.87, lon_min=77.49, lat_max=13.07, lon_max=77.69)
    h3_res = 9
    city_id = "bangalore_demo"

    temp_df = _synthetic_temperature_df()
    green_df = pd.DataFrame()  # empty — no OSM call in offline demo

    dashboard = build_heat_risk_dashboard(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=h3_res,
        city_id=city_id,
        **bbox,
    )
    candidates = build_intervention_candidates(
        temperature_df=temp_df,
        green_cover_df=green_df,
        h3_resolution=h3_res,
        city_id=city_id,
        **bbox,
    )

    print(f"  Dashboard cells: {len(dashboard['heat_cells'])}")
    print(f"  Max heat risk score: {dashboard['summary']['max_heat_risk_score']}")
    print(f"  Data quality flag: {dashboard['data_quality_flag']}")
    print(f"  Intervention candidates: {len(candidates['candidates'])}")

    if candidates["candidates"]:
        top = candidates["candidates"][0]
        print(f"  Top candidate h3_id: {top['h3_id']}, risk_score: {top['risk_score']}")

    return dashboard, candidates


# ── 5. Validate against SDK schemas ──────────────────────────────────────

def section_validate(dashboard: dict, candidates: dict) -> None:
    print("\n=== 5. SDK schema validation ===")
    dashboard_schema = sdk.get_contract_schema("heat_risk_dashboard")
    candidates_schema = sdk.get_contract_schema("heat_intervention_candidates")

    for field in dashboard_schema.get("required", []):
        assert field in dashboard, f"Dashboard missing required field: {field}"
    print("  heat_risk_dashboard: all required fields present")

    for field in candidates_schema.get("required", []):
        assert field in candidates, f"Candidates missing required field: {field}"
    print("  heat_intervention_candidates: all required fields present")


# ── 6. Intervention candidates & suggestions ─────────────────────────────

def section_intervention_candidates(candidates: dict) -> None:
    print("\n=== 6. Intervention candidates ===")
    cands = candidates["candidates"]
    assert len(cands) <= 10, "Expected at most 10 candidates"
    scores = [c["risk_score"] for c in cands]
    assert scores == sorted(scores, reverse=True), "Candidates not sorted by risk_score desc"
    print(f"  {len(cands)} candidates, sorted by risk_score descending")
    for c in cands[:3]:
        print(f"    h3={c['h3_id'][:12]}…  risk={c['risk_score']:.3f}  "
              f"green_deficit={c['green_deficit']:.3f}  "
              f"interventions={c.get('suggested_interventions', [])}")


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("Urban Heat Risk SDK Walkthrough")
    print("=" * 40)
    section_inventory()
    section_app_descriptor()
    section_contracts()
    dashboard, candidates = section_pipeline_outputs()
    section_validate(dashboard, candidates)
    section_intervention_candidates(candidates)
    print("\nWalkthrough complete. All assertions passed.")


if __name__ == "__main__":
    main()
