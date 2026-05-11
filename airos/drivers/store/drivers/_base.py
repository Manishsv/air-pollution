"""
Shared base for in-tree driver wrappers.

Each in-tree driver wraps an existing _ingest_* function from ingestor.py in
a class that satisfies the H3DataSourceDriver Protocol. This is the Phase 1/3
migration layer — no ingest logic is duplicated here.

Phase 2 will move each driver's logic into its own package; at that point
these thin wrappers disappear and the driver class becomes the primary entry
point.
"""
from __future__ import annotations

from airos.os.sdk.base_driver import BaseDriver
from airos.os.sdk.driver_types import ConformanceResult


class _InTreeDriver(BaseDriver):
    """Base for thin wrappers around existing _ingest_* functions."""

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        raise NotImplementedError(
            f"{type(self).__name__} must implement fetch()"
        )

    def conformance_check(self) -> ConformanceResult:
        """Default: check env vars declared in _required_env_vars."""
        return super().conformance_check()
