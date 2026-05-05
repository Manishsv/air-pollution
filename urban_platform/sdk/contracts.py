from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from urban_platform.specifications.conformance import SPEC_ROOT, load_manifest
from urban_platform.specifications.runtime_validation import validate_artifact


class ValidationErrorSummary(TypedDict):
    path: str
    message: str
    schema: str


def list_contract_keys() -> list[str]:
    m = load_manifest()
    arts = m.get("artifacts") or {}
    return sorted([k for k in arts.keys() if isinstance(k, str)])


def contract_exists(contract_key: str) -> bool:
    ck = str(contract_key or "").strip()
    if not ck:
        return False
    m = load_manifest()
    arts = m.get("artifacts") or {}
    return ck in arts


def get_contract_schema(contract_key: str) -> dict[str, Any]:
    """
    Return the JSON Schema object registered for ``contract_key`` in the manifest.

    Raises:
      - KeyError if contract_key not found
      - ValueError if schema_path missing or contract is not JSON-schema-backed
      - FileNotFoundError / JSONDecodeError for schema file errors
    """
    ck = str(contract_key or "").strip()
    m = load_manifest()
    arts = m.get("artifacts") or {}
    if ck not in arts:
        raise KeyError(f"Unknown contract_key {ck!r} (not in manifest).")
    meta = arts.get(ck) or {}
    rel = meta.get("schema_path")
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(f"Artifact {ck!r} is not schema-backed (missing schema_path).")
    if str(meta.get("contract_type") or "") == "openapi":
        raise ValueError(f"Artifact {ck!r} is an OpenAPI stub, not a JSON schema contract.")

    p = (SPEC_ROOT / rel).resolve()
    with open(p, encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("Schema JSON must be an object.")
    return obj


def validate_payload(contract_key: str, payload: dict) -> list[ValidationErrorSummary]:
    """
    Validate ``payload`` against the contract schema for ``contract_key``.

    Returns a list of error summaries. Empty list means valid.
    """
    ck = str(contract_key or "").strip()
    if not ck:
        return [{"path": "$", "message": "contract_key is required", "schema": "<none>"}]
    if not isinstance(payload, dict):
        return [{"path": "$", "message": "payload must be an object/dict", "schema": ck}]

    try:
        res = validate_artifact(ck, payload)
    except KeyError:
        return [{"path": "$", "message": f"Unknown contract_key {ck!r} (not in manifest).", "schema": ck}]
    except Exception as exc:  # noqa: BLE001
        return [{"path": "$", "message": str(exc), "schema": ck}]

    errs = res.get("errors") or []
    out: list[ValidationErrorSummary] = []
    if isinstance(errs, list):
        for e in errs:
            if not isinstance(e, dict):
                continue
            out.append(
                {
                    "path": str(e.get("path") or "$"),
                    "message": str(e.get("message") or ""),
                    "schema": str(e.get("schema") or ck),
                }
            )
    return out

