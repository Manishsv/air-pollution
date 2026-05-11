"""
AirOS Data Source Driver Protocol
===================================
Stable interface that every AirOS domain driver — in-tree or third-party —
must satisfy.

**Stability contract:** once 1.0.0 ships, this Protocol is stable.
  - Adding optional properties → minor version bump
  - Renaming/removing/changing signatures → major version bump + migration guide

Third-party driver authors: implement this Protocol directly, or subclass
BaseDriver (airos.os.sdk.base_driver) which provides sensible defaults
for the optional fields and shared watermark logic.

Usage
-----
    from airos.os.sdk.driver_protocol import H3DataSourceDriver
    from airos.os.sdk.driver_types import ConformanceResult

    class MyDriver:
        domain = "my_domain"
        cadence_hours = 1.0
        produces_assessments = True
        signal_names = ["MY_SIGNAL", "DATA_CONFIDENCE"]
        data_sources = ["https://api.example.com"]

        def fetch(self, city_id, bbox, *, force=False):
            ...
            return rows_written

        def conformance_check(self):
            import os
            if not os.getenv("MY_API_KEY"):
                return ConformanceResult(ok=False, failures=["MY_API_KEY not set"])
            return ConformanceResult(ok=True)

    # Runtime check (works because @runtime_checkable):
    assert isinstance(MyDriver(), H3DataSourceDriver)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from airos.os.sdk.driver_types import ConformanceResult


@runtime_checkable
class H3DataSourceDriver(Protocol):
    """Stable AirOS driver interface.

    Any object that exposes these attributes and methods satisfies the Protocol.
    No inheritance required.
    """

    # ------------------------------------------------------------------ #
    # Identity — required, must be set at class level or as properties    #
    # ------------------------------------------------------------------ #

    @property
    def domain(self) -> str:
        """Machine-readable domain name.

        Must be unique across all drivers active in a deployment.
        Examples: 'air', 'flood', 'openaq_v2', 'pune_noise_sensors'.

        Convention: use underscores, lowercase ASCII. Prefer the canonical
        AirOS domain name ('air', 'flood', etc.) when you are implementing
        an alternate source for an existing domain — use a suffix like
        'air_iqair' when multiple air drivers coexist.
        """
        ...

    @property
    def cadence_hours(self) -> float:
        """Minimum hours between fetches.

        The scheduler will not call fetch() more frequently than this.
        Use 0.25 for 15-minute cadence, 0.5 for 30 minutes, etc.
        The watermark check lives in BaseDriver._check_interval(); override
        fetch() and skip the check if the upstream API is push-based.
        """
        ...

    @property
    def produces_assessments(self) -> bool:
        """True if this driver writes h3_assessments rows (risk levels).

        Structural drivers (buildings, roads, drains, weather) set this to
        False — they provide context signals only and do not generate alerts.
        The scheduler uses this to skip the assessment reporting step.
        """
        ...

    # ------------------------------------------------------------------ #
    # Core fetch — required                                               #
    # ------------------------------------------------------------------ #

    def fetch(
        self,
        city_id: str,
        bbox: dict,
        *,
        force: bool = False,
    ) -> int:
        """Pull data, compute H3 signals, write to the Knowledge Store.

        Parameters
        ----------
        city_id : str
            City identifier (e.g. 'bangalore'). Used as the partition key
            in all Knowledge Store tables.
        bbox : dict
            Bounding box: {'lat_min', 'lon_min', 'lat_max', 'lon_max'}.
        force : bool
            If True, ignore the watermark and re-fetch unconditionally.
            Used by --force CLI flag and test harnesses.

        Returns
        -------
        int
            Number of signal rows written to h3_signals. Zero is valid —
            it means no new data was available (e.g. satellite not yet
            revisited, API returned empty). Never negative.

        Raises
        ------
        DriverFetchError
            On unrecoverable errors after exhausting internal retries.
            The scheduler will catch this, log it, and move on.

        Contract
        --------
        - Idempotent: calling fetch() twice for the same city/hour must
          not produce duplicate rows. Use the h3_signals upsert keys
          (h3_id, city_id, domain, signal, hour_bucket).
        - Must call record_ingest() at the end (success or partial).
        - Must respect the watermark unless force=True.
        - Must not raise on transient errors (retry internally).
        """
        ...

    # ------------------------------------------------------------------ #
    # Conformance — required                                              #
    # ------------------------------------------------------------------ #

    def conformance_check(self) -> ConformanceResult:
        """Validate the driver's static configuration without a live fetch.

        Called once at load time by the driver loader. Must complete quickly
        (< 1 second) — do not make live API calls here.

        Check:
        - Required environment variables are set (not necessarily valid)
        - Required config files exist and are parseable
        - signal_names declared matches what fetch() actually writes
          (check against signals.yaml if you ship one)

        Return ConformanceResult(ok=False, failures=[...]) for blocking
        problems. The loader will not activate a driver that fails here.
        Return ConformanceResult(ok=True, warnings=[...]) for non-blocking
        issues (optional API key missing, degraded confidence expected).
        """
        ...

    # ------------------------------------------------------------------ #
    # Metadata — optional (BaseDriver provides defaults)                  #
    # ------------------------------------------------------------------ #

    @property
    def signal_names(self) -> list[str]:
        """Canonical signal names this driver writes to h3_signals.

        Used by:
        - The conformance gate to verify output columns
        - The H3 Expert Agent system prompt (knows what signals to expect)
        - The dashboard panel (knows what to query)

        Always include 'DATA_CONFIDENCE' if you write it (all drivers should).
        """
        ...

    @property
    def data_sources(self) -> list[str]:
        """Human-readable list of upstream data sources.

        Shown in dashboard provenance labels and evidence bundles.
        Examples: ['OpenMeteo API (no key required)', 'CPCB sensor network']
        """
        ...
