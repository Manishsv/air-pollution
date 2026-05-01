from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator
from jsonschema.validators import RefResolver

# air_quality_mvp/urban_platform/specifications/conformance.py -> parents[2] == air_quality_mvp
_MVP_ROOT = Path(__file__).resolve().parents[2]
SPEC_ROOT = _MVP_ROOT / "specifications"
MANIFEST_PATH = SPEC_ROOT / "manifest.json"


def schema_dir(version: str = "v1") -> Path:
    return SPEC_ROOT / "json_schema" / version


def load_manifest() -> dict[str, Any]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def iter_manifest_schema_paths(version: str = "v1") -> Iterator[tuple[str, Path]]:
    """Yield (artifact_name, schema_path) from manifest."""
    m = load_manifest()
    base = SPEC_ROOT
    for name, meta in (m.get("artifacts") or {}).items():
        rel = (meta or {}).get("schema_path")
        if not rel:
            continue
        yield name, (base / rel).resolve()


@lru_cache(maxsize=32)
def validator_for_schema_file(schema_path: str) -> Draft202012Validator:
    """
    Build a validator, resolving relative ``$ref`` against sibling schema files.

    Draft 2020-12 resolves relative ``$ref`` URIs against the referrer schema's ``$id``
    (not only the file directory). We preload all ``*.schema.json`` in the same folder
    into the resolver store under both ``file:.../name`` and each document's ``$id``.
    """
    p = Path(schema_path).resolve()
    schema = json.loads(p.read_text(encoding="utf-8"))
    base_uri = p.parent.as_uri() + "/"
    store: dict[str, Any] = {}
    for sib in sorted(p.parent.glob("*.schema.json")):
        doc = json.loads(sib.read_text(encoding="utf-8"))
        store[base_uri + sib.name] = doc
        sid = doc.get("$id")
        if isinstance(sid, str) and sid:
            store[sid] = doc
    resolver = RefResolver(base_uri=base_uri, referrer=schema, store=store)
    return Draft202012Validator(schema, resolver=resolver)


def assert_conforms(instance: Any, *, schema_name: str, version: str = "v1") -> None:
    """
    Validate ``instance`` against the schema registered in ``manifest.json`` for ``schema_name``.

    ``schema_name`` is the manifest key (e.g. ``decision_packet``, ``data_audit``).
    """
    m = load_manifest()
    artifacts = m.get("artifacts") or {}
    if schema_name not in artifacts:
        raise KeyError(f"Unknown artifact {schema_name!r} in specifications/manifest.json")
    rel = artifacts[schema_name]["schema_path"]
    path = (SPEC_ROOT / rel).resolve()
    v = validator_for_schema_file(str(path))
    v.validate(instance)
