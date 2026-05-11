"""AirOS Agents layer — AI analysis agents.

Key exports:
    AgentProtocol       — every agent implements analyse()
    Insight             — typed dict for agent insight outputs
"""
from __future__ import annotations
from typing import Any, Protocol, TypedDict, runtime_checkable


class Insight(TypedDict, total=False):
    h3_id: str
    city_id: str
    domain: str
    risk_level: str
    summary: str
    recommended_actions: list[str]
    confidence: float
    analysis_timestamp: str


@runtime_checkable
class AgentProtocol(Protocol):
    """Every analysis agent exposes an analyse method."""
    def analyse(self, cell: dict, context: dict) -> Insight: ...
