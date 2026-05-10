"""Batch ingestor — pulls data from all domain pipelines and writes to the H3 Knowledge Store.

Run manually:
    python -m urban_platform.h3_knowledge.ingestor
    python -m urban_platform.h3_knowledge.ingestor --cities bangalore --domains air,water
    python -m urban_platform.h3_knowledge.ingestor --force   # ignore watermarks, re-ingest all

Wire into main.py:
    python main.py --step ingest-h3

Typical schedule (cron / systemd timer):
    air, fire, heat   → every 15 min  (near-real-time sensors)
    water, flood      → every 1 hour  (satellite revisit ~daily, but rain gauges hourly)
    construction,
    green, noise      → every 6 hours (satellite-derived, changes slowly)
    waste             → every 1 hour
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from urban_platform.h3_knowledge.writer import (
    ingest_assessment_cells,
    write_packet,
    record_ingest,
    get_last_ingest,
    _apply_analysis_gate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City bounding boxes — same as panels use
# ---------------------------------------------------------------------------
_CITY_BBOXES: dict[str, dict] = {
    "bangalore":  {"lat_min": 12.834, "lon_min": 77.461, "lat_max": 13.139, "lon_max": 77.784},
    "hyderabad":  {"lat_min": 17.287, "lon_min": 78.270, "lat_max": 17.556, "lon_max": 78.622},
    "mumbai":     {"lat_min": 18.890, "lon_min": 72.776, "lat_max": 19.272, "lon_max": 72.987},
    "delhi":      {"lat_min": 28.404, "lon_min": 76.838, "lat_max": 28.883, "lon_max": 77.347},
    "chennai":    {"lat_min": 12.878, "lon_min": 80.179, "lat_max": 13.223, "lon_max": 80.332},
    "pune":       {"lat_min": 18.421, "lon_min": 73.735, "lat_max": 18.631, "lon_max": 73.982},
}

ALL_CITIES  = list(_CITY_BBOXES.keys())
ALL_DOMAINS = [
    "air", "fire", "heat", "flood", "water", "waste", "construction", "green", "noise", "weather",
    # Urban infrastructure — OSM-derived structural context (weekly cadence)
    "buildings", "roads", "drains", "crowd",
]

# Siting is computed separately from regular domain ingest — monthly cadence.
# Use run_siting_batch() directly rather than including "siting" in ALL_DOMAINS,
# so it doesn't accidentally run on every scheduler sweep.
SITING_PERIOD_DAYS    = 90   # use 3 months of assessment data
SITING_INTERVAL_DAYS  = 30   # recompute at most once per month

# How often each domain should be re-ingested (minimum gap between runs)
_DOMAIN_INTERVAL: dict[str, timedelta] = {
    "air":          timedelta(minutes=15),
    "fire":         timedelta(minutes=15),
    "heat":         timedelta(minutes=30),
    "weather":      timedelta(minutes=15),   # Open-Meteo forecast updates hourly
    "flood":        timedelta(hours=1),
    "water":        timedelta(hours=1),
    "waste":        timedelta(hours=1),
    "construction": timedelta(hours=6),
    "green":        timedelta(hours=6),
    "noise":        timedelta(hours=6),
    # Urban infrastructure — OSM structural data changes quarterly at most
    "buildings":    timedelta(days=90),
    "roads":        timedelta(days=90),
    "drains":       timedelta(days=90),
    # Crowd: real-time camera feed — 15-min cadence to catch events/gatherings
    "crowd":        timedelta(minutes=15),
}

DEFAULT_H3_RES = 8


# ---------------------------------------------------------------------------
# Per-domain ingest functions
# ---------------------------------------------------------------------------

def _ingest_air(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("air", city_id, force)
    from urban_platform.applications.air.air_pipeline import (
        run_air_quality_pipeline, build_air_quality_decision_packets,
        _aqi_category,
    )
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    from urban_platform.h3_knowledge.coverage import coverage_signals
    from review_dashboard.data_cache import load_live_aq

    try:
        aq_df = load_live_aq(
            city_id,
            bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
            lookback_hours=2,
        )
    except Exception:
        aq_df = None
    if aq_df is None or aq_df.empty:
        logger.info("[%s/air] No live data available — skipping.", city_id)
        record_ingest(city_id=city_id, domain="air", rows_written=0, status="partial",
                      error_msg="no live AQ data")
        return 0

    # Use run_air_quality_pipeline directly — gets the full DataFrame including
    # nearest_obs_km, centroid_lat/lon that build_air_quality_dashboard strips out.
    pipeline = run_air_quality_pipeline(
        aq_df, DEFAULT_H3_RES, city_id,
        bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
    )
    risk_cells_df = pipeline["risk_cells"]

    packets = build_air_quality_decision_packets(
        aq_df=aq_df, h3_resolution=DEFAULT_H3_RES, city_id=city_id, **bbox, top_n=20,
    )

    # AQI category → canonical risk_level
    # Keys are normalised (lower-case, spaces → underscores) because the CPCB
    # API returns mixed-case strings like "Very Poor" or "Satisfactory".
    # "good"/"satisfactory" → "low" (not "good") so the map SQL CASE statement
    # scores them as 1 rather than 0/unknown.
    _cat_to_risk = {
        "severe":       "severe",
        "very_poor":    "high",
        "verypoor":     "high",
        "poor":         "high",
        "moderate":     "moderate",
        "satisfactory": "low",
        "good":         "low",
    }

    def _cat_lookup(raw_cat) -> str:
        """Normalise AQI category string then map to canonical risk level."""
        norm = str(raw_cat or "").lower().strip().replace(" ", "_").replace("-", "_")
        # Also try without underscores for "verypoor" style
        return _cat_to_risk.get(norm) or _cat_to_risk.get(norm.replace("_", "")) or "moderate"

    signal_rows: list[dict] = []
    for _, cell in risk_cells_df.iterrows():
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        clat = cell.get("centroid_lat")
        clon = cell.get("centroid_lon")
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES,
                        centroid_lat=clat, centroid_lon=clon)

        pm25 = cell.get("pm25_ugm3")
        aqi_score = cell.get("aqi_score")
        cat = cell.get("aqi_category", "good")
        risk = _cat_lookup(cat)

        if pm25 is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "PM25",
                                 "value": pm25, "unit": "µg/m³"})
        if aqi_score is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "AQI",
                                 "value": aqi_score, "unit": "index"})

        # Coverage uncertainty — distance-derived per cell
        nearest_km = cell.get("nearest_obs_km")
        signal_rows.extend(coverage_signals(h3_id, nearest_km, "air"))

        write_assessment(h3_id=h3_id, city_id=city_id, domain="air",
                         risk_level=risk,
                         primary_index="AQI", primary_value=aqi_score,
                         dominant_issue=cat, summary=cell.to_dict())

        # Analysis gate: only queue when data is reliable and risk band changed
        from urban_platform.h3_knowledge.coverage import distance_to_confidence, DOMAIN_DEFAULT_CONFIDENCE
        nearest_km_for_gate = cell.get("nearest_obs_km")
        dc_for_gate = (distance_to_confidence(nearest_km_for_gate)
                       if nearest_km_for_gate is not None
                       else DOMAIN_DEFAULT_CONFIDENCE.get("air", 0.5))
        _apply_analysis_gate(
            h3_id=h3_id, city_id=city_id, domain="air",
            new_risk_level=risk, data_confidence=dc_for_gate,
            centroid_lat=clat, centroid_lng=clon,
        )

    written = write_signals(signal_rows, city_id=city_id, domain="air", source="cpcb")
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""),
                     h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="air",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="air", rows_written=written)
    return written


def _ingest_water(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("water", city_id, force)
    from review_dashboard.data_cache import load_water_quality
    from urban_platform.applications.water.water_pipeline import (
        build_water_dashboard, build_water_decision_packets,
    )
    cells_dict = load_water_quality(
        bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], DEFAULT_H3_RES,
    )
    if not cells_dict:
        logger.info("[%s/water] No live GEE data — skipping.", city_id)
        record_ingest(city_id=city_id, domain="water", rows_written=0, status="partial",
                      error_msg="no live GEE water data")
        return 0
    cell_list = [{"h3_id": k, **v} for k, v in cells_dict.items()]
    # Alias: internal pipeline uses "water_quality_index"; DB stores the
    # more accurate name "optical_water_clarity_index" to reflect that this
    # is a Sentinel-2 optical proxy, not a regulatory WQI.
    for cell in cell_list:
        if "optical_water_clarity_index" not in cell:
            cell["optical_water_clarity_index"] = cell.get("water_quality_index")
    written = ingest_assessment_cells(cell_list, city_id=city_id, domain="water",
                                      signal_key="optical_water_clarity_index", risk_key="risk_level",
                                      issue_key="dominant_issue", unit="index", source="gee")
    packets = build_water_decision_packets(
        cells_dict, DEFAULT_H3_RES, city_id, **bbox,
    )
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="water", risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="water", rows_written=written)
    return written


def _ingest_construction(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("construction", city_id, force)
    from review_dashboard.data_cache import load_construction_signals
    from urban_platform.applications.construction.construction_pipeline import (
        build_construction_decision_packets,
    )
    cells_dict = load_construction_signals(
        bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], DEFAULT_H3_RES,
    )
    if not cells_dict:
        logger.info("[%s/construction] No live data — skipping.", city_id)
        record_ingest(city_id=city_id, domain="construction", rows_written=0, status="partial",
                      error_msg="no live GEE construction data")
        return 0
    cell_list = [{"h3_id": k, **v} for k, v in cells_dict.items()]
    written = ingest_assessment_cells(cell_list, city_id=city_id, domain="construction",
                                      signal_key="construction_risk_index", risk_key="risk_level",
                                      issue_key="dominant_issue", unit="index", source="gee")
    packets = build_construction_decision_packets(cells_dict, DEFAULT_H3_RES, city_id, **bbox)
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="construction",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="construction", rows_written=written)
    return written


def _ingest_green(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("green", city_id, force)
    from review_dashboard.data_cache import load_green_cover
    from urban_platform.applications.green.green_pipeline import build_green_decision_packets
    cells_dict = load_green_cover(
        bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], DEFAULT_H3_RES,
    )
    if not cells_dict:
        logger.info("[%s/green] No live data — skipping.", city_id)
        record_ingest(city_id=city_id, domain="green", rows_written=0, status="partial",
                      error_msg="no live GEE green data")
        return 0
    cell_list = [{"h3_id": k, **v} for k, v in cells_dict.items()]
    written = ingest_assessment_cells(cell_list, city_id=city_id, domain="green",
                                      signal_key="green_cover_change_index", risk_key="risk_level",
                                      unit="index", source="gee")
    packets = build_green_decision_packets(cells_dict, DEFAULT_H3_RES, city_id, **bbox)
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="green",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="green", rows_written=written)
    return written


def _ingest_noise(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("noise", city_id, force)
    from review_dashboard.data_cache import h3_grid_for_bbox, load_construction_signals
    from urban_platform.applications.noise.noise_pipeline import (
        build_noise_risk, build_noise_decision_packets,
    )
    import pandas as pd
    h3_ids = h3_grid_for_bbox(bbox["lat_min"], bbox["lon_min"],
                               bbox["lat_max"], bbox["lon_max"], DEFAULT_H3_RES)
    construction_cells = load_construction_signals(
        bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], DEFAULT_H3_RES,
    ) or {}
    noise_cells = build_noise_risk(h3_ids, city_id, construction_cells, pd.DataFrame(),
                                   bbox["lat_min"], bbox["lon_min"],
                                   bbox["lat_max"], bbox["lon_max"])
    if not noise_cells:
        logger.info("[%s/noise] Proximity model yielded no cells.", city_id)
        record_ingest(city_id=city_id, domain="noise", rows_written=0, status="partial")
        return 0
    cell_list = [{"h3_id": k, **v} for k, v in noise_cells.items()]
    written = ingest_assessment_cells(cell_list, city_id=city_id, domain="noise",
                                      signal_key="noise_risk_index", risk_key="risk_level",
                                      issue_key="dominant_source", unit="index",
                                      source="proximity_model")
    packets = build_noise_decision_packets(noise_cells, DEFAULT_H3_RES, city_id, **bbox)
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="noise",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="noise", rows_written=written)
    return written


def _ingest_fire(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("fire", city_id, force)
    from review_dashboard.data_cache import load_firms
    from urban_platform.applications.fire.fire_pipeline import (
        build_fire_dashboard, build_fire_decision_packets,
    )
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    fire_df = load_firms(bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], 2)
    if fire_df is None or (hasattr(fire_df, "empty") and fire_df.empty):
        logger.info("[%s/fire] No live FIRMS data — skipping.", city_id)
        record_ingest(city_id=city_id, domain="fire", rows_written=0, status="partial",
                      error_msg="no live FIRMS data")
        return 0
    dashboard = build_fire_dashboard(fire_df=fire_df, h3_resolution=DEFAULT_H3_RES,
                                     city_id=city_id, **bbox)
    packets   = build_fire_decision_packets(fire_df=fire_df, h3_resolution=DEFAULT_H3_RES,
                                            city_id=city_id, **bbox, top_n=20)
    from urban_platform.h3_knowledge.coverage import coverage_signals
    signal_rows = []
    for cell in dashboard.get("risk_cells", []):
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        frp = cell.get("max_frp_mw") or cell.get("frp")
        if frp is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "FRP", "value": frp, "unit": "MW"})
        # Fire: direct satellite observation — nearest_obs_km=0 → confidence=1.0
        signal_rows.extend(coverage_signals(h3_id, 0.0, "fire"))
        fire_risk = cell.get("risk_level", "unknown")
        write_assessment(h3_id=h3_id, city_id=city_id, domain="fire",
                         risk_level=fire_risk,
                         primary_index="FRP", primary_value=frp, summary=cell)
        # Analysis gate: fire always has confidence=1.0 (direct observation)
        _apply_analysis_gate(
            h3_id=h3_id, city_id=city_id, domain="fire",
            new_risk_level=fire_risk, data_confidence=1.0,
        )
    written = write_signals(signal_rows, city_id=city_id, domain="fire", source="firms")
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="fire",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="fire", rows_written=written)
    return written


def _ingest_flood(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("flood", city_id, force)
    from urban_platform.applications.flood.flood_pipeline import (
        build_flood_risk_dashboard, build_flood_decision_packets,
    )
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    from review_dashboard.components.flood_panel import (
        _synthetic_rainfall, _synthetic_incidents, _synthetic_assets,
    )
    import pandas as pd
    try:
        from review_dashboard.data_cache import load_live_rainfall
        rainfall_df = load_live_rainfall(
            city_id,
            bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"],
            lookback_hours=2,
        )
    except Exception:
        rainfall_df = pd.DataFrame()
    if rainfall_df is None or rainfall_df.empty:
        rainfall_df = _synthetic_rainfall(bbox)
    try:
        dashboard = build_flood_risk_dashboard(
            rainfall_df=rainfall_df,
            incidents_df=_synthetic_incidents(bbox),
            assets_df=_synthetic_assets(bbox),
            h3_resolution=DEFAULT_H3_RES,
            city_id=city_id, **bbox,
        )
        packets = build_flood_decision_packets(
            rainfall_df=rainfall_df,
            incidents_df=_synthetic_incidents(bbox),
            assets_df=_synthetic_assets(bbox),
            h3_resolution=DEFAULT_H3_RES,
            city_id=city_id, **bbox, top_n=20,
        )
    except Exception as exc:
        logger.warning("[%s/flood] pipeline error: %s", city_id, exc)
        record_ingest(city_id=city_id, domain="flood", rows_written=0, status="error",
                      error_msg=str(exc))
        return 0
    from urban_platform.h3_knowledge.coverage import coverage_signals
    signal_rows = []
    for cell in dashboard.get("risk_cells", []):
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        score = cell.get("flood_risk_score")
        rain  = cell.get("rainfall_mm_per_hr")
        if score is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "FLOOD_RISK_SCORE",
                                 "value": score, "unit": "index"})
        if rain is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "RAINFALL",
                                 "value": rain, "unit": "mm/hr"})
        # Coverage: flood uses a centroid rainfall broadcast — default confidence
        signal_rows.extend(coverage_signals(h3_id, None, "flood"))
        flood_risk = cell.get("risk_level", "unknown")
        write_assessment(h3_id=h3_id, city_id=city_id, domain="flood",
                         risk_level=flood_risk,
                         primary_index="FLOOD_RISK_SCORE", primary_value=score,
                         dominant_issue=cell.get("dominant_issue"), summary=cell)
        # Analysis gate: flood default confidence is 0.45 — below threshold
        # Most flood cells will be flagged for siting rather than analysis
        from urban_platform.h3_knowledge.coverage import DOMAIN_DEFAULT_CONFIDENCE
        _apply_analysis_gate(
            h3_id=h3_id, city_id=city_id, domain="flood",
            new_risk_level=flood_risk,
            data_confidence=DOMAIN_DEFAULT_CONFIDENCE.get("flood", 0.45),
        )
    written = write_signals(signal_rows, city_id=city_id, domain="flood", source="imd")
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="flood",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="flood", rows_written=written)
    return written


def _ingest_heat(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("heat", city_id, force)
    from urban_platform.applications.heat.heat_pipeline import (
        build_heat_risk_dashboard, build_intervention_candidates,
    )
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    import pandas as pd

    # Fetch a current temperature reading from Open-Meteo at the city centroid.
    # The heat pipeline does IDW from observation points; with a single centroid
    # point every cell gets the same temperature (UHI = 0), but the pipeline still
    # produces a valid heat_risk_score driven by the green-deficit component.
    centroid_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2.0
    centroid_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2.0
    try:
        from urban_platform.connectors.weather.openmeteo_current import fetch_current_weather
        wx = fetch_current_weather(centroid_lat, centroid_lon)
        if wx.get("error") or wx.get("temperature_c") is None:
            temperature_df = pd.DataFrame()
        else:
            temperature_df = pd.DataFrame([{
                "station_id":    f"openmeteo_{city_id}",
                "timestamp":     pd.Timestamp.utcnow(),
                "temperature_c": float(wx["temperature_c"]),
                "latitude":      centroid_lat,
                "longitude":     centroid_lon,
                "quality_flag":  "real",
            }])
    except Exception as _wx_exc:
        logger.debug("[%s/heat] weather fetch skipped: %s", city_id, _wx_exc)
        temperature_df = pd.DataFrame()

    try:
        dashboard  = build_heat_risk_dashboard(temperature_df=temperature_df,
                                               green_cover_df=pd.DataFrame(),
                                               h3_resolution=DEFAULT_H3_RES,
                                               city_id=city_id, **bbox)
        candidates = build_intervention_candidates(temperature_df=temperature_df,
                                                   green_cover_df=pd.DataFrame(),
                                                   h3_resolution=DEFAULT_H3_RES,
                                                   city_id=city_id, **bbox)
    except Exception as exc:
        logger.warning("[%s/heat] pipeline error: %s", city_id, exc)
        record_ingest(city_id=city_id, domain="heat", rows_written=0, status="error",
                      error_msg=str(exc))
        return 0
    from urban_platform.h3_knowledge.coverage import coverage_signals
    signal_rows = []
    # Dashboard returns key "heat_cells" (not "risk_cells")
    for cell in dashboard.get("heat_cells", []):
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        score = cell.get("heat_risk_score")
        lst   = cell.get("heat_index_c") or cell.get("temperature_c")
        uhi   = cell.get("uhi_intensity")
        for sig, val, unit in [("HEAT_RISK_SCORE", score, "index"),
                                ("LST", lst, "degC"), ("UHI", uhi, "degC")]:
            if val is not None:
                signal_rows.append({"h3_id": h3_id, "signal": sig,
                                     "value": val, "unit": unit})
        # Coverage: heat is a city-centroid broadcast — default confidence
        signal_rows.extend(coverage_signals(h3_id, None, "heat"))
        heat_risk = "high" if (score or 0) >= 0.66 else "moderate" if (score or 0) >= 0.33 else "low"
        write_assessment(h3_id=h3_id, city_id=city_id, domain="heat",
                         risk_level=heat_risk, primary_index="HEAT_RISK_SCORE",
                         primary_value=score, summary=cell)
        # Analysis gate: heat default confidence is 0.50 — below threshold
        # Heat cells will be flagged for siting (compact weather station recommended)
        from urban_platform.h3_knowledge.coverage import DOMAIN_DEFAULT_CONFIDENCE
        _apply_analysis_gate(
            h3_id=h3_id, city_id=city_id, domain="heat",
            new_risk_level=heat_risk,
            data_confidence=DOMAIN_DEFAULT_CONFIDENCE.get("heat", 0.50),
        )
    written = write_signals(signal_rows, city_id=city_id, domain="heat", source="openmeteo")
    for cand in candidates.get("candidates", []):
        write_packet(packet_id=cand.get("candidate_id", ""),
                     h3_id=cand.get("h3_id", ""),
                     city_id=city_id, domain="heat",
                     risk_level="high" if (cand.get("heat_risk_score") or 0) >= 0.66 else "moderate",
                     confidence_score=cand.get("heat_risk_score"),
                     field_verification_required=False, packet=cand)
    record_ingest(city_id=city_id, domain="heat", rows_written=written)
    return written


def _ingest_waste(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("waste", city_id, force)
    from review_dashboard.data_cache import load_firms
    from urban_platform.applications.waste.waste_pipeline import (
        build_waste_dashboard, build_waste_decision_packets,
    )
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    fire_df = load_firms(bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], 3)
    if fire_df is None or (hasattr(fire_df, "empty") and fire_df.empty):
        logger.info("[%s/waste] No live FIRMS data — skipping.", city_id)
        record_ingest(city_id=city_id, domain="waste", rows_written=0, status="partial",
                      error_msg="no live FIRMS data")
        return 0
    dashboard = build_waste_dashboard(firms_df=fire_df, ndvi_map={}, ch4_map={},
                                      h3_resolution=DEFAULT_H3_RES, city_id=city_id, **bbox)
    packets   = build_waste_decision_packets(firms_df=fire_df, ndvi_map={}, ch4_map={},
                                             h3_resolution=DEFAULT_H3_RES, city_id=city_id,
                                             **bbox, top_n=20)
    signal_rows = []
    for cell in dashboard.get("risk_cells", []):
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        for sig, key, unit in [("WASTE_RISK_SCORE", "waste_risk_score", "index"),
                                ("WASTE_FRP", "max_frp_mw", "MW"),
                                ("CH4", "ch4_ppb", "ppb")]:
            val = cell.get(key)
            if val is not None:
                signal_rows.append({"h3_id": h3_id, "signal": sig,
                                     "value": val, "unit": unit})
        # Waste: direct thermal detection — nearest_obs_km=0 → confidence=1.0
        from urban_platform.h3_knowledge.coverage import coverage_signals
        signal_rows.extend(coverage_signals(h3_id, 0.0, "waste"))
        waste_risk = cell.get("risk_level", "unknown")
        write_assessment(h3_id=h3_id, city_id=city_id, domain="waste",
                         risk_level=waste_risk,
                         primary_index="WASTE_RISK_SCORE",
                         primary_value=cell.get("waste_risk_score"),
                         dominant_issue=cell.get("dominant_type"), summary=cell)
        # Analysis gate: waste always has confidence=1.0 (direct thermal detection)
        _apply_analysis_gate(
            h3_id=h3_id, city_id=city_id, domain="waste",
            new_risk_level=waste_risk, data_confidence=1.0,
        )
    written = write_signals(signal_rows, city_id=city_id, domain="waste", source="firms")
    for pkt in packets:
        write_packet(packet_id=pkt.get("packet_id", ""), h3_id=pkt.get("spatial_unit_id", ""),
                     city_id=city_id, domain="waste",
                     risk_level=pkt.get("risk_level", "unknown"),
                     confidence_score=pkt.get("confidence_score"),
                     field_verification_required=bool(pkt.get("field_verification_required")),
                     packet=pkt)
    record_ingest(city_id=city_id, domain="waste", rows_written=written)
    return written


def _ingest_weather(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch current weather from Open-Meteo (no API key) and store as H3 signals.

    Fetches a single point at the city centroid — wind, humidity, pressure, and
    temperature vary slowly at city scale so broadcasting to all H3 cells is a
    reasonable approximation for cross-domain causal reasoning.

    Signals written per cell:
        WIND_SPEED_KMH   — 10 m wind speed (km/h)
        WIND_DIR_DEG     — 10 m wind direction in degrees (0=N, 90=E, …)
        HUMIDITY_PCT     — relative humidity at 2 m (%)
        PRESSURE_HPA     — mean sea-level pressure (hPa)
        TEMPERATURE_C    — ambient temperature at 2 m (°C)
        PRECIP_MM        — precipitation in the last hour (mm)
    """
    _check_interval("weather", city_id, force)

    from urban_platform.connectors.weather.openmeteo_current import fetch_current_weather
    from urban_platform.h3_knowledge.writer import write_signals, upsert_metadata

    # City centroid for the single-point weather fetch
    centroid_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2.0
    centroid_lon = (bbox["lon_min"] + bbox["lon_max"]) / 2.0

    wx = fetch_current_weather(centroid_lat, centroid_lon)
    if wx.get("error"):
        logger.warning("[%s/weather] Open-Meteo fetch error: %s", city_id, wx["error"])
        record_ingest(city_id=city_id, domain="weather", rows_written=0, status="error",
                      error_msg=wx["error"])
        return 0

    # Build signal rows — only include fields that have values
    _signal_map = [
        ("WIND_SPEED_KMH",  wx.get("wind_speed_kmh"),     "km/h"),
        ("WIND_DIR_DEG",    wx.get("wind_direction_deg"),  "deg"),
        ("HUMIDITY_PCT",    wx.get("humidity_pct"),        "%"),
        ("PRESSURE_HPA",    wx.get("pressure_hpa"),        "hPa"),
        ("TEMPERATURE_C",   wx.get("temperature_c"),       "degC"),
        ("PRECIP_MM",       wx.get("precipitation_mm"),    "mm"),
    ]
    available_signals = [(sig, val, unit) for sig, val, unit in _signal_map if val is not None]

    if not available_signals:
        logger.info("[%s/weather] All signal values null — skipping.", city_id)
        record_ingest(city_id=city_id, domain="weather", rows_written=0, status="partial",
                      error_msg="all signal values null")
        return 0

    # Generate H3 cells for the city bounding box (reuse existing helper)
    try:
        from review_dashboard.data_cache import h3_grid_for_bbox
        import h3
        h3_ids = list(h3_grid_for_bbox(
            bbox["lat_min"], bbox["lon_min"],
            bbox["lat_max"], bbox["lon_max"],
            DEFAULT_H3_RES,
        ))
    except Exception as exc:
        logger.warning("[%s/weather] H3 grid generation failed: %s", city_id, exc)
        record_ingest(city_id=city_id, domain="weather", rows_written=0, status="error",
                      error_msg=str(exc))
        return 0

    if not h3_ids:
        logger.info("[%s/weather] No H3 cells in bbox — skipping.", city_id)
        record_ingest(city_id=city_id, domain="weather", rows_written=0, status="partial")
        return 0

    # Register metadata and broadcast signals to every cell
    from urban_platform.h3_knowledge.coverage import coverage_signals, distance_to_confidence
    import math
    signal_rows: list[dict] = []
    for h3_id in h3_ids:
        lat, lon = h3.cell_to_latlng(h3_id)
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES,
                        centroid_lat=lat, centroid_lon=lon)
        for sig, val, unit in available_signals:
            signal_rows.append({
                "h3_id":  h3_id,
                "signal": sig,
                "value":  val,
                "unit":   unit,
            })
        # Coverage: distance from cell centroid to the city-centroid observation point
        # Cells near city centre get slightly higher confidence than fringe cells
        from urban_platform.applications.flood.flood_pipeline import _haversine_km
        dist_km = _haversine_km(lat, lon, centroid_lat, centroid_lon)
        signal_rows.extend(coverage_signals(h3_id, dist_km, "weather"))

    written = write_signals(signal_rows, city_id=city_id, domain="weather",
                            source="openmeteo_forecast")
    logger.info(
        "[%s/weather] %d cells × %d signals = %d rows  "
        "(wind %.1f km/h @ %s°, humidity %.0f%%, pressure %.0f hPa)",
        city_id, len(h3_ids), len(available_signals), written,
        wx.get("wind_speed_kmh") or 0,
        wx.get("wind_direction_deg") or "?",
        wx.get("humidity_pct") or 0,
        wx.get("pressure_hpa") or 0,
    )
    record_ingest(city_id=city_id, domain="weather", rows_written=written)
    return written


# ---------------------------------------------------------------------------
# Sensor siting — monthly batch job
# ---------------------------------------------------------------------------

def run_siting_batch(
    cities: list[str] | None = None,
    domains: list[str] | None = None,
    *,
    period_days: int = SITING_PERIOD_DAYS,
    force: bool = False,
) -> dict[str, dict[str, int]]:
    """Compute and persist sensor siting candidates for all city × domain pairs.

    Skips any pair that was already computed within SITING_INTERVAL_DAYS (30 days)
    unless force=True.

    Returns {city_id: {domain: candidates_written}}.
    """
    from urban_platform.h3_knowledge.writer import compute_and_store_siting
    from urban_platform.h3_knowledge.store import H3KnowledgeStore

    cities  = cities  or ALL_CITIES
    # Exclude structural/context domains that produce no h3_assessments rows.
    # "crowd" IS included — gathering alerts write assessments (risk_level="high").
    _NO_ASSESSMENT_DOMAINS = {"weather", "buildings", "roads", "drains"}
    domains = domains or [d for d in ALL_DOMAINS if d not in _NO_ASSESSMENT_DOMAINS]

    results: dict[str, dict[str, int]] = {}

    for city_id in cities:
        results[city_id] = {}
        for domain in domains:
            if not force:
                # Check siting_log watermark
                row = H3KnowledgeStore.get().fetchone(
                    "SELECT computed_at FROM h3_siting_log WHERE city_id = ? AND domain = ?",
                    [city_id, domain],
                )
                if row:
                    try:
                        last_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                        elapsed = datetime.now(timezone.utc) - last_dt
                        if elapsed < timedelta(days=SITING_INTERVAL_DAYS):
                            remaining = SITING_INTERVAL_DAYS - elapsed.days
                            logger.debug(
                                "[siting] %s/%s skipped — computed %dd ago, "
                                "next run in ~%dd",
                                city_id, domain, elapsed.days, remaining,
                            )
                            results[city_id][domain] = -1  # -1 = skipped (too recent)
                            continue
                    except Exception:
                        pass  # malformed timestamp — proceed with recompute

            try:
                n = compute_and_store_siting(city_id, domain,
                                             period_days=period_days, top_n=50)
                results[city_id][domain] = n
                logger.info("[siting] %s/%s — %d candidates written", city_id, domain, n)
            except Exception as exc:
                logger.error("[siting] %s/%s failed: %s", city_id, domain, exc)
                results[city_id][domain] = 0

    return results


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def _ingest_buildings(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from urban_platform.h3_knowledge.buildings_ingestor import ingest_buildings
    return ingest_buildings(city_id, bbox, force=force)


def _ingest_roads(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from urban_platform.h3_knowledge.roads_ingestor import ingest_roads
    return ingest_roads(city_id, bbox, force=force)


def _ingest_drains(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from urban_platform.h3_knowledge.drains_ingestor import ingest_drains
    return ingest_drains(city_id, bbox, force=force)


def _ingest_crowd(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from urban_platform.h3_knowledge.crowd_ingestor import ingest_crowd
    return ingest_crowd(city_id, bbox, force=force)


_DOMAIN_FN: dict[str, Callable] = {
    "air":          _ingest_air,
    "water":        _ingest_water,
    "construction": _ingest_construction,
    "green":        _ingest_green,
    "noise":        _ingest_noise,
    "fire":         _ingest_fire,
    "flood":        _ingest_flood,
    "heat":         _ingest_heat,
    "waste":        _ingest_waste,
    "weather":      _ingest_weather,
    # Urban infrastructure (OSM)
    "buildings":    _ingest_buildings,
    "roads":        _ingest_roads,
    "drains":       _ingest_drains,
    "crowd":        _ingest_crowd,
}


# ---------------------------------------------------------------------------
# Watermark guard — skip domain if run too recently
# ---------------------------------------------------------------------------

class _TooRecentError(Exception):
    pass


def _check_interval(domain: str, city_id: str, force: bool) -> None:
    if force:
        return
    last = get_last_ingest(city_id, domain)
    if last is None:
        return
    min_gap = _DOMAIN_INTERVAL.get(domain, timedelta(hours=1))
    now = datetime.now(timezone.utc)
    # normalise tz-naive timestamps
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = now - last
    if elapsed < min_gap:
        remaining = int((min_gap - elapsed).total_seconds() / 60)
        raise _TooRecentError(
            f"{domain}/{city_id} last ingested {int(elapsed.total_seconds()/60)}m ago "
            f"(min gap {int(min_gap.total_seconds()/60)}m) — {remaining}m remaining. "
            f"Use --force to override."
        )


# ---------------------------------------------------------------------------
# Domain dispatch — driver-aware
# ---------------------------------------------------------------------------

def _run_domain(
    domain: str,
    city_id: str,
    bbox: dict,
    *,
    force: bool = False,
) -> int:
    """Run one domain for one city.

    Dispatch priority:
      1. Active driver pool (loaded from drivers_registry.yaml via driver_loader).
         These are driver instances satisfying H3DataSourceDriver Protocol.
      2. Legacy _DOMAIN_FN dict (thin wrappers, kept for backward compat until
         Phase 2 packaging is complete).

    Returns rows written (0 = error/no data, -1 = skipped due to watermark).
    """
    # Try the driver pool first
    try:
        from urban_platform.sdk.driver_loader import get_active_drivers
        drivers = get_active_drivers()
        driver = drivers.get(domain)
    except Exception:
        driver = None

    if driver is not None:
        try:
            n = driver.fetch(city_id, bbox, force=force)
            logger.info("[%s/%s] ingested %d rows (driver: %s)", city_id, domain, n, type(driver).__name__)
            return n
        except _TooRecentError as e:
            logger.debug("Skipped: %s", e)
            return -1
        except Exception as exc:
            logger.error("[%s/%s] driver fetch failed: %s", city_id, domain, exc)
            record_ingest(city_id=city_id, domain=domain, rows_written=0,
                          status="error", error_msg=str(exc))
            return 0

    # Fallback: legacy dispatch table
    fn = _DOMAIN_FN.get(domain)
    if not fn:
        logger.warning("Unknown domain '%s' — no driver or legacy function found.", domain)
        return 0

    try:
        n = fn(city_id, bbox, force=force)
        logger.info("[%s/%s] ingested %d rows (legacy)", city_id, domain, n)
        return n
    except _TooRecentError as e:
        logger.debug("Skipped: %s", e)
        return -1
    except Exception as exc:
        logger.error("[%s/%s] ingest failed: %s", city_id, domain, exc)
        record_ingest(city_id=city_id, domain=domain, rows_written=0,
                      status="error", error_msg=str(exc))
        return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    cities: list[str] | None = None,
    domains: list[str] | None = None,
    *,
    force: bool = False,
) -> dict[str, dict[str, int]]:
    """Run the ingestor for the given cities and domains.

    Uses SQLite + WAL mode — the dashboard (readers) and ingestor (writer)
    can run simultaneously without lock errors.

    Returns a nested dict: {city_id: {domain: rows_written}}.
    """
    cities  = cities  or ALL_CITIES
    domains = domains or ALL_DOMAINS

    results: dict[str, dict[str, int]] = {}

    for city_id in cities:
        bbox = _CITY_BBOXES.get(city_id)
        if not bbox:
            logger.warning("Unknown city '%s' — skipping.", city_id)
            continue
        results[city_id] = {}
        for domain in domains:
            n = _run_domain(domain, city_id, bbox, force=force)
            results[city_id][domain] = n

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="H3 Knowledge Store — batch ingestor")
    parser.add_argument("--cities",  default=",".join(ALL_CITIES),
                        help="Comma-separated city IDs (default: all)")
    parser.add_argument("--domains", default=",".join(ALL_DOMAINS),
                        help="Comma-separated domain names (default: all)")
    parser.add_argument("--force", action="store_true",
                        help="Ignore watermarks and re-ingest regardless of last run time")
    args = parser.parse_args()

    cities  = [c.strip() for c in args.cities.split(",")  if c.strip()]
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]

    print(f"\nH3 Knowledge Store ingestor")
    print(f"  Cities : {', '.join(cities)}")
    print(f"  Domains: {', '.join(domains)}")
    print(f"  Force  : {args.force}\n")

    results = run(cities=cities, domains=domains, force=args.force)

    print("\nResults:")
    total = 0
    for city, domain_map in results.items():
        for domain, n in domain_map.items():
            status = "skipped (too recent)" if n == -1 else f"{n} rows"
            print(f"  {city:12s} {domain:14s} {status}")
            if n > 0:
                total += n
    print(f"\nTotal rows written: {total}")


if __name__ == "__main__":
    _cli()
