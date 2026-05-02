from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from urban_platform.decision_support.explainability import sanitize_for_json
from urban_platform.specifications.audit import (
    audit_api_responses,
    audit_domain_specs,
    audit_examples,
    audit_manifest,
    audit_output_artifacts,
    audit_schema_validity,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outputs_dir(base_path: Path | str) -> Path:
    return Path(base_path).resolve() / "data" / "outputs"


def _artifact_key_from_path(path_str: str) -> str | None:
    # Some rows use a fragment suffix like ".../decision_packets.json#items".
    name = Path(str(path_str).split("#", 1)[0]).name
    if name == "decision_packets.json":
        return "decision_packets"
    if name == "data_audit.json":
        return "data_audit"
    if name == "metrics.json":
        return "metrics"
    if name == "source_reliability.json":
        return "source_reliability"
    if name == "scale_analysis.json":
        return "scale_analysis"
    return None


def _build_artifacts_block_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Convert audit-style rows into the runtime-facing ``artifacts`` block consumed by the dashboard.

    This keeps backward compatibility with the earlier runtime report schema:

    {
      "artifacts": {
        "decision_packets": { "status", "core_schema_status", "profile_schema_status", "error_count", "errors", ... },
        "metrics": { ... },
        ...
      }
    }
    """
    artifacts: dict[str, Any] = {}

    # initialize entries from file-level rows
    for r in results:
        art_key = _artifact_key_from_path(str(r.get("artifact_or_api") or ""))
        if not art_key:
            continue
        # Ignore item-level rows for decision_packets; we assemble those below.
        if art_key == "decision_packets" and str(r.get("artifact_or_api") or "").endswith("#items"):
            continue

        artifacts[art_key] = {
            "status": r.get("status"),
            "schema": r.get("schema_name"),
            "profile": None,
            "core_schema_status": "n/a",
            "profile_schema_status": "n/a",
            "error_count": int(r.get("error_count") or 0),
            "errors": r.get("errors") or [],
        }

    # decision_packets: merge array validation + item-level core/profile validations
    arr_row = None
    core_row = None
    prof_row = None
    for r in results:
        base = str(r.get("artifact_or_api") or "").split("#", 1)[0]
        if Path(base).name != "decision_packets.json":
            continue
        if str(r.get("schema_name")) == "decision_packets" and not str(r.get("artifact_or_api") or "").endswith("#items"):
            arr_row = r
        elif str(r.get("schema_name")) == "urban_decision_packet_core" and str(r.get("artifact_or_api") or "").endswith("#items"):
            core_row = r
        elif str(r.get("schema_name")) == "decision_packet_air_quality" and str(r.get("artifact_or_api") or "").endswith("#items"):
            prof_row = r

    if arr_row is not None:
        errors: list[dict[str, Any]] = []
        errors.extend(arr_row.get("errors") or [])
        if core_row is not None:
            errors.extend(core_row.get("errors") or [])
        if prof_row is not None:
            errors.extend(prof_row.get("errors") or [])

        core_status = core_row.get("status") if core_row is not None else "skipped"
        prof_status = prof_row.get("status") if prof_row is not None else "skipped"
        overall_ok = str(arr_row.get("status")) == "valid" and str(core_status) == "valid" and str(prof_status) == "valid"

        artifacts["decision_packets"] = {
            "status": "valid" if overall_ok else ("skipped" if str(arr_row.get("status")) == "skipped" else "invalid"),
            "schema": "decision_packets",
            "profile": "air_quality",
            "core_schema_status": "valid" if str(core_status) == "valid" else ("skipped" if str(core_status) == "skipped" else "invalid"),
            "profile_schema_status": "valid"
            if str(prof_status) == "valid"
            else ("skipped" if str(prof_status) == "skipped" else "invalid"),
            "error_count": len(errors),
            "errors": errors,
        }

    return artifacts


def list_conformance_result_violations(results: list[dict[str, Any]] | None) -> list[str]:
    """
    Inspect row-wise conformance ``results`` and return human-readable violation lines.

    Rows with ``status == "skipped"`` are treated as optional (e.g. missing runtime artifacts or
    empty API paths) and do **not** produce violations.

    Any other row must have ``status == "valid"`` and ``error_count == 0``; otherwise a violation
    is recorded (covers ``invalid`` rows and inconsistent valid+errors).
    """
    violations: list[str] = []
    for idx, row in enumerate(results or []):
        if not isinstance(row, dict):
            violations.append(f"results[{idx}]: row is not an object ({type(row).__name__})")
            continue
        status_raw = row.get("status")
        status = str(status_raw or "").strip().lower()
        try:
            ec = int(row.get("error_count") or 0)
        except (TypeError, ValueError):
            ec = -1
        if status == "skipped":
            continue
        if status == "valid" and ec == 0:
            continue
        artifact = row.get("artifact_or_api") or "?"
        schema = row.get("schema_name") or "?"
        ct = row.get("contract_type") or "?"
        violations.append(
            f"{artifact} | contract_type={ct} schema={schema} status={status_raw!r} error_count={ec}"
        )
    return violations


def run_conformance(
    base_path: Path | str,
    *,
    mode: str = "full",  # "full" (schemas+manifest+outputs+api) | "runtime" (outputs only)
) -> dict[str, Any]:
    """
    Unified conformance engine.

    - ``mode="runtime"``: fast validation for pipeline runs (output artifacts only)
    - ``mode="full"``: full audit (schemas, manifest, artifacts, and local API/SDK responses)

    Always writes:
      <base_path>/data/outputs/conformance_report.json

    Report schema (single shape for both modes):

    {
      "validated_at": "...",
      "mode": "runtime"|"full",
      "artifacts": { ... runtime-facing artifact summary ... },
      "results": [ ... row-wise checks ... ]
    }
    """
    validated_at = _now()
    out_dir = _outputs_dir(base_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    if mode not in {"runtime", "full"}:
        raise ValueError(f"Unknown conformance mode: {mode!r}")

    if mode == "full":
        results.extend(audit_schema_validity(validated_at=validated_at))
        results.extend(audit_domain_specs(validated_at=validated_at))
        results.extend(audit_examples(validated_at=validated_at))
        results.extend(audit_manifest(validated_at=validated_at))

    results.extend(audit_output_artifacts(base_path=base_path, validated_at=validated_at))

    if mode == "full":
        results.extend(audit_api_responses(base_path=base_path, validated_at=validated_at))

    report: dict[str, Any] = {
        "validated_at": validated_at,
        "mode": mode,
        "artifacts": _build_artifacts_block_from_results(results),
        "results": results,
    }

    path = out_dir / "conformance_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sanitize_for_json(report), f, indent=2, default=str, allow_nan=False)

    return report

