"""AirOS Apps layer — domain application logic.

Key exports:
    AppProtocol         — every domain app implements run_pipeline()
    DecisionPacket      — typed dict for decision outputs
"""
from __future__ import annotations
from typing import Any, Protocol, TypedDict, runtime_checkable


class DecisionPacket(TypedDict, total=False):
    packet_id: str
    spatial_unit_id: str
    city_id: str
    domain: str
    risk_level: str
    confidence_score: float
    field_verification_required: bool
    evidence: dict
    recommendations: list[dict]


@runtime_checkable
class AppProtocol(Protocol):
    """Every domain app exposes a pipeline entry point."""
    def run_pipeline(self, bbox: dict, city_id: str, **kwargs) -> dict: ...
