from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from urban_platform.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file


def _descriptor_dir() -> Path:
    return (SPEC_ROOT / "app_descriptors").resolve()


def _load_descriptor_schema_validator():
    """
    Build a JSON Schema validator for AirOS app descriptors.

    This validates descriptor *shape* only. It does not execute builders and does not
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


def _sanitize_descriptor(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the response is safe for API clients:
    - no absolute filesystem paths
    - do not add any runtime-only fields
    """
    out = dict(obj)
    # Guard deployment_examples[].path from being absolute (should always be repo-relative).
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


def load_all_app_descriptors(*, validate: bool = True) -> List[Dict[str, Any]]:
    """
    Load all YAML app descriptors from `specifications/app_descriptors/`.

    - Safe parsing only (yaml.safe_load).
    - Optional JSON Schema validation for shape (default on).
    - Returns descriptors as dicts.
    - Fails safely (returns []) if directory missing.
    """
    d = _descriptor_dir()
    if not d.exists() or not d.is_dir():
        return []

    v = _load_descriptor_schema_validator() if validate else None
    out: List[Dict[str, Any]] = []
    for p in sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml"))):
        try:
            with open(p, encoding="utf-8") as f:
                obj = yaml.safe_load(f)
            if not isinstance(obj, dict):
                continue
            if v is not None:
                v.validate(obj)
            out.append(_sanitize_descriptor(obj))
        except Exception:
            # Fail closed per-file; do not break discovery endpoint for one bad descriptor.
            continue
    return out


def get_app_descriptor(app_id: str, *, validate: bool = True) -> Optional[Dict[str, Any]]:
    aid = str(app_id or "").strip()
    if not aid:
        return None
    for d in load_all_app_descriptors(validate=validate):
        if str(d.get("app_id") or "").strip() == aid:
            return d
    return None


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

