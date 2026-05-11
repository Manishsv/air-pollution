"""
AirOS Runtime Conformance Gate
================================
Validates driver signal output before it is written to the H3 Knowledge Store.

Rules
-----
BLOCKING (write is rejected if violated):
  1. DATA_CONFIDENCE must be present for every distinct h3_id in the batch.
     A cell without DATA_CONFIDENCE cannot be used for weighted reasoning.
     A single DATA_CONFIDENCE row covering one cell does NOT satisfy this
     requirement for other cells in the same batch.
  3. h3_id values that are not valid H3 resolution-8 cells.
     Wrong resolution means the cell cannot join with assessments or neighbours.
     The entire batch is rejected if any non-resolution-8 cell is found.

NON-BLOCKING (warning logged, write proceeds):
  2. Any signal name declared in driver.signal_names that appears in zero rows.
     Could be legitimately absent for a given city/hour (no events, cloudy sky)
     but worth flagging so operators know the driver is partially reporting.
  4. signal values that are None/NaN — these rows are skipped by write_signals.

Usage
-----
Call validate_signal_rows() before or after write_signals(). The conformance
gate does not modify the rows — it only reports. The caller decides whether
to block (on failures) or continue (on warnings only).

    from airos.os.sdk.conformance import validate_signal_rows
    result = validate_signal_rows(rows, driver=my_driver)
    if not result.ok:
        logger.error("Blocked: %s", result.failures)
        return 0
    # proceed to write_signals(rows, ...)

Integration
-----------
write_signals() in writer.py calls _maybe_validate() which looks up the active
driver for the domain and runs this gate automatically. Callers that call
write_signals() directly get conformance checking for free.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

from airos.os.sdk.driver_types import ConformanceResult

if TYPE_CHECKING:
    from airos.os.sdk.driver_protocol import H3DataSourceDriver

logger = logging.getLogger(__name__)

# H3 resolution to check for. All AirOS signals must be at res 8.
_EXPECTED_H3_RES = 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_signal_ranges(driver: "H3DataSourceDriver") -> dict[str, tuple[float, float]]:
    """Return {signal_name: (min, max)} from the driver's signals.yaml, if available.

    Used by Rule 5 to check value range violations. Returns an empty dict if
    the driver has no signals.yaml or if PyYAML is not installed.
    """
    ranges: dict[str, tuple[float, float]] = {}
    try:
        import yaml
        import inspect
        signals_yaml: str | None = getattr(driver, "signals_yaml_path", None)
        if signals_yaml is None:
            driver_file = inspect.getfile(type(driver))
            candidate = Path(driver_file).parent / "signals.yaml"
            if candidate.exists():
                signals_yaml = str(candidate)
        if signals_yaml and Path(signals_yaml).exists():
            with open(signals_yaml, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for sig in data.get("signals", []):
                name = sig.get("name")
                rng  = sig.get("range")
                if name and isinstance(rng, (list, tuple)) and len(rng) == 2:
                    try:
                        ranges[name] = (float(rng[0]), float(rng[1]))
                    except (TypeError, ValueError):
                        pass
    except ImportError:
        pass  # PyYAML not installed — Rule 5 is skipped silently
    except Exception:
        pass
    return ranges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_signal_rows(
    rows: list[dict],
    *,
    driver: "H3DataSourceDriver | None" = None,
    domain: str | None = None,
) -> ConformanceResult:
    """Check a list of signal rows (as passed to write_signals) for conformance.

    Parameters
    ----------
    rows : list[dict]
        Each dict must contain at least 'h3_id', 'signal', 'value'.
    driver : H3DataSourceDriver | None
        If provided, declared signal_names are cross-checked against rows.
    domain : str | None
        Used for logging context when driver is not provided.

    Returns
    -------
    ConformanceResult
        ok=False if any BLOCKING rule is violated.
        ok=True with warnings if only non-blocking rules fire.
        ok=True with no messages if all checks pass.
    """
    domain_tag = domain or (driver.domain if driver else "unknown")
    failures: list[str] = []
    warnings: list[str] = []

    if not rows:
        warnings.append(f"[{domain_tag}] zero rows submitted — no signals to validate")
        return ConformanceResult(ok=True, warnings=warnings)

    # Collect per-cell signal names, all h3_ids, and null count
    # cell_signals: h3_id -> set of signal names written for that cell
    cell_signals: dict[str, set[str]] = {}
    null_value_count = 0

    for row in rows:
        h3id = row.get("h3_id")
        sig = row.get("signal")
        if h3id and sig:
            cell_signals.setdefault(h3id, set()).add(sig)
        val = row.get("value")
        if val is None or (isinstance(val, float) and math.isnan(val)):
            null_value_count += 1

    h3_ids_present = set(cell_signals.keys())
    signal_names_present: set[str] = set().union(*cell_signals.values()) if cell_signals else set()

    # ── BLOCKING RULE 1: DATA_CONFIDENCE must be present for every cell ───
    cells_missing_dc = [
        h3id for h3id, sigs in cell_signals.items()
        if "DATA_CONFIDENCE" not in sigs
    ]
    if cells_missing_dc:
        sample = cells_missing_dc[:3]
        failures.append(
            f"[FAIL] [{domain_tag}] DATA_CONFIDENCE signal is absent for "
            f"{len(cells_missing_dc)} h3_id(s) (sample: {sample}). "
            "Every cell written must have a DATA_CONFIDENCE row so downstream "
            "reasoning can weight signals by reliability."
        )

    # ── NON-BLOCKING RULE 2: declared signals missing from rows ──────────
    if driver and driver.signal_names:
        declared = set(driver.signal_names)
        missing = declared - signal_names_present
        if missing:
            warnings.append(
                f"[WARN] [{domain_tag}] Declared signal(s) absent from rows: "
                f"{sorted(missing)}. May be legitimate (no events this hour) "
                "or a driver bug."
            )

    # ── BLOCKING RULE 3: H3 resolution must be 8 ─────────────────────────
    wrong_res: list[str] = []
    for h3_id in h3_ids_present:
        res = _h3_resolution(h3_id)
        if res is not None and res != _EXPECTED_H3_RES:
            wrong_res.append(h3_id)
    if wrong_res:
        sample = wrong_res[:3]
        failures.append(
            f"[FAIL] [{domain_tag}] {len(wrong_res)} h3_id(s) are not resolution "
            f"{_EXPECTED_H3_RES} (sample: {sample}). "
            "All signals must be written at H3 resolution 8."
        )

    # ── NON-BLOCKING RULE 4: null values ─────────────────────────────────
    if null_value_count > 0:
        warnings.append(
            f"[WARN] [{domain_tag}] {null_value_count}/{len(rows)} rows have null/NaN value. "
            "These rows will be skipped by write_signals()."
        )

    # ── NON-BLOCKING RULE 5: value range violations ───────────────────────
    if driver:
        signal_ranges = _load_signal_ranges(driver)
        if signal_ranges:
            # Collect out-of-range values per signal
            range_violations: dict[str, list] = {}
            for row in rows:
                sig = row.get("signal")
                val = row.get("value")
                if sig and val is not None and sig in signal_ranges:
                    if not (isinstance(val, float) and math.isnan(val)):
                        lo, hi = signal_ranges[sig]
                        if not (lo <= float(val) <= hi):
                            range_violations.setdefault(sig, []).append(round(float(val), 4))
            for sig, bad_vals in range_violations.items():
                lo, hi = signal_ranges[sig]
                sample = bad_vals[:3]
                warnings.append(
                    f"[WARN] [{domain_tag}] {len(bad_vals)} row(s) for signal {sig!r} have "
                    f"values outside declared range [{lo}, {hi}] (sample: {sample})."
                )

    ok = len(failures) == 0
    return ConformanceResult(ok=ok, failures=failures, warnings=warnings)


def validate_and_log(
    rows: list[dict],
    *,
    driver: "H3DataSourceDriver | None" = None,
    domain: str | None = None,
) -> ConformanceResult:
    """Run validation and emit log entries for failures and warnings.

    Returns the ConformanceResult so the caller can decide whether to block.
    """
    result = validate_signal_rows(rows, driver=driver, domain=domain)

    for msg in result.failures:
        logger.error("Conformance FAIL: %s", msg)
    for msg in result.warnings:
        logger.warning("Conformance WARN: %s", msg)

    return result


# ---------------------------------------------------------------------------
# H3 resolution helper
# ---------------------------------------------------------------------------

def _h3_resolution(h3_id: str) -> int | None:
    """Return the H3 resolution of a cell string, or None if unparseable."""
    try:
        import h3
        return h3.get_resolution(h3_id)
    except Exception:
        return None
