from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urban_platform.specifications.conformance import SPEC_ROOT


def _catalog_dir() -> Path:
    return (SPEC_ROOT / "examples" / "reference_data").resolve()


def list_reference_catalogs() -> list[dict[str, Any]]:
    d = _catalog_dir()
    if not d.exists() or not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def list_reference_catalog_ids() -> list[str]:
    ids: list[str] = []
    for c in list_reference_catalogs():
        cid = c.get("catalog_id")
        if isinstance(cid, str) and cid.strip():
            ids.append(cid.strip())
    return sorted(set(ids))


def get_reference_catalog(catalog_id: str) -> dict[str, Any] | None:
    cid = str(catalog_id or "").strip()
    if not cid:
        return None
    for c in list_reference_catalogs():
        if str(c.get("catalog_id") or "").strip() == cid:
            return dict(c)
    return None

