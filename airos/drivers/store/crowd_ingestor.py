"""Crowd domain ingestor — CCTV camera people_count → per-H3-cell signals (15-min cadence).

Sources (in priority order):
  1. observation_store.parquet — canonical store written by the camera publisher pipeline.
     Camera lat/lon comes from the camera registry (data/config/camera_registry.json)
     or from point_lat / point_lon columns if the publisher attaches them.
  2. Camera registry join only — if the observation store has entity_id but no coordinates.

Signals written (domain="crowd", source="cctv"):
    PEOPLE_COUNT      count      Total people counted across cameras in cell window
    CAMERA_COUNT      count      Number of active cameras that reported in this window
    CROWD_DENSITY     per_km2    PEOPLE_COUNT / cell_area_km2
    CROWD_INDEX       index      Normalised 0–1 crowd intensity (vs configurable ceiling)
    GATHERING_ALERT   flag       1.0 if CROWD_DENSITY exceeds event-detection threshold

Gathering detection threshold:
    CROWD_DENSITY ≥ 500 people/km²  →  GATHERING_ALERT = 1.0
    Cells flagged this way are also written as h3_assessments (risk_level="high")
    so the H3 Expert Agent sees them in its initial context and can reason about
    event-driven air quality or safety risks.

Refresh cadence: 15 minutes (matches typical CCTV analytics pipeline lag).
Data confidence: 0.90 for cameras that reported in the window;
                 0.0  for cells with no camera coverage (not written — absence = no data).

Privacy note:
    Only aggregate counts are stored — no frames, no faces, no trajectories.
    The camera publisher is responsible for ensuring no PII leaves the edge device.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from airos.os.rules import rules as _rules

def _gathering_threshold() -> float:
    return _rules.get("crowd", "gathering_threshold_per_km2", default=500.0)

def _index_saturation() -> float:
    return _rules.get("crowd", "index_saturation_per_km2", default=2000.0)

def _lookback_minutes() -> int:
    return int(_rules.get("crowd", "observation_window_minutes", default=20))

def _data_confidence() -> float:
    return _rules.get("crowd", "data_confidence", default=0.90)

# Path to the observation store (relative to project root)
_OBS_STORE_RELPATH = Path("data") / "processed" / "observation_store.parquet"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_recent_people_count(project_root: Path, lookback_minutes: int) -> "pd.DataFrame":
    """Load people_count observations from the canonical observation store.

    Returns an empty DataFrame if the store does not exist or has no data.
    """
    import pandas as pd

    obs_path = project_root / _OBS_STORE_RELPATH
    if not obs_path.exists():
        logger.debug("Observation store not found at %s", obs_path)
        return pd.DataFrame()

    try:
        df = pd.read_parquet(obs_path)
    except Exception as exc:
        logger.warning("Could not read observation store: %s", exc)
        return pd.DataFrame()

    # Normalise variable/observed_property column
    if "observed_property" in df.columns and "variable" not in df.columns:
        df["variable"] = df["observed_property"]

    # Filter to people_count
    if "variable" not in df.columns:
        return pd.DataFrame()
    df = df[df["variable"].astype(str) == "people_count"].copy()

    if df.empty:
        return df

    # Time filter — keep only the most recent window
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df[df["timestamp"] >= cutoff]

    return df.reset_index(drop=True)


def _attach_coordinates(
    obs_df: "pd.DataFrame",
    city_id: str,
) -> "pd.DataFrame":
    """Join camera registry lat/lon onto observation rows.

    Priority:
      1. point_lat / point_lon already in the DataFrame (publisher attached them)
      2. Camera registry lookup by entity_id
    """
    import pandas as pd
    from airos.drivers.registries.cameras import cameras_for_city

    df = obs_df.copy()

    # Coerce existing coordinate columns if present
    for col in ("point_lat", "point_lon"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")

    # Identify rows that still need coordinates
    missing_mask = df["point_lat"].isna() | df["point_lon"].isna()

    if missing_mask.any() and "entity_id" in df.columns:
        reg = cameras_for_city(city_id)
        if not reg.empty:
            reg_map = reg.set_index("entity_id")[["latitude", "longitude"]]
            matched = df.loc[missing_mask, "entity_id"].map(reg_map["latitude"])
            df.loc[missing_mask, "point_lat"] = (
                df.loc[missing_mask, "entity_id"].map(reg_map["latitude"])
            )
            df.loc[missing_mask, "point_lon"] = (
                df.loc[missing_mask, "entity_id"].map(reg_map["longitude"])
            )

    # Drop rows with no coordinates — we cannot place them
    df = df.dropna(subset=["point_lat", "point_lon"])
    return df.reset_index(drop=True)


def _aggregate_to_h3(
    obs_df: "pd.DataFrame",
    h3_ids: list[str],
    resolution: int,
) -> dict[str, dict[str, Any]]:
    """Assign each observation to an H3 cell; aggregate counts per cell.

    Returns
    -------
    dict  {h3_id: {"people_count": int, "camera_count": int}}
    """
    import h3 as _h3
    import pandas as pd

    result: dict[str, dict[str, Any]] = {
        h3_id: {"people_count": 0, "camera_count": 0} for h3_id in h3_ids
    }
    h3_id_set = set(h3_ids)

    if obs_df.empty:
        return result

    for _, row in obs_df.iterrows():
        try:
            lat = float(row["point_lat"])
            lon = float(row["point_lon"])
            val = float(row["value"]) if row.get("value") is not None else 0.0
        except (TypeError, ValueError):
            continue

        cell = _h3.latlng_to_cell(lat, lon, resolution)
        if cell not in h3_id_set:
            continue

        result[cell]["people_count"] += val
        result[cell]["camera_count"] += 1

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_crowd(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Read latest camera people_count observations and write per-H3-cell crowd signals.

    Parameters
    ----------
    city_id : str
    bbox    : dict with keys lat_min, lon_min, lat_max, lon_max
    force   : skip the watermark interval check

    Returns
    -------
    int — number of signal rows written
    """
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import (
        write_signals, write_assessment, upsert_metadata, record_ingest,
    )
    from airos.drivers.store.geo_agg import cells_for_bbox, cell_area_km2

    try:
        _check_interval("crowd", city_id, force)
    except Exception as e:
        logger.info("[%s/crowd] %s", city_id, e)
        return 0

    # Resolve project root (two levels up from this file)
    project_root = Path(__file__).resolve().parents[3]

    _lbm = _lookback_minutes()
    logger.info("[%s/crowd] Loading people_count observations (last %dm) …", city_id, _lbm)
    obs_df = _load_recent_people_count(project_root, _lbm)

    if obs_df.empty:
        logger.info("[%s/crowd] No people_count observations in window.", city_id)
        record_ingest(city_id=city_id, domain="crowd", rows_written=0,
                      status="partial", error_msg="no camera observations in window")
        return 0

    # Attach coordinates via camera registry or existing point_lat/lon columns
    obs_df = _attach_coordinates(obs_df, city_id)
    if obs_df.empty:
        logger.info(
            "[%s/crowd] Observations found but none could be geo-located. "
            "Register cameras in data/config/camera_registry.json.",
            city_id,
        )
        record_ingest(city_id=city_id, domain="crowd", rows_written=0,
                      status="partial", error_msg="no geo-located camera observations")
        return 0

    logger.info("[%s/crowd] %d geo-located observations. Assigning to H3 cells …",
                city_id, len(obs_df))

    h3_ids   = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )
    area_km2 = cell_area_km2(DEFAULT_H3_RES)

    aggregated = _aggregate_to_h3(obs_df, h3_ids, DEFAULT_H3_RES)

    # Only write signals for cells that have at least one camera reporting.
    # Cells with no camera coverage are simply absent — not zeros.
    # This is intentional: a zero in a cell with no camera is meaningless;
    # the H3 Expert Agent should see absence rather than a misleading zero.
    signal_rows: list[dict] = []
    active_cells = 0

    for h3_id, agg in aggregated.items():
        cam_count    = agg["camera_count"]
        people_count = agg["people_count"]

        if cam_count == 0:
            continue  # no camera coverage — do not write zeros

        active_cells += 1
        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        density = round(people_count / area_km2, 2)
        index   = round(min(density / _index_saturation(), 1.0), 4)
        alert   = 1.0 if density >= _gathering_threshold() else 0.0

        signal_rows += [
            {"h3_id": h3_id, "signal": "PEOPLE_COUNT",    "value": float(people_count), "unit": "count"},
            {"h3_id": h3_id, "signal": "CAMERA_COUNT",    "value": float(cam_count),    "unit": "count"},
            {"h3_id": h3_id, "signal": "CROWD_DENSITY",   "value": density,              "unit": "per_km2"},
            {"h3_id": h3_id, "signal": "CROWD_INDEX",     "value": index,                "unit": "index"},
            {"h3_id": h3_id, "signal": "GATHERING_ALERT", "value": alert,                "unit": "flag"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE", "value": _data_confidence(),   "unit": "ratio"},
        ]

        # Write an assessment for gathering-detected cells so the H3 Expert
        # Agent sees them in its initial context alongside AQI / heat signals.
        if alert:
            write_assessment(
                h3_id=h3_id, city_id=city_id, domain="crowd",
                risk_level="high",
                primary_index="CROWD_DENSITY",
                primary_value=density,
                dominant_issue="gathering_detected",
                summary={
                    "people_count":    people_count,
                    "crowd_density":   density,
                    "camera_count":    cam_count,
                    "threshold":       _gathering_threshold(),
                },
            )

    written = write_signals(signal_rows, city_id=city_id, domain="crowd", source="cctv")
    logger.info(
        "[%s/crowd] %d active camera cell(s) / %d total cells — %d rows written.",
        city_id, active_cells, len(h3_ids), written,
    )
    record_ingest(city_id=city_id, domain="crowd", rows_written=written)
    return written
