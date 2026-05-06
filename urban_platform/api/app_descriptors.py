from __future__ import annotations

from typing import Any, Dict, List

from urban_platform.sdk.specs_helpers import (
    get_app_descriptor_from_specs,
    load_air_os_app_descriptor_schema_validator,
    load_all_app_descriptors_from_specs,
)


_load_descriptor_schema_validator = load_air_os_app_descriptor_schema_validator


def load_all_app_descriptors(*, validate: bool = True) -> List[Dict[str, Any]]:
    """
    Load all YAML app descriptors from `specifications/app_descriptors/`.

    - Safe parsing only (yaml.safe_load).
    - Optional JSON Schema validation for shape (default on).
    - Returns descriptors as dicts.
    - Fails safely (returns []) if directory missing.
    """
    return load_all_app_descriptors_from_specs(validate=validate)


def get_app_descriptor(app_id: str, *, validate: bool = True) -> Dict[str, Any] | None:
    return get_app_descriptor_from_specs(app_id, validate=validate)


def build_app_summaries(descriptors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Summarize descriptors for GET /apps.
    """
    items: List[Dict[str, Any]] = []
    for d in descriptors:
        dl = d.get("decision_logic") if isinstance(d.get("decision_logic"), dict) else {}
        items.append(
            {
                "app_id": d.get("app_id"),
                "name": d.get("name"),
                "version": d.get("version"),
                "status": d.get("status"),
                "domain_id": d.get("domain_id"),
                "app_type": d.get("app_type"),
                "description": d.get("description"),
                "input_contracts": d.get("input_contracts") or [],
                "output_contracts": d.get("output_contracts") or [],
                "decision_logic": {"builder_ids": (dl.get("builder_ids") if isinstance(dl, dict) else []) or []},
                "deployment_examples": d.get("deployment_examples") or [],
                "dashboard": d.get("dashboard") or {},
                "safety": d.get("safety") or {},
            }
        )
    return items
