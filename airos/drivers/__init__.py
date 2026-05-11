"""AirOS Drivers layer — data integration contracts.

Key exports:
    DriverProtocol      — every connector must implement fetch()
    ISignalWriter       — writes raw signals to the H3 store
    IAssessmentReader   — reads assessments from the H3 store
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class DriverProtocol(Protocol):
    """Every domain data connector implements this interface."""
    def fetch(self, bbox: dict, **kwargs) -> object: ...


@runtime_checkable
class ISignalWriter(Protocol):
    def write_signals(self, rows: list[dict], *, city_id: str, domain: str) -> int: ...


@runtime_checkable
class IAssessmentReader(Protocol):
    def read_assessments(self, city_id: str, domain: str, limit: int) -> list[dict]: ...
