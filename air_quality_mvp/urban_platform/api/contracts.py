from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Tuple

import pandas as pd


BBox = Tuple[float, float, float, float]  # west, south, east, north (WGS84)


@dataclass(frozen=True)
class PlatformApiContracts:
    """
    Function-level API contracts for the platform.

    This is intentionally server-agnostic: implementations may be local-file based,
    database-backed, or served over HTTP in the future.
    """

    class Entities(Protocol):
        def __call__(self, entity_type: Optional[str] = None, bbox: Optional[BBox] = None) -> pd.DataFrame: ...

    class Observations(Protocol):
        def __call__(
            self,
            variable: Optional[str] = None,
            grid_id: Optional[str] = None,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
        ) -> pd.DataFrame: ...

    class Features(Protocol):
        def __call__(
            self,
            feature_name: Optional[str] = None,
            grid_id: Optional[str] = None,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
        ) -> pd.DataFrame: ...

    class Events(Protocol):
        def __call__(
            self,
            event_type: Optional[str] = None,
            severity: Optional[str] = None,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
        ) -> pd.DataFrame: ...

    class Recommendations(Protocol):
        def __call__(self, grid_id: Optional[str] = None, min_confidence: Optional[float] = None) -> pd.DataFrame: ...

    class DecisionPackets(Protocol):
        def __call__(
            self,
            h3_id: Optional[str] = None,
            min_confidence: Optional[float] = None,
            recommendation_allowed: Optional[bool] = None,
            category: Optional[str] = None,
        ) -> list[dict]: ...

    class DecisionPacket(Protocol):
        def __call__(self, packet_id: str) -> Optional[dict]: ...

    class SourceReliability(Protocol):
        def __call__(
            self,
            entity_id: Optional[str] = None,
            variable: Optional[str] = None,
            status: Optional[str] = None,
        ) -> pd.DataFrame: ...

