from __future__ import annotations

"""
Shared helpers for loading governed specification documents used by the SDK and API.

**Internal (implementation detail):** not part of ``airos.os.sdk.__all__``.
New callers should use descriptor entrypoints such as ``get_app_descriptor`` /
``airos.os.sdk.apps`` or Core API routes, not this module directly
(see ``docs/SDK_SURFACE.md``).

App descriptors are YAML under ``specifications/app_descriptors/``; loading uses safe
parse + optional JSON Schema validation only (no dynamic execution).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from airos.os.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file


def _app_descriptor_specs_dir() -> Path:
    return (SPEC_ROOT / "app_descriptors").resolve()


def load_air_os_app_descriptor_schema_validator():
    """
    Build a JSON Schema validator for AirOS app descriptors.

    Validates descriptor *shape* only. Does not execute builders and does not
    interpret descriptors as dynamic plugins.
    """
    m = load_manifest()
    schema_path = (m.get("artifacts") or {}).get("platform_air_os_app_descriptor", {}).get("schema_path")
    if not schema_path:
        return None
    p = (SPEC_ROOT / str(schema_path)).resolve()
    if not p.exists():
        return None
    return validator_for_schema_file(str(p))


def _is_abs_path_string(s: str) -> bool:
    try:
        return Path(s).is_absolute()
    except Exception:
        return False


def _sanitize_app_descriptor(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the response is safe for API clients:
    - no absolute filesystem paths
    - do not add any runtime-only fields
    """
    out = dict(obj)
    dep = out.get("deployment_examples") or []
    if isinstance(dep, list):
        fixed = []
        for it in dep:
            if not isinstance(it, dict):
                continue
            it2 = dict(it)
            p = it2.get("path")
            if isinstance(p, str) and _is_abs_path_string(p):
                it2["path"] = p.lstrip("/")  # best-effort; still non-absolute
            fixed.append(it2)
        out["deployment_examples"] = fixed
    return out


def load_all_app_descriptors_from_specs(*, validate: bool = True) -> List[Dict[str, Any]]:
    """
    Load all YAML app descriptors from ``specifications/app_descriptors/``.

    - Safe parsing only (yaml.safe_load).
    - Optional JSON Schema validation for shape (default on).
    - Returns descriptors as dicts.
    - Fails safely (returns []) if directory missing.
    """
    d = _app_descriptor_specs_dir()
    if not d.exists() or not d.is_dir():
        return []

    v = load_air_os_app_descriptor_schema_validator() if validate else None
    out: List[Dict[str, Any]] = []
    for p in sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml"))):
        try:
            with open(p, encoding="utf-8") as f:
                obj = yaml.safe_load(f)
            if not isinstance(obj, dict):
                continue
            if v is not None:
                v.validate(obj)
            out.append(_sanitize_app_descriptor(obj))
        except Exception:
            continue
    return out


def get_app_descriptor_from_specs(app_id: str, *, validate: bool = True) -> Optional[Dict[str, Any]]:
    aid = str(app_id or "").strip()
    if not aid:
        return None
    for d in load_all_app_descriptors_from_specs(validate=validate):
        if str(d.get("app_id") or "").strip() == aid:
            return d
    return None
