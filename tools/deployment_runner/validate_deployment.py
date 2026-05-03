from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import yaml

# Allow running as a standalone script from repo root:
# `python tools/deployment_runner/validate_deployment.py --deployment ...`
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT_FOR_IMPORTS = _THIS_FILE.parents[2]
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from urban_platform.specifications.conformance import load_manifest  # noqa: E402


@dataclass(frozen=True)
class ValidationSummary:
    deployment_dir: str
    deployment_id: str | None
    enabled_domains: list[str]
    provider_count: int
    application_count: int
    network_adapter_count: int
    warnings: list[str]
    errors: list[str]
    recommended_next_task: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECRET_KEY_RE = re.compile(
    r"(?i)\b("
    r"password|passwd|passphrase|secret|token|api[_-]?key|access[_-]?key|refresh[_-]?token|"
    r"authorization|bearer|credentials|private[_-]?key|mailbox[_-]?password"
    r")\b"
)

_SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._-]+\b|"
    r"\bAKIA[0-9A-Z]{12,}\b|"
    r"\bghp_[A-Za-z0-9]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\bAIza[0-9A-Za-z_-]{20,}\b"
    r")"
)

_OP_AUTHORITY_TERMS = ("auto_enforce", "automatic_penalty", "demolition_order")


def _read_yaml(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return doc


def _iter_scalar_strings(obj: Any) -> Iterable[str]:
    if obj is None:
        return
    if isinstance(obj, str):
        yield obj
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _iter_scalar_strings(v)
        return
    if isinstance(obj, list):
        for it in obj:
            yield from _iter_scalar_strings(it)
        return


def _check_no_secrets(obj: Any, *, context: str, warnings: list[str], errors: list[str]) -> None:
    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            # Values: look for token/key-like patterns only (avoid flagging benign policy text like "no API keys").
            if _SECRET_VALUE_RE.search(node):
                errors.append(f"{context}: secret-like value detected: {node!r}")
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                    errors.append(f"{context}: secret-like key detected: {k!r}")
                walk(v)
            return
        if isinstance(node, list):
            for it in node:
                walk(it)
            return

    walk(obj)


def _manifest_has_artifact(manifest: dict[str, Any], key: str) -> bool:
    arts = manifest.get("artifacts")
    return isinstance(arts, dict) and key in arts


def _ensure_file_exists(path: Path, *, label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing required file: {label} ({path.name})")


def _validate_deployment_profile(profile: dict[str, Any], *, warnings: list[str], errors: list[str]) -> tuple[str | None, list[str]]:
    required_fields = [
        "deployment_id",
        "deployment_name",
        "deployment_type",
        "enabled_domains",
        "environment",
    ]
    for f in required_fields:
        if not str(profile.get(f) or "").strip() and f != "enabled_domains":
            errors.append(f"deployment_profile: missing {f}")
    enabled_domains = profile.get("enabled_domains")
    if not isinstance(enabled_domains, list) or not all(isinstance(x, str) and x.strip() for x in enabled_domains):
        errors.append("deployment_profile: enabled_domains must be a non-empty list of strings")
        enabled = []
    else:
        enabled = [x.strip() for x in enabled_domains]

    no_secrets_notice = profile.get("no_secrets_notice")
    if not isinstance(no_secrets_notice, str) or not no_secrets_notice.strip():
        warnings.append("deployment_profile: missing no_secrets_notice (recommended)")

    deployment_id = profile.get("deployment_id")
    dep_id = deployment_id.strip() if isinstance(deployment_id, str) and deployment_id.strip() else None
    return dep_id, enabled


def _validate_provider_registry(
    reg: dict[str, Any],
    *,
    deployment_dir: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> int:
    providers = reg.get("providers")
    if not isinstance(providers, list):
        errors.append("provider_registry: providers must be a list")
        return 0

    _check_no_secrets(reg, context="provider_registry", warnings=warnings, errors=errors)

    for i, p in enumerate(providers):
        ctx = f"provider_registry.providers[{i}]"
        if not isinstance(p, dict):
            errors.append(f"{ctx}: provider entry must be an object")
            continue
        pid = str(p.get("provider_id") or "").strip()
        if not pid:
            errors.append(f"{ctx}: missing provider_id")

        domain_ids = p.get("domain_ids")
        if not isinstance(domain_ids, list) or not all(isinstance(x, str) and x.strip() for x in domain_ids):
            errors.append(f"{ctx}: domain_ids must be a non-empty list of strings")

        contract = str(p.get("provider_contract") or "").strip()
        if not contract:
            errors.append(f"{ctx}: missing provider_contract")
        elif not _manifest_has_artifact(manifest, contract):
            errors.append(f"{ctx}: provider_contract not found in specifications/manifest.json artifacts: {contract}")

        input_method = str(p.get("input_method") or "").strip()
        if not input_method:
            errors.append(f"{ctx}: missing input_method")

        oot = p.get("output_platform_object_types")
        if not isinstance(oot, list) or not all(isinstance(x, str) and x.strip() for x in oot):
            errors.append(f"{ctx}: output_platform_object_types must be a non-empty list of strings")

        fixture_path = p.get("fixture_path")
        if fixture_path is not None:
            fp = str(fixture_path).strip()
            if not fp:
                errors.append(f"{ctx}: fixture_path declared but empty")
            else:
                full = (repo_root / fp).resolve()
                if not full.exists():
                    errors.append(f"{ctx}: fixture_path not found: {fp}")
                # Encourage deployments to keep fixtures under specifications/examples in repo examples.
                if "deployments/examples/" in str(deployment_dir).replace("\\", "/") and not fp.startswith("specifications/"):
                    warnings.append(f"{ctx}: fixture_path is not under specifications/: {fp}")

    return len(providers)


def _validate_application_registry(
    reg: dict[str, Any],
    *,
    manifest: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> int:
    apps = reg.get("applications")
    if not isinstance(apps, list):
        errors.append("application_registry: applications must be a list")
        return 0

    _check_no_secrets(reg, context="application_registry", warnings=warnings, errors=errors)

    for i, a in enumerate(apps):
        ctx = f"application_registry.applications[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{ctx}: application entry must be an object")
            continue
        aid = str(a.get("application_id") or "").strip()
        if not aid:
            errors.append(f"{ctx}: missing application_id")

        domain_id = str(a.get("domain_id") or "").strip()
        if not domain_id:
            errors.append(f"{ctx}: missing domain_id")

        contracts = a.get("consumer_contracts")
        if not isinstance(contracts, list) or not all(isinstance(x, str) and x.strip() for x in contracts):
            errors.append(f"{ctx}: consumer_contracts must be a non-empty list of strings")
        else:
            for ck in contracts:
                if not _manifest_has_artifact(manifest, ck):
                    errors.append(f"{ctx}: consumer_contract not found in manifest artifacts: {ck}")

        sg = a.get("safety_gates_and_blocked_uses")
        if not isinstance(sg, list) or not all(isinstance(x, str) and x.strip() for x in sg):
            errors.append(f"{ctx}: safety_gates_and_blocked_uses must be a non-empty list of strings")

        # Guardrail: disallow operational authority language unless it appears in blocked uses references.
        blob = json.dumps(a, sort_keys=True)
        blocked_refs = " ".join(x for x in (sg or []) if isinstance(x, str))
        for term in _OP_AUTHORITY_TERMS:
            if term in blob and term not in blocked_refs:
                errors.append(
                    f"{ctx}: disallowed operational authority term {term!r} present (must be explicitly in blocked uses)"
                )

    return len(apps)


def _validate_network_adapter_registry(
    reg: dict[str, Any],
    *,
    manifest: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> int:
    adapters = reg.get("adapters")
    if adapters is None:
        return 0
    if not isinstance(adapters, list):
        errors.append("network_adapter_registry: adapters must be a list")
        return 0

    _check_no_secrets(reg, context="network_adapter_registry", warnings=warnings, errors=errors)

    for i, ad in enumerate(adapters):
        ctx = f"network_adapter_registry.adapters[{i}]"
        if not isinstance(ad, dict):
            errors.append(f"{ctx}: adapter entry must be an object")
            continue
        adapter_id = str(ad.get("adapter_id") or "").strip()
        if not adapter_id:
            errors.append(f"{ctx}: missing adapter_id")

        transport = str(ad.get("supported_transport") or "").strip()
        if not transport:
            errors.append(f"{ctx}: missing supported_transport")

        contracts = ad.get("supported_network_contracts")
        if not isinstance(contracts, list) or not all(isinstance(x, str) and x.strip() for x in contracts):
            errors.append(f"{ctx}: supported_network_contracts must be a non-empty list of strings")
        else:
            for ck in contracts:
                if not _manifest_has_artifact(manifest, ck):
                    errors.append(f"{ctx}: supported_network_contract not found in manifest artifacts: {ck}")

        # configuration_ref is optional and preferred over inline config.
        config_ref = ad.get("configuration_ref")
        if isinstance(config_ref, str) and config_ref.strip() and not config_ref.startswith("DEPLOYMENT_LOCAL:"):
            warnings.append(f"{ctx}: configuration_ref should typically be DEPLOYMENT_LOCAL:... (got {config_ref!r})")

    return len(adapters)


def _validate_optional_profile(
    *,
    path: Path,
    kind: str,
    required_keys: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    if not path.exists():
        return
    if not path.is_file():
        errors.append(f"{kind}: expected file but found non-file: {path.name}")
        return
    doc = _read_yaml(path)
    _check_no_secrets(doc, context=kind, warnings=warnings, errors=errors)
    for k in required_keys:
        if not str(doc.get(k) or "").strip():
            errors.append(f"{kind}: missing {k}")


def validate_deployment(*, deployment_dir: Path, repo_root: Path) -> ValidationSummary:
    warnings: list[str] = []
    errors: list[str] = []

    manifest = load_manifest()

    # 1) Required files
    prof_path = deployment_dir / "deployment_profile.yaml"
    prov_path = deployment_dir / "provider_registry.yaml"
    app_path = deployment_dir / "application_registry.yaml"
    _ensure_file_exists(prof_path, label="deployment_profile.yaml", errors=errors)
    _ensure_file_exists(prov_path, label="provider_registry.yaml", errors=errors)
    _ensure_file_exists(app_path, label="application_registry.yaml", errors=errors)

    if "deployments/examples/" in str(deployment_dir).replace("\\", "/"):
        if not (deployment_dir / "README.md").is_file():
            warnings.append("example deployment: README.md is missing (recommended)")

    # If required files are missing, stop early but still report.
    deployment_id: str | None = None
    enabled_domains: list[str] = []
    provider_count = 0
    application_count = 0
    adapter_count = 0

    if not errors:
        profile = _read_yaml(prof_path)
        _check_no_secrets(profile, context="deployment_profile", warnings=warnings, errors=errors)
        deployment_id, enabled_domains = _validate_deployment_profile(profile, warnings=warnings, errors=errors)

        provider_reg = _read_yaml(prov_path)
        provider_count = _validate_provider_registry(
            provider_reg,
            deployment_dir=deployment_dir,
            repo_root=repo_root,
            manifest=manifest,
            warnings=warnings,
            errors=errors,
        )

        app_reg = _read_yaml(app_path)
        application_count = _validate_application_registry(app_reg, manifest=manifest, warnings=warnings, errors=errors)

        net_path = deployment_dir / "network_adapter_registry.yaml"
        if net_path.exists():
            net_reg = _read_yaml(net_path)
            adapter_count = _validate_network_adapter_registry(net_reg, manifest=manifest, warnings=warnings, errors=errors)

        # 6) Optional profiles
        _validate_optional_profile(
            path=deployment_dir / "agency_node_profile.yaml",
            kind="agency_node_profile",
            required_keys=["node_id", "agency_id", "jurisdiction_type", "enabled_domains"],
            warnings=warnings,
            errors=errors,
        )
        _validate_optional_profile(
            path=deployment_dir / "jurisdiction_profile.yaml",
            kind="jurisdiction_profile",
            required_keys=["jurisdiction_id", "jurisdiction_type", "authoritative_source"],
            warnings=warnings,
            errors=errors,
        )
        _validate_optional_profile(
            path=deployment_dir / "data_sharing_policy.yaml",
            kind="data_sharing_policy",
            required_keys=[
                "policy_id",
                "purpose",
                "allowed_senders",
                "allowed_receivers",
                "allowed_message_types",
                "allowed_schema_refs",
                "prohibited_uses",
            ],
            warnings=warnings,
            errors=errors,
        )

    if errors:
        rec = (
            "Fix deployment configuration errors (missing required fields/files, invalid manifest references, "
            "or secret-like values). Re-run validation before attempting any deployment runs."
        )
    else:
        rec = (
            "Validation passed. Next: run conformance (`python main.py --step conformance`) and then execute a "
            "deployment runner (if available) for this deployment."
        )

    return ValidationSummary(
        deployment_dir=str(deployment_dir),
        deployment_id=deployment_id,
        enabled_domains=enabled_domains,
        provider_count=provider_count,
        application_count=application_count,
        network_adapter_count=adapter_count,
        warnings=warnings,
        errors=errors,
        recommended_next_task=rec,
    )


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / "specifications").exists() and (cur / "README.md").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve().parents[2]


def _print_summary(s: ValidationSummary) -> None:
    dep = s.deployment_id or "<unknown>"
    print("AirOS deployment configuration validation")
    print(f"- deployment_id: {dep}")
    print(f"- enabled_domains: {', '.join(s.enabled_domains) if s.enabled_domains else '<none>'}")
    print(f"- provider_count: {s.provider_count}")
    print(f"- application_count: {s.application_count}")
    print(f"- network_adapter_count: {s.network_adapter_count}")
    if s.warnings:
        print("- warnings:")
        for w in s.warnings:
            print(f"  - {w}")
    if s.errors:
        print("- errors:")
        for e in s.errors:
            print(f"  - {e}")
    print(f"- recommended_next_task: {s.recommended_next_task}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an AirOS deployment configuration directory.")
    parser.add_argument(
        "--deployment",
        required=True,
        type=str,
        help="Deployment directory (e.g. deployments/examples/flood_local_demo).",
    )
    args = parser.parse_args()

    repo_root = _find_repo_root(Path(__file__).resolve())
    deployment_dir = (repo_root / str(args.deployment)).resolve()
    if not deployment_dir.exists():
        raise SystemExit(f"Deployment directory not found: {args.deployment}")

    summary = validate_deployment(deployment_dir=deployment_dir, repo_root=repo_root)
    _print_summary(summary)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

