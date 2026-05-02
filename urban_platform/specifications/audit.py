from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from jsonschema import Draft202012Validator
import yaml

from urban_platform.decision_support.explainability import sanitize_for_json
from urban_platform.specifications.conformance import SPEC_ROOT, load_manifest, validator_for_schema_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outputs_dir(base_path: Path | str) -> Path:
    return Path(base_path).resolve() / "data" / "outputs"


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _contract_type_for(schema_name: str) -> str | None:
    m = load_manifest()
    meta = (m.get("artifacts") or {}).get(schema_name) or {}
    ct = meta.get("contract_type")
    return str(ct) if ct is not None else None


def _collect_validator_errors(validator: Any, instance: Any, *, schema_name: str) -> list[dict[str, Any]]:
    errs: list[dict[str, Any]] = []
    for e in validator.iter_errors(instance):
        path = "$"
        try:
            parts = list(e.absolute_path)
            if parts:
                path = "/" + "/".join(str(p) for p in parts)
        except Exception:
            path = "$"
        errs.append({"path": path, "message": e.message, "schema": schema_name})
    return errs


def _report_row(
    *,
    validated_at: str,
    artifact_or_api: str,
    schema_name: str,
    contract_type: str | None,
    status: str,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    es = errors or []
    return {
        "artifact_or_api": artifact_or_api,
        "schema_name": schema_name,
        "contract_type": contract_type,
        "status": status,
        "error_count": len(es),
        "errors": es,
        "validated_at": validated_at,
    }


def _iter_schema_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_dir():
            yield from sorted(p.glob("*.schema.json"))


def audit_schema_validity(*, validated_at: str) -> list[dict[str, Any]]:
    """
    Validate that all schema files are:
    - valid JSON
    - valid Draft 2020-12 JSON Schema documents
    """
    rows: list[dict[str, Any]] = []
    schema_dirs = [
        SPEC_ROOT / "provider_contracts",
        SPEC_ROOT / "platform_objects",
        SPEC_ROOT / "consumer_contracts",
        SPEC_ROOT / "network_contracts",
    ]
    for schema_path in _iter_schema_files(schema_dirs):
        artifact_or_api = f"schema_file:{schema_path.relative_to(SPEC_ROOT)}"
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(doc)
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(schema_path.name),
                    contract_type="schema_file",
                    status="valid",
                )
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(schema_path.name),
                    contract_type="schema_file",
                    status="invalid",
                    errors=[{"path": "$", "message": str(exc), "schema": str(schema_path.name)}],
                )
            )
    return rows


def _validate_domain_spec_yaml(path: Path) -> list[str]:
    """
    Lightweight structure check for domain spec YAML stubs.

    This is intentionally minimal: it does not enforce semantics, only presence of required top-level keys.
    """
    required_keys = [
        "domain_id",
        "version",
        "status",
        "purpose",
        "target_actors",
        "supported_decisions",
        "canonical_entities",
        "observations",
        "features",
        "allowed_variables",
        "units",
        "thresholds_or_categories",
        "safety_gates",
        "provenance_requirements",
        "source_reliability_requirements",
        "decision_packet_profile",
        "dashboard_consumer_requirements",
        "human_review_prompts",
        "field_verification_requirements",
        "blocked_uses",
        "open_questions",
    ]
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return ["Domain spec must be a YAML mapping/object at the top level"]
    missing = [k for k in required_keys if k not in doc]
    errs: list[str] = []
    if missing:
        errs.append(f"Missing required top-level keys: {missing}")
    if doc.get("version") not in {"v1"}:
        errs.append("version must be 'v1' for *.v1.yaml stubs")
    return errs


def audit_domain_specs(*, validated_at: str) -> list[dict[str, Any]]:
    """
    Validate that domain specs exist and follow the required top-level structure.
    """
    rows: list[dict[str, Any]] = []
    dom_dir = SPEC_ROOT / "domain_specs"
    if not dom_dir.exists():
        return rows
    for p in sorted(dom_dir.glob("*.v1.yaml")):
        artifact_or_api = f"domain_spec:{p.relative_to(SPEC_ROOT)}"
        try:
            problems = _validate_domain_spec_yaml(p)
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(p.name),
                    contract_type="domain_spec",
                    status="valid" if not problems else "invalid",
                    errors=[{"path": "$", "message": msg, "schema": str(p.name)} for msg in problems],
                )
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(p.name),
                    contract_type="domain_spec",
                    status="invalid",
                    errors=[{"path": "$", "message": str(exc), "schema": str(p.name)}],
                )
            )
    return rows


def audit_examples(*, validated_at: str) -> list[dict[str, Any]]:
    """
    Validate example/fixture JSON files registered in specifications/manifest.json.

    Examples are required to stay in sync with the schemas they illustrate.
    """
    rows: list[dict[str, Any]] = []
    m = load_manifest()
    examples = m.get("examples") or {}
    arts = m.get("artifacts") or {}
    for ex_name, meta in examples.items():
        schema_name = (meta or {}).get("schema_name")
        rel_path = (meta or {}).get("path")
        errors: list[dict[str, Any]] = []
        if not schema_name:
            errors.append({"path": "$.schema_name", "message": "Missing schema_name", "schema": str(ex_name)})
        if not rel_path:
            errors.append({"path": "$.path", "message": "Missing path", "schema": str(ex_name)})

        artifact_or_api = f"example:{ex_name}"
        if errors:
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(schema_name or ex_name),
                    contract_type="example",
                    status="invalid",
                    errors=errors,
                )
            )
            continue

        ex_path = (SPEC_ROOT / str(rel_path)).resolve()
        if not ex_path.exists():
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(schema_name),
                    contract_type="example",
                    status="invalid",
                    errors=[{"path": "$.path", "message": f"Missing file: {rel_path}", "schema": str(ex_name)}],
                )
            )
            continue

        if str(schema_name) not in arts:
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=artifact_or_api,
                    schema_name=str(schema_name),
                    contract_type="example",
                    status="invalid",
                    errors=[{"path": "$.schema_name", "message": f"Unknown schema_name in manifest artifacts: {schema_name}", "schema": str(ex_name)}],
                )
            )
            continue

        data, load_err = _read_json(ex_path)
        if load_err is not None:
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=str(ex_path),
                    schema_name=str(schema_name),
                    contract_type="example",
                    status="invalid",
                    errors=[{"path": "$", "message": load_err, "schema": str(schema_name)}],
                )
            )
            continue

        schema_rel = arts[str(schema_name)]["schema_path"]
        v = validator_for_schema_file(str((SPEC_ROOT / schema_rel).resolve()))
        errs = _collect_validator_errors(v, data, schema_name=str(schema_name))
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=str(ex_path),
                schema_name=str(schema_name),
                contract_type="example",
                status="valid" if not errs else "invalid",
                errors=errs,
            )
        )
    return rows


def audit_manifest(*, validated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    m = load_manifest()
    arts = m.get("artifacts") or {}
    allowed = {"provider", "platform_object", "consumer", "openapi", "network_contract"}
    for name, meta in arts.items():
        schema_path = (meta or {}).get("schema_path")
        ct = (meta or {}).get("contract_type")
        errors: list[dict[str, Any]] = []
        if not ct:
            errors.append({"path": "$.contract_type", "message": "Missing contract_type", "schema": name})
        elif str(ct) not in allowed:
            errors.append({"path": "$.contract_type", "message": f"Invalid contract_type: {ct!r}", "schema": name})
        if not schema_path:
            errors.append({"path": "$.schema_path", "message": "Missing schema_path", "schema": name})
        else:
            p = (SPEC_ROOT / str(schema_path)).resolve()
            if not p.exists():
                errors.append({"path": "$.schema_path", "message": f"Missing file: {schema_path}", "schema": name})

        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=f"manifest:{name}",
                schema_name=name,
                contract_type=str(ct) if ct is not None else None,
                status="valid" if not errors else "invalid",
                errors=errors,
            )
        )
    return rows


def audit_output_artifacts(*, base_path: Path | str, validated_at: str) -> list[dict[str, Any]]:
    out_dir = _outputs_dir(base_path)
    rows: list[dict[str, Any]] = []

    def validate_json_file(file_name: str, schema_name: str) -> None:
        path = out_dir / file_name
        data, load_err = _read_json(path)
        ct = _contract_type_for(schema_name)
        if data is None and load_err is None:
            rows.append(_report_row(validated_at=validated_at, artifact_or_api=str(path), schema_name=schema_name, contract_type=ct, status="skipped"))
            return
        if load_err is not None:
            rows.append(
                _report_row(
                    validated_at=validated_at,
                    artifact_or_api=str(path),
                    schema_name=schema_name,
                    contract_type=ct,
                    status="invalid",
                    errors=[{"path": "$", "message": load_err, "schema": schema_name}],
                )
            )
            return
        v = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"][schema_name]["schema_path"]).resolve()))
        errs = _collect_validator_errors(v, data, schema_name=schema_name)
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=str(path),
                schema_name=schema_name,
                contract_type=ct,
                status="valid" if not errs else "invalid",
                errors=errs,
            )
        )

    # decision_packets.json: validate array + each item against core + AQ profile
    dp_path = out_dir / "decision_packets.json"
    packets, load_err = _read_json(dp_path)
    if packets is None and load_err is None:
        rows.append(_report_row(validated_at=validated_at, artifact_or_api=str(dp_path), schema_name="decision_packets", contract_type=_contract_type_for("decision_packets"), status="skipped"))
    elif load_err is not None:
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=str(dp_path),
                schema_name="decision_packets",
                contract_type=_contract_type_for("decision_packets"),
                status="invalid",
                errors=[{"path": "$", "message": load_err, "schema": "decision_packets"}],
            )
        )
    else:
        v_arr = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["decision_packets"]["schema_path"]).resolve()))
        arr_errs = _collect_validator_errors(v_arr, packets, schema_name="decision_packets")
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=str(dp_path),
                schema_name="decision_packets",
                contract_type=_contract_type_for("decision_packets"),
                status="valid" if not arr_errs else "invalid",
                errors=arr_errs,
            )
        )

        v_core = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["urban_decision_packet_core"]["schema_path"]).resolve()))
        v_aq = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["decision_packet_air_quality"]["schema_path"]).resolve()))
        core_errors: list[dict[str, Any]] = []
        aq_errors: list[dict[str, Any]] = []
        if not isinstance(packets, list):
            core_errors.append({"path": "$", "message": "decision_packets.json must be an array to validate items", "schema": "urban_decision_packet_core"})
            aq_errors.append({"path": "$", "message": "decision_packets.json must be an array to validate items", "schema": "decision_packet_air_quality"})
        else:
            for i, pkt in enumerate(packets):
                if not isinstance(pkt, dict):
                    core_errors.append({"path": f"/{i}", "message": "Packet must be an object", "schema": "urban_decision_packet_core", "packet_index": i})
                    aq_errors.append({"path": f"/{i}", "message": "Packet must be an object", "schema": "decision_packet_air_quality", "packet_index": i})
                    continue
                for e in _collect_validator_errors(v_core, pkt, schema_name="urban_decision_packet_core"):
                    e["packet_index"] = i
                    core_errors.append(e)
                for e in _collect_validator_errors(v_aq, pkt, schema_name="decision_packet_air_quality"):
                    e["packet_index"] = i
                    aq_errors.append(e)

        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=f"{dp_path}#items",
                schema_name="urban_decision_packet_core",
                contract_type=_contract_type_for("urban_decision_packet_core"),
                status="valid" if not core_errors else "invalid",
                errors=core_errors,
            )
        )
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api=f"{dp_path}#items",
                schema_name="decision_packet_air_quality",
                contract_type=_contract_type_for("decision_packet_air_quality"),
                status="valid" if not aq_errors else "invalid",
                errors=aq_errors,
            )
        )

    validate_json_file("data_audit.json", "data_audit")
    validate_json_file("metrics.json", "metrics")
    validate_json_file("source_reliability.json", "source_reliability")
    validate_json_file("scale_analysis.json", "scale_analysis")

    return rows


def _df_to_wrapper(df: pd.DataFrame) -> dict[str, Any]:
    data = []
    if df is not None and not df.empty:
        try:
            data = df.to_dict(orient="records")
        except Exception:
            data = []
    return {"data": data, "count": (len(df) if df is not None else 0), "generated_at": _now()}


def audit_api_responses(*, base_path: Path | str, validated_at: str) -> list[dict[str, Any]]:
    """
    Validate local API return values against consumer contracts where available.
    This does not change runtime API behavior; it wraps responses only for validation.
    """
    rows: list[dict[str, Any]] = []
    from urban_platform.api import local as api

    # decision packets APIs: validate raw list/dict against existing consumer schemas (not wrapper)
    packets = api.get_decision_packets(base_dir=Path(base_path))
    if packets:
        v_arr = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["decision_packets"]["schema_path"]).resolve()))
        errs = _collect_validator_errors(v_arr, packets, schema_name="decision_packets")
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_decision_packets()",
                schema_name="decision_packets",
                contract_type=_contract_type_for("decision_packets"),
                status="valid" if not errs else "invalid",
                errors=errs,
            )
        )
        # validate items
        v_core = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["urban_decision_packet_core"]["schema_path"]).resolve()))
        v_aq = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["decision_packet_air_quality"]["schema_path"]).resolve()))
        core_errors: list[dict[str, Any]] = []
        aq_errors: list[dict[str, Any]] = []
        for i, pkt in enumerate(packets):
            for e in _collect_validator_errors(v_core, pkt, schema_name="urban_decision_packet_core"):
                e["packet_index"] = i
                core_errors.append(e)
            for e in _collect_validator_errors(v_aq, pkt, schema_name="decision_packet_air_quality"):
                e["packet_index"] = i
                aq_errors.append(e)
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_decision_packets()#items",
                schema_name="urban_decision_packet_core",
                contract_type=_contract_type_for("urban_decision_packet_core"),
                status="valid" if not core_errors else "invalid",
                errors=core_errors,
            )
        )
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_decision_packets()#items",
                schema_name="decision_packet_air_quality",
                contract_type=_contract_type_for("decision_packet_air_quality"),
                status="valid" if not aq_errors else "invalid",
                errors=aq_errors,
            )
        )
        # single packet
        pid = str((packets[0] or {}).get("packet_id") or "")
        if pid:
            one = api.get_decision_packet(pid, base_dir=Path(base_path))
            if one is not None:
                errs = _collect_validator_errors(v_aq, one, schema_name="decision_packet_air_quality")
                rows.append(
                    _report_row(
                        validated_at=validated_at,
                        artifact_or_api=f"api:get_decision_packet({pid})",
                        schema_name="decision_packet_air_quality",
                        contract_type=_contract_type_for("decision_packet_air_quality"),
                        status="valid" if not errs else "invalid",
                        errors=errs,
                    )
                )
    else:
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_decision_packets()",
                schema_name="decision_packets",
                contract_type=_contract_type_for("decision_packets"),
                status="skipped",
            )
        )

    # wrappers for DataFrame-returning APIs
    df = api.get_recommendations(base_dir=Path(base_path))
    wrapper = _df_to_wrapper(df)
    try:
        v = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["consumer_recommendation_response"]["schema_path"]).resolve()))
        errs = _collect_validator_errors(v, wrapper, schema_name="consumer_recommendation_response")
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_recommendations()",
                schema_name="consumer_recommendation_response",
                contract_type=_contract_type_for("consumer_recommendation_response"),
                status="valid" if not errs else "invalid",
                errors=errs,
            )
        )
    except Exception as exc:  # noqa: BLE001
        rows.append(
            _report_row(
                validated_at=validated_at,
                artifact_or_api="api:get_recommendations()",
                schema_name="consumer_recommendation_response",
                contract_type=_contract_type_for("consumer_recommendation_response"),
                status="invalid",
                errors=[{"path": "$", "message": str(exc), "schema": "consumer_recommendation_response"}],
            )
        )

    df = api.get_source_reliability(base_dir=Path(base_path))
    wrapper = _df_to_wrapper(df)
    v = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["consumer_source_reliability_response"]["schema_path"]).resolve()))
    errs = _collect_validator_errors(v, wrapper, schema_name="consumer_source_reliability_response")
    rows.append(
        _report_row(
            validated_at=validated_at,
            artifact_or_api="api:get_source_reliability()",
            schema_name="consumer_source_reliability_response",
            contract_type=_contract_type_for("consumer_source_reliability_response"),
            status="valid" if not errs else "invalid",
            errors=errs,
        )
    )

    df = api.get_features(base_dir=Path(base_path))
    wrapper = _df_to_wrapper(df)
    v = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["consumer_feature_response"]["schema_path"]).resolve()))
    errs = _collect_validator_errors(v, wrapper, schema_name="consumer_feature_response")
    rows.append(
        _report_row(
            validated_at=validated_at,
            artifact_or_api="api:get_features()",
            schema_name="consumer_feature_response",
            contract_type=_contract_type_for("consumer_feature_response"),
            status="valid" if not errs else "invalid",
            errors=errs,
        )
    )

    df = api.get_observations(base_dir=Path(base_path))
    wrapper = _df_to_wrapper(df)
    v = validator_for_schema_file(str((SPEC_ROOT / load_manifest()["artifacts"]["consumer_observation_response"]["schema_path"]).resolve()))
    errs = _collect_validator_errors(v, wrapper, schema_name="consumer_observation_response")
    rows.append(
        _report_row(
            validated_at=validated_at,
            artifact_or_api="api:get_observations()",
            schema_name="consumer_observation_response",
            contract_type=_contract_type_for("consumer_observation_response"),
            status="valid" if not errs else "invalid",
            errors=errs,
        )
    )

    return rows


def run_conformance_audit(base_path: Path | str) -> dict[str, Any]:
    """
    Full specification conformance audit.

    Writes:
      <base_path>/data/outputs/conformance_report.json
    """
    # Backward-compatible wrapper: delegate to the unified engine (full mode).
    from urban_platform.specifications.engine import run_conformance

    return run_conformance(base_path, mode="full")

