from __future__ import annotations

from typing import Any

from urban_platform.sdk.specs_helpers import (
    get_app_descriptor_from_specs,
    load_all_app_descriptors_from_specs,
)


def list_app_descriptors() -> list[dict[str, Any]]:
    return list(load_all_app_descriptors_from_specs(validate=True))


def list_app_ids() -> list[str]:
    out: list[str] = []
    for d in list_app_descriptors():
        aid = d.get("app_id")
        if isinstance(aid, str) and aid.strip():
            out.append(aid.strip())
    return sorted(set(out))


def get_app_descriptor(app_id: str) -> dict[str, Any] | None:
    d = get_app_descriptor_from_specs(app_id, validate=True)
    return dict(d) if isinstance(d, dict) else None
