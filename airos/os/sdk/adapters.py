from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from airos.os.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file


def _descriptor_dir() -> Path:
    return (SPEC_ROOT / "provider_adapters").resolve()


def _load_descriptor_schema_validator():
    m = load_manifest()
    schema_path = (m.get("artifacts") or {}).get("platform_provider_adapter_descriptor", {}).get("schema_path")
    if not schema_path:
        return None
    p = (SPEC_ROOT / str(schema_path)).resolve()
    if not p.exists():
        return None
    return validator_for_schema_file(str(p))


def _sanitize_descriptor(obj: Dict[str, Any]) -> Dict[str, Any]:
    # Provider adapter descriptors should not contain filesystem paths; keep as-is,
    # but ensure we never inject local absolute paths.
    return dict(obj)


def list_provider_adapter_descriptors() -> list[dict[str, Any]]:
    d = _descriptor_dir()
    if not d.exists() or not d.is_dir():
        return []

    v = _load_descriptor_schema_validator()
    out: list[dict[str, Any]] = []
    for p in sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml"))):
        try:
            obj = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                continue
            if v is not None:
                v.validate(obj)
            out.append(_sanitize_descriptor(obj))
        except Exception:
            continue
    return out


def list_provider_adapter_ids() -> list[str]:
    ids: list[str] = []
    for d in list_provider_adapter_descriptors():
        aid = d.get("adapter_id")
        if isinstance(aid, str) and aid.strip():
            ids.append(aid.strip())
    return sorted(set(ids))


def get_provider_adapter_descriptor(adapter_id: str) -> dict[str, Any] | None:
    aid = str(adapter_id or "").strip()
    if not aid:
        return None
    for d in list_provider_adapter_descriptors():
        if str(d.get("adapter_id") or "").strip() == aid:
            return dict(d)
    return None

