"""
AirOS BaseDriver
================
Concrete base class for in-tree AirOS drivers. Third-party drivers may
subclass this or implement H3DataSourceDriver directly without inheriting.

BaseDriver provides:
  - Default implementations of the optional Protocol fields
  - Shared _check_interval() watermark logic (calls ingestor._check_interval)
  - A default conformance_check() that validates required env vars

Subclasses must implement:
  - domain     (class attribute or property)
  - cadence_hours (class attribute or property)
  - produces_assessments (class attribute or property)
  - fetch(city_id, bbox, *, force=False) -> int

Subclasses should override:
  - signal_names   (list the signals fetch() writes)
  - data_sources   (human-readable upstream source list)
  - _required_env_vars (list of env var names conformance_check() validates)
"""
from __future__ import annotations

import logging
import os
from typing import ClassVar

from airos.os.sdk.driver_types import ConformanceResult, DriverFetchError  # noqa: F401

logger = logging.getLogger(__name__)


class BaseDriver:
    """Abstract base for AirOS domain drivers.

    Satisfies H3DataSourceDriver Protocol when domain, cadence_hours,
    produces_assessments, fetch(), and conformance_check() are defined.
    """

    # ------------------------------------------------------------------ #
    # Subclass must define these                                           #
    # ------------------------------------------------------------------ #

    #: Machine-readable domain name — must be unique in the deployment.
    domain: ClassVar[str]

    #: Minimum hours between fetches (0.25 = 15 min, 1.0 = hourly, etc.)
    cadence_hours: ClassVar[float]

    #: True if this driver writes h3_assessments rows.
    produces_assessments: ClassVar[bool]

    # ------------------------------------------------------------------ #
    # Subclass should override these                                       #
    # ------------------------------------------------------------------ #

    #: Canonical signal names written to h3_signals. Include DATA_CONFIDENCE.
    signal_names: ClassVar[list[str]] = []

    #: Human-readable upstream data source descriptions.
    data_sources: ClassVar[list[str]] = []

    #: Env var names required for this driver to operate.
    #: conformance_check() returns ok=False if any are absent.
    _required_env_vars: ClassVar[list[str]] = []

    # ------------------------------------------------------------------ #
    # Watermark guard                                                      #
    # ------------------------------------------------------------------ #

    def _check_interval(self, city_id: str, force: bool) -> None:
        """Raise _TooRecentError if the domain was ingested too recently.

        Delegates to ingestor._check_interval() which reads h3_ingest_log.
        BaseDriver drivers call this at the top of fetch() before pulling data.
        """
        from airos.drivers.store.ingestor import (
            _check_interval as _ingestor_check,
        )
        _ingestor_check(self.domain, city_id, force)

    # ------------------------------------------------------------------ #
    # Conformance                                                          #
    # ------------------------------------------------------------------ #

    def conformance_check(self) -> ConformanceResult:
        """Default conformance: verify all _required_env_vars are set.

        Override this in subclasses to add driver-specific checks (e.g.
        config file exists, credential format is valid, signals.yaml
        matches signal_names).
        """
        failures = []
        warnings = []

        for var in self._required_env_vars:
            val = os.getenv(var)
            if not val:
                failures.append(f"Required env var {var!r} is not set")

        if not self.signal_names:
            warnings.append(
                f"Driver {self.domain!r} declares no signal_names — "
                "conformance gate cannot validate output columns"
            )

        return ConformanceResult(ok=len(failures) == 0, failures=failures, warnings=warnings)

    # ------------------------------------------------------------------ #
    # Repr                                                                 #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} domain={self.domain!r} "
            f"cadence={self.cadence_hours}h>"
        )
