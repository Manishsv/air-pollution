"""AirOS Network layer — external surfaces (dashboard, API, CLI).

Key exports:
    INetworkSurface     — every surface must implement serve()
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class INetworkSurface(Protocol):
    """Every external surface implements a serve() entry point."""
    def serve(self, **kwargs) -> None: ...
