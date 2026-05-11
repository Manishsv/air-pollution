"""AirOS OS layer — runtime contracts, storage, config, scheduling.

Key exports (Protocol / ABC level):
    IStore              — read/write interface for any storage backend
    IContractValidator  — validates data against domain specs
    IDeploymentConfig   — deployment-level settings (city, environment)
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class IStore(Protocol):
    """Minimal storage interface every backend must satisfy."""
    def read(self, key: str) -> object: ...
    def write(self, key: str, value: object) -> None: ...


@runtime_checkable
class IContractValidator(Protocol):
    def validate(self, data: dict, schema_id: str) -> list[str]: ...


@runtime_checkable
class IDeploymentConfig(Protocol):
    city_id: str
    environment: str  # "dev" | "staging" | "prod"
