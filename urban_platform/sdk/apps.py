from __future__ import annotations

from typing import Any, Dict, List, Optional

from urban_platform.api.app_descriptors import get_app_descriptor as _get_app_descriptor
from urban_platform.api.app_descriptors import load_all_app_descriptors as _load_all_app_descriptors


def list_app_descriptors() -> list[dict[str, Any]]:
    return list(_load_all_app_descriptors(validate=True))


def list_app_ids() -> list[str]:
    out: list[str] = []
    for d in list_app_descriptors():
        aid = d.get("app_id")
        if isinstance(aid, str) and aid.strip():
            out.append(aid.strip())
    return sorted(set(out))


def get_app_descriptor(app_id: str) -> dict[str, Any] | None:
    d = _get_app_descriptor(app_id, validate=True)
    return dict(d) if isinstance(d, dict) else None

