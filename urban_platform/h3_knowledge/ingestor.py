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
ALL_DOMAINS = ["air", "fire", "heat", "flood", "water", "waste", "construction", "green", "noise"]

# How often each domain should be re-ingested (minimum gap between runs)
_DOMAIN_INTERVAL: dict[str, timedelta] = {
    "air":          timedelta(minutes=15),
    "fire":         timedelta(minutes=15),
    "heat":         timedelta(minutes=30),
    "flood":        timedelta(hours=1),
    "water":        timedelta(hours=1),
    "waste":        timedelta(hours=1),
    "construction": timedelta(hours=6),
    "green":        timedelta(hours=6),
    "noise":        timedelta(hours=6),
}

DEFAULT_H3_RES = 8


# ---------------------------------------------------------------------------
# Per-domain ingest functions
# ---------------------------------------------------------------------------

def _ingest_air(city_id: str, bbox: dict, *, force: bool = False) -> int:
    _check_interval("air", city_id, force)
    from urban_platform.applications.air_quality.pipeline import (
        build_air_quality_dashboard, build_air_quality_decision_packets,
    )
    from review_dashboard.data_cache import load_air_quality_dataframe
    try:
        aq_df = load_air_quality_dataframe(city_id)
    except Exception:
        aq_df = None
    if aq_df is None or aq_df.empty:
        logger.info("[%s/air] No live data available — skipping.", city_id)
        record_ingest(city_id=city_id, domain="air", rows_written=0, status="partial",
                      error_msg="no live AQ data")
        return 0
    dashboard = build_air_quality_dashboard(
        aq_df=aq_df, h3_resolution=DEFAULT_H3_RES, city_id=city_id, **bbox,
    )
    packets = build_air_quality_decision_packets(
        aq_df=aq_df, h3_resolution=DEFAULT_H3_RES, city_id=city_id, **bbox, top_n=20,
    )
    cells = dashboard.get("risk_cells", [])
    from urban_platform.h3_knowledge.writer import write_signals, write_assessment, upsert_metadata
    signal_rows = []
    for cell in cells:
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES,
                        centroid_lat=cell.get("centroid_lat"),
                        centroid_lon=cell.get("centroid_lon"))
        aqi = cell.get("aqi")
        if aqi is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "AQI", "value": aqi, "unit": "index"})
        write_assessment(h3_id=h3_id, city_id=city_id, domain="air",
                         risk_level=cell.get("risk_level", "unknown"),
                         primary_index="AQI", primary_value=aqi,
                         dominant_issue=cell.get("dominant_pollutant"), summary=cell)
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
    written = ingest_assessment_cells(cell_list, city_id=city_id, domain="water",
                                      signal_key="wqi", risk_key="risk_level",
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
                                      signal_key="cri", risk_key="risk_level",
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
                                      signal_key="gcci", risk_key="risk_level",
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
                                      signal_key="nri", risk_key="risk_level",
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
    signal_rows = []
    for cell in dashboard.get("risk_cells", []):
        h3_id = cell.get("h3_id")
        if not h3_id:
            continue
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)
        frp = cell.get("max_frp_mw") or cell.get("frp")
        if frp is not None:
            signal_rows.append({"h3_id": h3_id, "signal": "FRP", "value": frp, "unit": "MW"})
        write_assessment(h3_id=h3_id, city_id=city_id, domain="fire",
                         risk_level=cell.get("risk_level", "unknown"),
                         primary_index="FRP", primary_value=frp, summary=cell)
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
    # Flood pipeline fetches its own data (IMD rain + incident reports)
    try:
        dashboard = build_flood_risk_dashboard(h3_resolution=DEFAULT_H3_RES,
                                               city_id=city_id, **bbox)
        packets   = build_flood_decision_packets(h3_resolution=DEFAULT_H3_RES,
                                                 city_id=city_id, **bbox, top_n=20)
    except Exception as exc:
        logger.warning("[%s/flood] pipeline error: %s", city_id, exc)
        record_ingest(city_id=city_id, domain="flood", rows_written=0, status="error",
                      error_msg=str(exc))
        return 0
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
        write_assessment(h3_id=h3_id, city_id=city_id, domain="flood",
                         risk_level=cell.get("risk_level", "unknown"),
                         primary_index="FLOOD_RISK_SCORE", primary_value=score,
                         dominant_issue=cell.get("dominant_issue"), summary=cell)
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
    try:
        dashboard  = build_heat_risk_dashboard(temperature_df=pd.DataFrame(),
                                               green_cover_df=pd.DataFrame(),
                                               h3_resolution=DEFAULT_H3_RES,
                                               city_id=city_id, **bbox)
        candidates = build_intervention_candidates(temperature_df=pd.DataFrame(),
                                                   green_cover_df=pd.DataFrame(),
                                                   h3_resolution=DEFAULT_H3_RES,
                                                   city_id=city_id, **bbox)
    except Exception as exc:
        logger.warning("[%s/heat] pipeline error: %s", city_id, exc)
        record_ingest(city_id=city_id, domain="heat", rows_written=0, status="error",
                      error_msg=str(exc))
        return 0
    signal_rows = []
    for cell in dashboard.get("risk_cells", []):
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
        risk = "high" if (score or 0) >= 0.66 else "moderate" if (score or 0) >= 0.33 else "good"
        write_assessment(h3_id=h3_id, city_id=city_id, domain="heat",
                         risk_level=risk, primary_index="HEAT_RISK_SCORE",
                         primary_value=score, summary=cell)
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
        write_assessment(h3_id=h3_id, city_id=city_id, domain="waste",
                         risk_level=cell.get("risk_level", "unknown"),
                         primary_index="WASTE_RISK_SCORE",
                         primary_value=cell.get("waste_risk_score"),
                         dominant_issue=cell.get("dominant_type"), summary=cell)
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


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

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
# Public entry point
# ---------------------------------------------------------------------------

def run(
    cities: list[str] | None = None,
    domains: list[str] | None = None,
    *,
    force: bool = False,
) -> dict[str, dict[str, int]]:
    """Run the ingestor for the given cities and domains.

    Opens a read-write connection (exclusively), runs all domain ingests,
    then closes the connection so the dashboard can resume read-only access.

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
            fn = _DOMAIN_FN.get(domain)
            if not fn:
                logger.warning("Unknown domain '%s' — skipping.", domain)
                continue
            try:
                n = fn(city_id, bbox, force=force)
                results[city_id][domain] = n
                logger.info("[%s/%s] ingested %d rows", city_id, domain, n)
            except _TooRecentError as e:
                logger.debug("Skipped: %s", e)
                results[city_id][domain] = -1  # -1 = skipped
            except Exception as exc:
                logger.error("[%s/%s] ingest failed: %s", city_id, domain, exc)
                record_ingest(city_id=city_id, domain=domain, rows_written=0,
                              status="error", error_msg=str(exc))
                results[city_id][domain] = 0
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
