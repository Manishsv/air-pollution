from __future__ import annotations

from typing import Any, Dict, List

from airos.os.specifications.conformance import (
    SPEC_ROOT,
    load_manifest,
    validator_for_schema_file,
)


def manifest_has_artifact(schema_name: str) -> bool:
    """True if ``schema_name`` is a key in ``specifications/manifest.json`` artifacts."""
    m = load_manifest()
    artifacts = m.get("artifacts") or {}
    return str(schema_name or "").strip() in artifacts


def collect_validation_errors(instance: Any, *, schema_name: str, version: str = "v1") -> List[Dict[str, Any]]:
    """
    Validate ``instance`` against the manifest-registered schema for ``schema_name``.

    Returns a stable, JSON-serializable list of issues (empty if valid).
    Reuses manifest resolution and cached validators from conformance utilities.
    """
    del version  # manifest paths are relative to specifications/ today
    m = load_manifest()
    artifacts = m.get("artifacts") or {}
    if schema_name not in artifacts:
        return [{"message": f"Unknown manifest artifact key: {schema_name!r}"}]
    rel = (artifacts[schema_name] or {}).get("schema_path")
    if not rel:
        return [{"message": f"Manifest artifact {schema_name!r} has no schema_path"}]
    path = (SPEC_ROOT / str(rel)).resolve()
    if not path.is_file():
        return [{"message": f"Schema file missing: {path}"}]
    v = validator_for_schema_file(str(path))
    out: List[Dict[str, Any]] = []
    for err in sorted(v.iter_errors(instance), key=lambda e: (list(e.path), str(e.message))):
        out.append(
            {
                "message": err.message,
                "path": [str(x) for x in err.absolute_path],
            }
        )
    return out
