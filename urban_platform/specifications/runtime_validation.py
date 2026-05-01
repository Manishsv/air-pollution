from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from urban_platform.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file

logger = logging.getLogger(__name__)


def _outputs_dir(base_path: Path | str) -> Path:
    return Path(base_path).resolve() / "data" / "outputs"


def _validator_for_manifest_key(schema_key: str) -> Any:
    m = load_manifest()
    artifacts = m.get("artifacts") or {}
    if schema_key not in artifacts:
        raise KeyError(f"Unknown schema manifest key: {schema_key!r}")
    rel = artifacts[schema_key]["schema_path"]
    path = (SPEC_ROOT / rel).resolve()
    return validator_for_schema_file(str(path))


def _collect_errors(validator: Any, instance: Any, *, schema_key: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for e in validator.iter_errors(instance):
        path = "$"
        try:
            parts = list(e.absolute_path)
            if parts:
                path = "/" + "/".join(str(p) for p in parts)
        except Exception:
            path = "$"
        errors.append({"path": path, "message": e.message, "schema": schema_key})
    return errors


def validate_artifact(schema_name: str, data: Any) -> dict[str, Any]:
    """
    Validate ``data`` against the JSON Schema registered in ``manifest.json`` under ``schema_name``.

    Returns ``{"status": "valid"|"invalid", "schema_name", "error_count", "errors"}``.
    """
    v = _validator_for_manifest_key(schema_name)
    errs = _collect_errors(v, data, schema_key=schema_name)
    return {
        "status": "valid" if not errs else "invalid",
        "schema_name": schema_name,
        "error_count": len(errs),
        "errors": errs,
    }


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    """Returns (data, load_error_message). data is None if file missing."""
    if not path.exists():
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _single_file_artifact(
    *,
    out_dir: Path,
    file_name: str,
    manifest_schema_key: str,
) -> dict[str, Any]:
    path = out_dir / file_name
    data, load_err = _load_json(path)
    if data is None and load_err is None:
        return {
            "status": "skipped",
            "schema": manifest_schema_key,
            "profile": None,
            "core_schema_status": "n/a",
            "profile_schema_status": "n/a",
            "error_count": 0,
            "errors": [],
        }
    if load_err is not None:
        return {
            "status": "invalid",
            "schema": manifest_schema_key,
            "profile": None,
            "core_schema_status": "n/a",
            "profile_schema_status": "n/a",
            "error_count": 1,
            "errors": [{"path": "$", "message": load_err, "schema": manifest_schema_key}],
        }
    v = _validator_for_manifest_key(manifest_schema_key)
    errs = _collect_errors(v, data, schema_key=manifest_schema_key)
    st = "valid" if not errs else "invalid"
    return {
        "status": st,
        "schema": manifest_schema_key,
        "profile": None,
        "core_schema_status": "n/a",
        "profile_schema_status": "n/a",
        "error_count": len(errs),
        "errors": errs,
    }


def _validate_decision_packets(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "decision_packets.json"
    data, load_err = _load_json(path)
    if data is None and load_err is None:
        return {
            "status": "skipped",
            "schema": "decision_packets",
            "profile": "air_quality",
            "core_schema_status": "skipped",
            "profile_schema_status": "skipped",
            "error_count": 0,
            "errors": [],
        }
    if load_err is not None:
        return {
            "status": "invalid",
            "schema": "decision_packets",
            "profile": "air_quality",
            "core_schema_status": "skipped",
            "profile_schema_status": "skipped",
            "error_count": 1,
            "errors": [{"path": "$", "message": load_err, "schema": "decision_packets"}],
        }
    if not isinstance(data, list):
        return {
            "status": "invalid",
            "schema": "decision_packets",
            "profile": "air_quality",
            "core_schema_status": "skipped",
            "profile_schema_status": "skipped",
            "error_count": 1,
            "errors": [{"path": "$", "message": "decision_packets.json must be a JSON array", "schema": "decision_packets"}],
        }

    errors: list[dict[str, Any]] = []
    v_arr = _validator_for_manifest_key("decision_packets")
    arr_errs = _collect_errors(v_arr, data, schema_key="decision_packets")
    errors.extend(arr_errs)
    array_ok = not arr_errs

    v_core = _validator_for_manifest_key("urban_decision_packet_core")
    v_aq = _validator_for_manifest_key("decision_packet_air_quality")

    core_ok = True
    profile_ok = True
    for i, pkt in enumerate(data):
        if not isinstance(pkt, dict):
            errors.append({"path": f"/{i}", "message": "Packet must be an object", "schema": "decision_packets", "packet_index": i})
            core_ok = False
            profile_ok = False
            continue
        ce = _collect_errors(v_core, pkt, schema_key="urban_decision_packet_core")
        pe = _collect_errors(v_aq, pkt, schema_key="decision_packet_air_quality")
        for e in ce:
            e["packet_index"] = i
            errors.append(e)
        for e in pe:
            e["packet_index"] = i
            errors.append(e)
        if ce:
            core_ok = False
        if pe:
            profile_ok = False

    overall = array_ok and core_ok and profile_ok
    return {
        "status": "valid" if overall else "invalid",
        "schema": "decision_packets",
        "profile": "air_quality",
        "core_schema_status": "valid" if core_ok else "invalid",
        "profile_schema_status": "valid" if profile_ok else "invalid",
        "error_count": len(errors),
        "errors": errors,
    }


def validate_output_artifacts(base_path: Path | str) -> dict[str, Any]:
    """
    Validate standard output JSON under ``<base_path>/data/outputs/`` and write ``conformance_report.json``.

    ``base_path`` is the project root (same as SDK / pipeline ``project_root``).
    """
    # Backward-compatible entrypoint: runtime mode uses the unified engine and keeps the same top-level keys
    # required by the dashboard and SDK (`validated_at`, `artifacts`).
    from urban_platform.specifications.engine import run_conformance

    return run_conformance(base_path, mode="runtime")
