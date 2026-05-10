"""
AirOS Driver Type Definitions
==============================
Shared types used by the driver Protocol, BaseDriver, and the conformance gate.
These are deliberately minimal — no heavy dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConformanceResult:
    """Return value of H3DataSourceDriver.conformance_check().

    ok       — True if the driver is ready to fetch. False means it must not
               be loaded into the active driver pool.
    failures — Blocking problems (missing env vars, bad config). ok=False when
               this list is non-empty.
    warnings — Non-blocking observations (degraded confidence, optional keys
               missing). ok may still be True.
    """
    ok: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [f"ConformanceResult(ok={self.ok}"]
        if self.failures:
            parts.append(f", failures={self.failures}")
        if self.warnings:
            parts.append(f", warnings={self.warnings}")
        parts.append(")")
        return "".join(parts)


class DriverFetchError(Exception):
    """Raised by H3DataSourceDriver.fetch() on unrecoverable errors.

    The scheduler catches this, logs it, records partial status in
    h3_ingest_log, and moves on to the next domain without crashing.

    For transient errors (network timeouts, rate limits) the driver should
    handle retry internally and only raise DriverFetchError when it has
    exhausted retries.
    """
    def __init__(self, domain: str, city_id: str, message: str) -> None:
        self.domain = domain
        self.city_id = city_id
        super().__init__(f"[{domain}/{city_id}] {message}")


class DriverConformanceError(Exception):
    """Raised by the driver loader when conformance_check() returns ok=False.

    The loader raises this so the calling code can decide whether to abort
    startup (strict mode) or skip the failing driver (permissive mode).
    """
