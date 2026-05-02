from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class DeploymentExampleStatus:
    deployment_key: str
    deployment_dir: str
    deployment_id: str
    deployment_profile_exists: bool
    provider_registry_exists: bool
    application_registry_exists: bool
    readme_exists: bool
    provider_count: Optional[int]
    application_count: Optional[int]
    missing_fixture_paths: list[str]
    missing_manifest_references: list[str]
    risks: list[str]
    recommended_next_task: str
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeploymentExamplesProbeResult:
    examples_dir_exists: bool
    example_count: int
    deployments: list[dict[str, Any]]
    risks: list[str]
    recommended_next_task: str
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to read JSON at {path}: {exc}"
    try:
        return json.loads(text), None
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to parse JSON at {path}: {exc}"


def _read_yaml(path: Path) -> tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to read YAML at {path}: {exc}"
    try:
        return yaml.safe_load(text), None
    except Exception as exc:  # noqa: BLE001
        return None, f"Failed to parse YAML at {path}: {exc}"


def probe_deployment_examples(repo_root: Path) -> DeploymentExamplesProbeResult:
    """
    Lightweight structural probe over deployments/examples/*.

    Read-only:
    - does not run deployments
    - does not import registry modules
    - validates obvious manifest and fixture path references
    """
    errors: list[str] = []
    risks: list[str] = []

    spec_root = repo_root / "specifications"
    manifest_path = spec_root / "manifest.json"
    manifest, err = _read_json(manifest_path)
    if err:
        errors.append(err)
        manifest = {}
    if not isinstance(manifest, dict):
        errors.append("manifest.json root must be an object")
        manifest = {}
    artifacts = (manifest.get("artifacts") or {}) if isinstance(manifest, dict) else {}

    examples_dir = repo_root / "deployments" / "examples"
    if not examples_dir.exists():
        return DeploymentExamplesProbeResult(
            examples_dir_exists=False,
            example_count=0,
            deployments=[],
            risks=[],
            recommended_next_task="Add a deployment example under deployments/examples/ if you want a registry-driven demo.",
            errors=errors,
        )

    deployments: list[DeploymentExampleStatus] = []
    for d in sorted([p for p in examples_dir.iterdir() if p.is_dir()]):
        deployment_key = d.name
        dep_profile = d / "deployment_profile.yaml"
        prov_reg = d / "provider_registry.yaml"
        app_reg = d / "application_registry.yaml"
        readme = d / "README.md"

        dep_id = deployment_key
        dep_profile_doc: Any = None
        dep_profile_errs: list[str] = []
        if dep_profile.exists():
            dep_profile_doc, yerr = _read_yaml(dep_profile)
            if yerr:
                dep_profile_errs.append(yerr)
            if isinstance(dep_profile_doc, dict) and dep_profile_doc.get("deployment_id"):
                dep_id = str(dep_profile_doc.get("deployment_id"))

        missing_fixture_paths: list[str] = []
        missing_manifest_refs: list[str] = []
        local_risks: list[str] = []
        local_errors: list[str] = dep_profile_errs[:]

        provider_count: Optional[int] = None
        if prov_reg.exists():
            doc, yerr = _read_yaml(prov_reg)
            if yerr:
                local_errors.append(yerr)
                doc = None
            providers = (doc or {}).get("providers") if isinstance(doc, dict) else None
            if isinstance(providers, list):
                provider_count = len(providers)
                for pmeta in providers:
                    if not isinstance(pmeta, dict):
                        continue
                    pid = str(pmeta.get("provider_id") or "?")
                    pc = pmeta.get("provider_contract")
                    if isinstance(pc, str) and pc and pc not in artifacts:
                        missing_manifest_refs.append(f"{deployment_key} provider:{pid} provider_contract:{pc}")
                    fx = pmeta.get("fixture_path")
                    if isinstance(fx, str) and fx.strip():
                        fx_path = (repo_root / fx.strip()).resolve()
                        if not fx_path.exists():
                            missing_fixture_paths.append(f"{deployment_key} provider:{pid} fixture_missing:{fx.strip()}")
            else:
                local_risks.append(f"{deployment_key}: provider_registry.yaml missing providers array")

        application_count: Optional[int] = None
        if app_reg.exists():
            doc, yerr = _read_yaml(app_reg)
            if yerr:
                local_errors.append(yerr)
                doc = None
            apps = (doc or {}).get("applications") if isinstance(doc, dict) else None
            if isinstance(apps, list):
                application_count = len(apps)
                for ameta in apps:
                    if not isinstance(ameta, dict):
                        continue
                    aid = str(ameta.get("application_id") or "?")
                    ccs = ameta.get("consumer_contracts") or []
                    if isinstance(ccs, list):
                        for ck in ccs:
                            if isinstance(ck, str) and ck and ck not in artifacts:
                                missing_manifest_refs.append(f"{deployment_key} application:{aid} consumer_contract:{ck}")
                    else:
                        local_risks.append(f"{deployment_key} application:{aid} consumer_contracts not an array")
            else:
                local_risks.append(f"{deployment_key}: application_registry.yaml missing applications array")

        # Required file presence checks
        if not dep_profile.exists():
            local_risks.append(f"{deployment_key}: missing deployment_profile.yaml")
        if not prov_reg.exists():
            local_risks.append(f"{deployment_key}: missing provider_registry.yaml")
        if not app_reg.exists():
            local_risks.append(f"{deployment_key}: missing application_registry.yaml")
        if not readme.exists():
            local_risks.append(f"{deployment_key}: missing README.md")

        if missing_fixture_paths:
            local_risks.append(f"{deployment_key}: missing fixture paths (fix fixture_path entries).")
        if missing_manifest_refs:
            local_risks.append(f"{deployment_key}: missing manifest references (fix contract keys or manifest).")
        if local_errors:
            local_risks.append(f"{deployment_key}: YAML/JSON parse errors present.")

        if local_risks:
            recommended = f"Fix deployment example issues (first: {local_risks[0]})."
        else:
            recommended = "Keep deployment examples aligned with manifest contracts and fixture paths."

        deployments.append(
            DeploymentExampleStatus(
                deployment_key=deployment_key,
                deployment_dir=str(d.relative_to(repo_root)),
                deployment_id=dep_id,
                deployment_profile_exists=dep_profile.exists(),
                provider_registry_exists=prov_reg.exists(),
                application_registry_exists=app_reg.exists(),
                readme_exists=readme.exists(),
                provider_count=provider_count,
                application_count=application_count,
                missing_fixture_paths=missing_fixture_paths,
                missing_manifest_references=missing_manifest_refs,
                risks=local_risks,
                recommended_next_task=recommended,
                errors=local_errors,
            )
        )

    if not deployments:
        risks.append("deployments/examples exists but no deployment example folders were found.")

    any_risks = any(d.risks for d in deployments)
    if any_risks:
        risks.append("One or more deployment examples have structural issues.")

    if any_risks:
        first = next((r for d in deployments for r in d.risks), "Fix deployment example issues.")
        recommended_next = f"Resolve deployment example issues (first: {first})."
    else:
        recommended_next = "Add another deployment example or extend checks (still read-only)."

    return DeploymentExamplesProbeResult(
        examples_dir_exists=True,
        example_count=len(deployments),
        deployments=[d.to_dict() for d in deployments],
        risks=risks,
        recommended_next_task=recommended_next,
        errors=errors,
    )

