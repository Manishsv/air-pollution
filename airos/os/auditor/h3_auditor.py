"""H3 data auditor — checks raw ingest quality and signal distributions.

Checks run in three layers:
  1. Ingest layer    — staleness, zero-row runs, conformance failures
  2. Signal layer    — constant values, all-zero, out-of-range, missing declared signals
  3. Coverage layer  — domains with no assessment rows despite produces_assessments=True

Results are written to audit_issues in the SQLite knowledge store.
Re-running resolves previously detected issues that no longer fire.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

Severity = Literal["error", "warning", "info"]

# Staleness thresholds per domain (hours). Domains not listed use the default.
_STALE_HOURS: dict[str, float] = {
    "air":           3.0,
    "flood":         2.0,
    "heat":          6.0,
    "weather":       3.0,
    "crowd":        24.0,   # camera pipeline runs infrequently
    "fire":         12.0,
    "construction": 48.0,
    "green":        72.0,
    "nightlights": 168.0,   # weekly
    "roads":       168.0,
    "terrain":     720.0,   # monthly
    "buildings":   720.0,
    "drains":      720.0,
}
_DEFAULT_STALE_HOURS = 24.0

# Expected value ranges for key signals. (signal → (min, max))
_SIGNAL_RANGES: dict[str, tuple[float, float]] = {
    "PM25":                      (0.0,  1000.0),
    "AQI":                       (0.0,   500.0),
    "DATA_CONFIDENCE":           (0.0,     1.0),
    "HEAT_RISK_SCORE":           (0.0,     1.0),
    "LST":                       (-20.0, 70.0),
    "UHI":                       (-10.0, 15.0),
    "FLOOD_RISK_SCORE":          (0.0,     1.0),
    "RAINFALL":                  (0.0,   500.0),
    "GREEN_COVER_CHANGE_INDEX":  (-1.0,    1.0),
    "ROAD_DENSITY":              (0.0, 200_000.0),
    "CONSTRUCTION_RISK_INDEX":   (0.0,     1.0),
    "NOISE_RISK_INDEX":          (0.0,     1.0),
    "OPTICAL_WATER_CLARITY_INDEX": (0.0,   1.0),
    "WASTE_RISK_INDEX":          (0.0,     1.0),
    "NTL_RADIANCE":              (0.0, 10_000.0),
    "TEMPERATURE_C":             (-20.0,  60.0),
    "HUMIDITY_PCT":              (0.0,   100.0),
    "ELEVATION_M":               (-500.0, 9000.0),
    "SLOPE_DEG":                 (0.0,    90.0),
    "CROWD_DENSITY":             (0.0, 100_000.0),
    "FRP":                       (0.0,  10_000.0),
}

# Signals that are meaningless if stuck constant across all cells
# (value, tolerance) — if stdev < tolerance × |mean| the signal is flagged
_CONSTANT_SIGNALS: set[str] = {
    "UHI", "HEAT_RISK_SCORE", "LST", "PM25", "AQI",
    "FLOOD_RISK_SCORE", "ROAD_DENSITY",
}

# Signals legitimately zero in dry/calm conditions — skip all_zero check
_ALLOW_ZERO: set[str] = {
    "RAINFALL", "PRECIP_MM", "FRP", "BURN_FRP_MW", "WASTE_FRP",
    "GATHERING_ALERT",
}

# Domains where 0 rows written is normal (event-driven; no events = no rows).
# declared_signals_absent is also suppressed for these — primary signals only
# appear during active events (fires, crowd gatherings).
_EVENT_DRIVEN_DOMAINS: set[str] = {"fire", "crowd", "waste"}


@dataclass
class AuditIssue:
    city_id:    str
    check_name: str
    message:    str
    severity:   Severity = "warning"
    domain:     str = ""
    h3_id:      str | None = None
    detail:     dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "issue_id":    str(uuid.uuid4()),
            "city_id":     self.city_id,
            "domain":      self.domain,
            "h3_id":       self.h3_id,
            "check_name":  self.check_name,
            "severity":    self.severity,
            "message":     self.message,
            "detail_json": json.dumps(self.detail) if self.detail else None,
            "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


class H3DataAuditor:
    """Run all audit checks for one or more cities and persist findings."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from airos.drivers.store.schema import DB_PATH
            db_path = str(DB_PATH)
        self._db = db_path

    # ── Public entry point ────────────────────────────────────────────────

    def run(self, city_ids: list[str] | None = None) -> list[AuditIssue]:
        """Run all checks; persist results; return issue list."""
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        try:
            if city_ids is None:
                city_ids = [r[0] for r in conn.execute(
                    "SELECT DISTINCT city_id FROM h3_ingest_log"
                ).fetchall()]

            issues: list[AuditIssue] = []
            for city_id in city_ids:
                logger.info("[auditor] Auditing city=%s …", city_id)
                # Build set of domains with active conformance warnings explaining absence
                warned_domains = self._conformance_warned_domains(city_id)
                issues += self._check_ingest_staleness(conn, city_id)
                issues += self._check_conformance_failures(conn, city_id)
                issues += self._check_zero_row_runs(conn, city_id)
                issues += self._check_signal_distributions(conn, city_id)
                issues += self._check_assessment_coverage(conn, city_id, warned_domains)
                issues += self._check_declared_signals_present(conn, city_id, warned_domains)

            self._persist(conn, city_ids, issues)
            logger.info("[auditor] %d issue(s) detected across %d city(ies).",
                        len(issues), len(city_ids))
            return issues
        finally:
            conn.close()

    def _conformance_warned_domains(self, city_id: str) -> set[str]:
        """Domains that have conformance warnings explaining why signals are absent.

        These are domains where the driver's conformance_check() raised a warning
        (e.g. 'observation store not found', 'API key not set') that explains
        why no data was ingested. We suppress declared_signals_absent and
        missing_assessments for these domains to avoid noise.
        """
        try:
            from airos.os.sdk.driver_loader import load_drivers
            drivers = load_drivers("data/config/drivers_registry.yaml")
        except Exception:
            return set()
        warned = set()
        for domain, driver in drivers.items():
            try:
                result = driver.conformance_check()
                if result.warnings:
                    warned.add(domain)
            except Exception:
                pass
        return warned

    # ── Check: ingest staleness ───────────────────────────────────────────

    def _check_ingest_staleness(self, conn, city_id: str) -> list[AuditIssue]:
        rows = conn.execute(
            "SELECT domain, last_ingested_at, rows_written, status "
            "FROM h3_ingest_log WHERE city_id = ?", (city_id,)
        ).fetchall()
        issues = []
        now = datetime.now(timezone.utc)
        for r in rows:
            domain = r["domain"]
            threshold = _STALE_HOURS.get(domain, _DEFAULT_STALE_HOURS)
            try:
                last = datetime.fromisoformat(
                    r["last_ingested_at"].replace("Z", "+00:00")
                )
            except Exception:
                continue
            age_h = (now - last).total_seconds() / 3600.0
            if age_h > threshold:
                sev: Severity = "error" if age_h > threshold * 3 else "warning"
                issues.append(AuditIssue(
                    city_id=city_id, domain=domain,
                    check_name="ingest_staleness",
                    severity=sev,
                    message=(
                        f"{domain}: last ingested {age_h:.1f}h ago "
                        f"(threshold {threshold:.0f}h)"
                    ),
                    detail={"age_hours": round(age_h, 1),
                            "threshold_hours": threshold,
                            "last_ingested_at": r["last_ingested_at"]},
                ))
        return issues

    # ── Check: conformance failures ───────────────────────────────────────

    def _check_conformance_failures(self, conn, city_id: str) -> list[AuditIssue]:
        rows = conn.execute(
            "SELECT domain, conformance_ok, conformance_failures "
            "FROM h3_ingest_log WHERE city_id = ? AND conformance_ok = 0",
            (city_id,)
        ).fetchall()
        issues = []
        for r in rows:
            failures = []
            try:
                failures = json.loads(r["conformance_failures"] or "[]")
            except Exception:
                pass
            issues.append(AuditIssue(
                city_id=city_id, domain=r["domain"],
                check_name="conformance_failure",
                severity="error",
                message=f"{r['domain']}: conformance gate failed — {len(failures)} failure(s)",
                detail={"failures": failures},
            ))
        return issues

    # ── Check: zero-row runs ──────────────────────────────────────────────

    def _check_zero_row_runs(self, conn, city_id: str) -> list[AuditIssue]:
        rows = conn.execute(
            "SELECT domain, rows_written, status, error_msg "
            "FROM h3_ingest_log "
            "WHERE city_id = ? AND rows_written = 0 AND status != 'partial'",
            (city_id,)
        ).fetchall()
        issues = []
        for r in rows:
            if r["domain"] in _EVENT_DRIVEN_DOMAINS:
                continue  # 0 rows is normal when no events are occurring
            issues.append(AuditIssue(
                city_id=city_id, domain=r["domain"],
                check_name="zero_rows_written",
                severity="warning",
                message=f"{r['domain']}: last ingest wrote 0 rows (status={r['status']})",
                detail={"error_msg": r["error_msg"]},
            ))
        return issues

    # ── Check: signal distributions ───────────────────────────────────────

    def _check_signal_distributions(self, conn, city_id: str) -> list[AuditIssue]:
        # One query per domain to get per-signal stats from the latest hour_bucket
        domains = [r[0] for r in conn.execute(
            "SELECT DISTINCT domain FROM h3_signals WHERE city_id = ?", (city_id,)
        ).fetchall()]
        issues = []
        for domain in domains:
            rows = conn.execute("""
                SELECT signal,
                       COUNT(*) as n,
                       MIN(value)  as vmin,
                       MAX(value)  as vmax,
                       AVG(value)  as vmean,
                       SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) as nulls
                FROM h3_signals
                WHERE city_id = ? AND domain = ?
                  AND hour_bucket = (
                      SELECT MAX(hour_bucket) FROM h3_signals
                      WHERE city_id = ? AND domain = ?
                  )
                GROUP BY signal
            """, (city_id, domain, city_id, domain)).fetchall()

            for r in rows:
                sig = r["signal"]
                n, vmin, vmax, vmean = r["n"], r["vmin"], r["vmax"], r["vmean"]
                null_count = r["nulls"]

                # Null rate
                null_rate = null_count / n if n > 0 else 0.0
                if null_rate > 0.2:
                    issues.append(AuditIssue(
                        city_id=city_id, domain=domain,
                        check_name="high_null_rate",
                        severity="warning" if null_rate < 0.5 else "error",
                        message=(
                            f"{domain}/{sig}: {null_rate*100:.0f}% null values "
                            f"({null_count}/{n} cells)"
                        ),
                        detail={"null_count": null_count, "total_cells": n,
                                "null_rate": round(null_rate, 3)},
                    ))

                if vmin is None or vmax is None:
                    continue

                # Constant-value detection (stdev ≈ 0)
                if sig in _CONSTANT_SIGNALS and n >= 10:
                    spread = vmax - vmin
                    if spread < 1e-6:
                        issues.append(AuditIssue(
                            city_id=city_id, domain=domain,
                            check_name="constant_signal",
                            severity="error",
                            message=(
                                f"{domain}/{sig}: all {n} cells have identical value "
                                f"{vmean:.4f} — likely a pipeline bug"
                            ),
                            detail={"value": vmean, "n_cells": n},
                        ))

                # Out-of-range
                if sig in _SIGNAL_RANGES:
                    lo, hi = _SIGNAL_RANGES[sig]
                    if vmin < lo or vmax > hi:
                        issues.append(AuditIssue(
                            city_id=city_id, domain=domain,
                            check_name="out_of_range",
                            severity="error",
                            message=(
                                f"{domain}/{sig}: values [{vmin:.3g}, {vmax:.3g}] "
                                f"outside expected [{lo}, {hi}]"
                            ),
                            detail={"vmin": vmin, "vmax": vmax,
                                    "expected_min": lo, "expected_max": hi},
                        ))

                # All-zero check — skip signals that are legitimately zero in calm/dry conditions
                if sig not in {"DATA_CONFIDENCE"} | _ALLOW_ZERO and vmax == 0.0 and n >= 10:
                    issues.append(AuditIssue(
                        city_id=city_id, domain=domain,
                        check_name="all_zero",
                        severity="warning",
                        message=f"{domain}/{sig}: all {n} cells are zero",
                        detail={"n_cells": n},
                    ))

        return issues

    # ── Check: assessment coverage ────────────────────────────────────────

    def _check_assessment_coverage(self, conn, city_id: str,
                                   warned_domains: set[str] | None = None) -> list[AuditIssue]:
        try:
            from airos.os.sdk.driver_loader import load_drivers
            drivers = load_drivers("data/config/drivers_registry.yaml")
        except Exception:
            return []

        warned_domains = warned_domains or set()
        issues = []
        for domain, driver in drivers.items():
            if not getattr(driver, "produces_assessments", False):
                continue
            if domain in warned_domains:
                continue  # conformance warning explains absence
            count = conn.execute(
                "SELECT COUNT(*) FROM h3_assessments "
                "WHERE city_id = ? AND domain = ?", (city_id, domain)
            ).fetchone()[0]
            if count == 0:
                issues.append(AuditIssue(
                    city_id=city_id, domain=domain,
                    check_name="missing_assessments",
                    severity="warning",
                    message=(
                        f"{domain}: driver produces assessments but none found "
                        f"in h3_assessments for {city_id}"
                    ),
                    detail={},
                ))
        return issues

    # ── Check: declared signals present ──────────────────────────────────

    def _check_declared_signals_present(self, conn, city_id: str,
                                        warned_domains: set[str] | None = None) -> list[AuditIssue]:
        try:
            from airos.os.sdk.driver_loader import load_drivers
            drivers = load_drivers("data/config/drivers_registry.yaml")
        except Exception:
            return []

        warned_domains = warned_domains or set()
        issues = []
        for domain, driver in drivers.items():
            if domain in warned_domains or domain in _EVENT_DRIVEN_DOMAINS:
                continue  # conformance warning or event-driven — absence is expected
            declared = set(getattr(driver, "signal_names", []))
            if not declared:
                continue
            stored = {r[0] for r in conn.execute(
                "SELECT DISTINCT signal FROM h3_signals "
                "WHERE city_id = ? AND domain = ?", (city_id, domain)
            ).fetchall()}
            missing = declared - stored
            if missing:
                issues.append(AuditIssue(
                    city_id=city_id, domain=domain,
                    check_name="declared_signals_absent",
                    severity="warning",
                    message=(
                        f"{domain}: declared signal(s) never stored: "
                        f"{sorted(missing)}"
                    ),
                    detail={"missing": sorted(missing), "stored": sorted(stored)},
                ))
        return issues

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self, conn, city_ids: list[str], issues: list[AuditIssue]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Resolve all previous open issues for these cities that didn't re-fire
        fired_keys = {(i.city_id, i.domain, i.check_name) for i in issues}
        for city_id in city_ids:
            existing = conn.execute(
                "SELECT issue_id, domain, check_name FROM audit_issues "
                "WHERE city_id = ? AND resolved_at IS NULL",
                (city_id,)
            ).fetchall()
            for row in existing:
                key = (city_id, row["domain"], row["check_name"])
                if key not in fired_keys:
                    conn.execute(
                        "UPDATE audit_issues SET resolved_at = ? WHERE issue_id = ?",
                        (now, row["issue_id"])
                    )

        # Upsert new/re-fired issues:
        # delete old unresolved matching (city, domain, check_name) then insert fresh
        for issue in issues:
            conn.execute(
                "DELETE FROM audit_issues "
                "WHERE city_id = ? AND domain = ? AND check_name = ? "
                "  AND resolved_at IS NULL",
                (issue.city_id, issue.domain, issue.check_name)
            )
            row = issue.to_row()
            conn.execute(
                "INSERT INTO audit_issues "
                "(issue_id, city_id, domain, h3_id, check_name, severity, "
                " message, detail_json, detected_at) "
                "VALUES (:issue_id, :city_id, :domain, :h3_id, :check_name, "
                ":severity, :message, :detail_json, :detected_at)",
                row
            )
        conn.commit()
