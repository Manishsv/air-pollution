"""Night Lights domain ingestor — VIIRS NTL samples → per-H3-cell signals.

Signals written (domain="nightlights"):
    NTL_RADIANCE          nW/cm²/sr  Mean VIIRS DNB radiance per cell (0=dark, 60+=very bright).
    NTL_LIT_FRACTION      ratio      Fraction of sub-pixels above 0.3 nW threshold (0–1).
    ECONOMIC_ACTIVITY_INDEX index    Normalised radiance (NTL_RADIANCE / 60.0, capped 1.0).
    DATA_CONFIDENCE       ratio      0.90 real VIIRS, 0.65 cloud-contaminated/gap-filled, 0.0 synthetic.
    ACTIVITY_CLASS        ordinal    Rule-based class: 0=dark, 1=residential, 2=commercial, 3=industrial.
                                     Stored as float ordinal in value (REAL column); unit field = label.
                                     Written immediately after the main 4 signals using skip_conformance=True.

Classification thresholds (absolute NTL_RADIANCE nW/cm²/sr):
    dark       < 1.0
    residential  1.0–10.0
    commercial  10.0–35.0
    industrial  > 35.0

Refresh cadence: 30 days (monthly VIIRS composites).
Data confidence: 0.90 (real VIIRS); 0.65 (cloud-contaminated or gap-filled > 10%);
                 0.0 (synthetic fallback).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from airos.drivers.connectors.nightlights.viirs import fetch_ntl_samples  # noqa: E402 — module-level for mockability

logger = logging.getLogger(__name__)

# Fraction of cloud-contaminated/void-filled samples above which DATA_CONFIDENCE
# drops from 0.90 to 0.65.
_CLOUD_FRACTION_THRESHOLD = 0.10

# ---------------------------------------------------------------------------
# ACTIVITY_CLASS ordinal encoding
# ---------------------------------------------------------------------------
# h3_signals.value is REAL — store class as integer ordinal; decode in the panel.
ACTIVITY_CLASS_LABELS: dict[int, str] = {
    0: "dark",
    1: "residential",
    2: "commercial",
    3: "industrial",
}
ACTIVITY_CLASS_ORDINAL: dict[str, int] = {v: k for k, v in ACTIVITY_CLASS_LABELS.items()}

# Absolute NTL_RADIANCE thresholds (nW/cm²/sr)
_RADIANCE_DARK       = 1.0    # < 1.0 → dark
_RADIANCE_COMMERCIAL = 10.0   # 1.0–10.0 → residential, 10.0–35.0 → commercial
_RADIANCE_INDUSTRIAL = 35.0   # > 35.0 → industrial

_SATURATION_VALUE = 60.0   # nW/cm²/sr — ECONOMIC_ACTIVITY_INDEX denominator


# ---------------------------------------------------------------------------
# Internal: grid-point → H3 cell assignment
# ---------------------------------------------------------------------------

def _assign_h3(
    samples: list[dict[str, Any]],
    resolution: int,
) -> dict[str, list[dict[str, Any]]]:
    """Group samples by H3 cell at the given resolution."""
    import h3 as _h3
    cell_map: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        lat, lon = s["lat"], s["lon"]
        cell = _h3.latlng_to_cell(lat, lon, resolution)
        cell_map.setdefault(cell, []).append(s)
    return cell_map


# ---------------------------------------------------------------------------
# Internal: per-cell signal computation
# ---------------------------------------------------------------------------

def _cell_signals(
    samples: list[dict[str, Any]],
) -> tuple[float | None, float | None, float]:
    """Compute mean radiance, mean lit_fraction, and DATA_CONFIDENCE for a cell.

    Excludes no_data samples from the mean.
    Confidence:
      - 0.0 if any sample has "synthetic_fallback" in source_record_id
      - 0.65 if > 10% of samples are cloud_contaminated or void_filled
      - 0.90 otherwise (real VIIRS)

    Returns (radiance_nw, lit_fraction, confidence).
    """
    # Check for synthetic
    is_synthetic = any(
        "synthetic_fallback" in s.get("source_record_id", "")
        for s in samples
    )

    usable_radiance = [
        s["radiance_nw"]
        for s in samples
        if s.get("quality_flag") != "no_data"
        and s.get("radiance_nw") is not None
    ]
    usable_lit = [
        s["lit_fraction"]
        for s in samples
        if s.get("quality_flag") != "no_data"
        and s.get("lit_fraction") is not None
    ]

    if not usable_radiance:
        return None, None, 0.0

    mean_radiance = float(np.mean(usable_radiance))
    mean_lit = float(np.mean(usable_lit)) if usable_lit else None

    if is_synthetic:
        confidence = 0.0
    else:
        cloud_count = sum(
            1 for s in samples
            if s.get("quality_flag") in ("cloud_contaminated", "void_filled")
        )
        if cloud_count / len(samples) > _CLOUD_FRACTION_THRESHOLD:
            confidence = 0.65
        else:
            confidence = 0.90

    return round(mean_radiance, 3), (round(mean_lit, 3) if mean_lit is not None else None), confidence


# ---------------------------------------------------------------------------
# Public: classify_activity — writes ACTIVITY_CLASS for city cells
# ---------------------------------------------------------------------------

def classify_activity(city_id: str) -> int:
    """Classify H3 cells for *city_id* and write ACTIVITY_CLASS to h3_signals.

    Reads NTL_RADIANCE from the store and applies absolute threshold rules:
        dark        NTL_RADIANCE < 1.0 nW
        residential 1.0 <= NTL_RADIANCE < 10.0
        commercial  10.0 <= NTL_RADIANCE < 35.0
        industrial  NTL_RADIANCE >= 35.0

    ACTIVITY_CLASS is stored as an integer ordinal — decode with ACTIVITY_CLASS_LABELS:
        0 dark · 1 residential · 2 commercial · 3 industrial

    Returns the number of ACTIVITY_CLASS rows written.
    """
    from airos.drivers.store.store import H3KnowledgeStore
    from airos.drivers.store.writer import write_signals

    store = H3KnowledgeStore.get()

    df = store.fetchdf(
        """
        SELECT h3_id, signal, value
        FROM   h3_signals
        WHERE  city_id = ?
          AND  domain  = 'nightlights'
          AND  signal  = 'NTL_RADIANCE'
          AND  value   IS NOT NULL
        """,
        [city_id],
    )
    if df is None or df.empty:
        logger.warning(
            "[%s/nightlights] classify_activity: no NTL_RADIANCE found — skipping.",
            city_id,
        )
        return 0

    def _classify_radiance(radiance: float) -> int:
        if radiance >= _RADIANCE_INDUSTRIAL:
            return ACTIVITY_CLASS_ORDINAL["industrial"]
        if radiance >= _RADIANCE_COMMERCIAL:
            return ACTIVITY_CLASS_ORDINAL["commercial"]
        if radiance >= _RADIANCE_DARK:
            return ACTIVITY_CLASS_ORDINAL["residential"]
        return ACTIVITY_CLASS_ORDINAL["dark"]

    signal_rows = []
    for _, row in df.iterrows():
        radiance = float(row["value"])
        ordinal = _classify_radiance(radiance)
        signal_rows.append({
            "h3_id":  row["h3_id"],
            "signal": "ACTIVITY_CLASS",
            "value":  float(ordinal),
            "unit":   ACTIVITY_CLASS_LABELS[ordinal],
        })

    # skip_conformance=True: the classifier writes only ACTIVITY_CLASS as a
    # targeted update — the other 4 signals are already in the store from
    # the NTL ingest. Running the full conformance gate on a single-signal
    # batch would always fail the "all declared signals present" check.
    written = write_signals(
        signal_rows, city_id=city_id, domain="nightlights",
        source="nightlights_classifier", skip_conformance=True,
        geometry_assignment_method="derived",
    )

    counts = {}
    for row in signal_rows:
        label = ACTIVITY_CLASS_LABELS[int(row["value"])]
        counts[label] = counts.get(label, 0) + 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    logger.info(
        "[%s/nightlights] classified %d cells: %s",
        city_id, len(signal_rows), summary,
    )
    return written


# ---------------------------------------------------------------------------
# Public: ingest_nightlights
# ---------------------------------------------------------------------------

def ingest_nightlights(city_id: str, bbox: dict, *, force: bool = False) -> int:
    """Fetch VIIRS NTL samples for the city bbox and write per-cell signals.

    Parameters
    ----------
    city_id : str
    bbox    : dict with keys lat_min, lon_min, lat_max, lon_max
    force   : skip the watermark interval check

    Returns
    -------
    int — number of signal rows written (including ACTIVITY_CLASS rows)
    """
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import write_signals, upsert_metadata, record_ingest
    from airos.drivers.store.geo_agg import cells_for_bbox

    try:
        _check_interval("nightlights", city_id, force)
    except Exception as e:
        logger.info("[%s/nightlights] %s", city_id, e)
        return 0

    logger.info("[%s/nightlights] Fetching VIIRS NTL samples …", city_id)
    samples = fetch_ntl_samples(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
    )

    if not samples:
        logger.warning("[%s/nightlights] No NTL samples returned.", city_id)
        record_ingest(
            city_id=city_id, domain="nightlights", rows_written=0,
            status="partial", error_msg="connector returned empty",
        )
        return 0

    ok_count = sum(1 for s in samples if s.get("quality_flag") == "ok")
    logger.info(
        "[%s/nightlights] %d samples fetched (%d ok). Aggregating to H3 …",
        city_id, len(samples), ok_count,
    )

    # ── Step 1: assign each sample to an H3 cell ────────────────────────────
    cell_samples = _assign_h3(samples, DEFAULT_H3_RES)

    # Ensure every bbox cell is represented (even if no samples fell inside)
    all_cells = cells_for_bbox(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
        DEFAULT_H3_RES,
    )

    # ── Step 2: compute per-cell signals ─────────────────────────────────────
    signal_rows: list[dict] = []

    for h3_id in all_cells:
        cell_samps = cell_samples.get(h3_id, [])

        upsert_metadata(h3_id=h3_id, city_id=city_id, resolution=DEFAULT_H3_RES)

        if not cell_samps:
            # No samples fell in this cell — write nulls so it appears in store
            signal_rows += [
                {"h3_id": h3_id, "signal": "NTL_RADIANCE",           "value": None,  "unit": "nW/cm²/sr"},
                {"h3_id": h3_id, "signal": "NTL_LIT_FRACTION",       "value": None,  "unit": "ratio"},
                {"h3_id": h3_id, "signal": "ECONOMIC_ACTIVITY_INDEX", "value": None,  "unit": "index"},
                {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",         "value": 0.0,   "unit": "ratio"},
            ]
            continue

        radiance, lit_fraction, confidence = _cell_signals(cell_samps)

        if radiance is None:
            signal_rows += [
                {"h3_id": h3_id, "signal": "NTL_RADIANCE",           "value": None,  "unit": "nW/cm²/sr"},
                {"h3_id": h3_id, "signal": "NTL_LIT_FRACTION",       "value": None,  "unit": "ratio"},
                {"h3_id": h3_id, "signal": "ECONOMIC_ACTIVITY_INDEX", "value": None,  "unit": "index"},
                {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",         "value": 0.0,   "unit": "ratio"},
            ]
            continue

        # ECONOMIC_ACTIVITY_INDEX: radiance / saturation, capped at 1.0
        eai = round(min(radiance / _SATURATION_VALUE, 1.0), 4)

        signal_rows += [
            {"h3_id": h3_id, "signal": "NTL_RADIANCE",            "value": radiance,     "unit": "nW/cm²/sr"},
            {"h3_id": h3_id, "signal": "NTL_LIT_FRACTION",        "value": lit_fraction, "unit": "ratio"},
            {"h3_id": h3_id, "signal": "ECONOMIC_ACTIVITY_INDEX", "value": eai,          "unit": "index"},
            {"h3_id": h3_id, "signal": "DATA_CONFIDENCE",         "value": confidence,   "unit": "ratio"},
        ]

    written = write_signals(signal_rows, city_id=city_id, domain="nightlights",
                            source="viirs_black_marble",
                            geometry_assignment_method="raster")
    logger.info(
        "[%s/nightlights] %d cells × 4 signals = %d rows written.",
        city_id, len(all_cells), written,
    )

    # Classify immediately after ingest while the data is fresh.
    classified = classify_activity(city_id)
    logger.info("[%s/nightlights] %d ACTIVITY_CLASS rows written.", city_id, classified)

    record_ingest(city_id=city_id, domain="nightlights",
                  rows_written=written + classified)
    return written + classified
