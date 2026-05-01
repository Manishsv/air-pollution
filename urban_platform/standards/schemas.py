from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ObservationSchema:
    required_columns: List[str]


@dataclass(frozen=True)
class EntitySchema:
    required_columns: List[str]


@dataclass(frozen=True)
class FeatureSchema:
    required_columns: List[str]


@dataclass(frozen=True)
class EventSchema:
    required_columns: List[str]


SCHEMAS: Dict[str, Any] = {
    "Observation": ObservationSchema(
        required_columns=[
            "observation_id",
            "entity_id",
            "observed_property",
            "value",
            "unit",
            "timestamp",
            "source",
            "quality_flag",
        ]
    ),
    "Entity": EntitySchema(
        required_columns=[
            "entity_id",
            "entity_type",
            "geometry",
            "attributes",
            "source",
            "confidence",
        ]
    ),
    "Feature": FeatureSchema(
        required_columns=[
            "feature_id",
            "spatial_unit_id",
            "feature_name",
            "value",
            "unit",
            "source",
            "confidence",
        ]
    ),
    "Event": EventSchema(
        required_columns=[
            "event_id",
            "event_type",
            "spatial_unit_id",
            "timestamp",
            "severity",
            "confidence",
            "recommended_action",
        ]
    ),
}


def observation_required_columns() -> List[str]:
    return list(SCHEMAS["Observation"].required_columns)


def empty_observations() -> "Any":
    import pandas as pd

    return pd.DataFrame(columns=observation_required_columns())


def normalize_quality_flag(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    if v in {"", "unknown", "unavailable"}:
        return "unknown"
    if v in {"good", "ok", "pass"}:
        return "ok"
    if v in {"bad", "fail"}:
        return "bad"
    if v in {"synthetic"}:
        return "synthetic"
    return v

