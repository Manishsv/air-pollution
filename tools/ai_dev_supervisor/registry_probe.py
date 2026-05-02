from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class RegistryHygieneResult:
    provider_count: int
    application_count: int
    adapter_count: int
    missing_manifest_references: list[str]
    missing_example_references: list[str]
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


def _example_ref_to_path(spec_root: Path, manifest: dict[str, Any], ref: str) -> Optional[Path]:
    """
    Resolve an example reference string to a concrete file path under specifications/.

    Supported formats:
    - "example_manifest_key" (key under manifest['examples'])
    - "examples/<...>.json" (relative path under specifications/)
    - "specifications/examples/<...>.json" (repo-root-relative; normalized)
    """
    ref = str(ref)
    ex_meta = (manifest.get("examples") or {}).get(ref)
    if isinstance(ex_meta, dict) and isinstance(ex_meta.get("path"), str):
        return (spec_root / ex_meta["path"]).resolve()

    if ref.startswith("specifications/"):
        ref = ref[len("specifications/") :]

    if ref.startswith("examples/"):
        return (spec_root / ref).resolve()

    return None


def check_registry_hygiene(
    *,
    spec_root: Path,
    manifest: dict[str, Any],
    provider_registry: dict[str, Any],
    application_registry: dict[str, Any],
    network_adapter_registry: dict[str, Any],
) -> RegistryHygieneResult:
    errors: list[str] = []
    risks: list[str] = []
    missing_manifest: list[str] = []
    missing_examples: list[str] = []

    artifacts = manifest.get("artifacts") or {}

    providers = provider_registry.get("providers") or []
    if not isinstance(providers, list):
        errors.append("provider_registry.providers must be an array")
        providers = []

    for p in providers:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("provider_id") or "?")
        contract = p.get("provider_contract")
        if isinstance(contract, str) and contract:
            if contract not in artifacts:
                missing_manifest.append(f"provider:{pid} provider_contract:{contract}")
        else:
            risks.append(f"provider:{pid} missing provider_contract")

        exs = p.get("examples") or []
        if isinstance(exs, list):
            for ref in exs:
                if not isinstance(ref, str) or not ref.strip():
                    continue
                path = _example_ref_to_path(spec_root, manifest, ref.strip())
                if path is None:
                    missing_examples.append(f"provider:{pid} example_ref_unresolved:{ref}")
                    continue
                if not path.exists():
                    missing_examples.append(f"provider:{pid} example_missing:{ref}")
        else:
            risks.append(f"provider:{pid} examples must be an array")

        # Informational fields (reported elsewhere) — don't import modules here.
        if not isinstance(p.get("status"), str):
            risks.append(f"provider:{pid} missing status")
        if not isinstance(p.get("input_method"), str):
            risks.append(f"provider:{pid} missing input_method")

    apps = application_registry.get("applications") or []
    if not isinstance(apps, list):
        errors.append("application_registry.applications must be an array")
        apps = []

    for a in apps:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("application_id") or "?")
        consumer_contracts = a.get("consumer_contracts") or []
        if isinstance(consumer_contracts, list):
            for c in consumer_contracts:
                if not isinstance(c, str) or not c.strip():
                    continue
                if c not in artifacts:
                    missing_manifest.append(f"application:{aid} consumer_contract:{c}")
        else:
            risks.append(f"application:{aid} consumer_contracts must be an array")

        exs = a.get("examples") or []
        if isinstance(exs, list):
            for ref in exs:
                if not isinstance(ref, str) or not ref.strip():
                    continue
                path = _example_ref_to_path(spec_root, manifest, ref.strip())
                if path is None:
                    missing_examples.append(f"application:{aid} example_ref_unresolved:{ref}")
                    continue
                if not path.exists():
                    missing_examples.append(f"application:{aid} example_missing:{ref}")
        else:
            risks.append(f"application:{aid} examples must be an array")

        sgbu = a.get("safety_gates_and_blocked_uses") or []
        if not isinstance(sgbu, list) or not sgbu:
            risks.append(f"application:{aid} missing safety_gates_and_blocked_uses")

        # Informational-only fields for now (no imports).
        if not isinstance(a.get("payload_builders"), list):
            risks.append(f"application:{aid} missing payload_builders")

    adapters = network_adapter_registry.get("adapters") or []
    if not isinstance(adapters, list):
        errors.append("network_adapter_registry.adapters must be an array")
        adapters = []

    for ad in adapters:
        if not isinstance(ad, dict):
            continue
        adid = str(ad.get("adapter_id") or "?")
        snc = ad.get("supported_network_contracts") or []
        if isinstance(snc, list):
            for c in snc:
                if not isinstance(c, str) or not c.strip():
                    continue
                if c not in artifacts:
                    missing_manifest.append(f"adapter:{adid} supported_network_contract:{c}")
        else:
            risks.append(f"adapter:{adid} supported_network_contracts must be an array")

    if missing_manifest:
        risks.append("Registry references missing manifest artifacts (fix registry or register artifacts).")
    if missing_examples:
        risks.append("Registry references missing example files/keys (fix paths or add examples).")
    if errors:
        risks.append("Registry hygiene probe encountered errors (fix registry JSON structure).")

    if missing_manifest:
        recommended = f"Fix missing manifest references (first: {missing_manifest[0]})."
    elif missing_examples:
        recommended = f"Fix missing example references (first: {missing_examples[0]})."
    elif errors:
        recommended = "Fix registry JSON structure errors and rerun supervisor."
    else:
        recommended = "Keep registries aligned with manifest artifacts and examples; add registry validation to CI if needed."

    return RegistryHygieneResult(
        provider_count=len(providers),
        application_count=len(apps),
        adapter_count=len(adapters),
        missing_manifest_references=missing_manifest,
        missing_example_references=missing_examples,
        risks=risks,
        recommended_next_task=recommended,
        errors=errors,
    )


def probe_registry_hygiene(repo_root: Path) -> RegistryHygieneResult:
    """
    Read registry examples and check for missing manifest/example references.
    This is intentionally read-only and does not import connector/app modules.
    """
    errors: list[str] = []
    spec_root = repo_root / "specifications"
    manifest_path = spec_root / "manifest.json"
    prov_path = spec_root / "examples" / "registries" / "provider_registry.sample.json"
    app_path = spec_root / "examples" / "registries" / "application_registry.sample.json"
    nad_path = spec_root / "examples" / "registries" / "network_adapter_registry.sample.json"

    manifest, err = _read_json(manifest_path)
    if err:
        errors.append(err)
        manifest = {}
    provider_registry, err = _read_json(prov_path)
    if err:
        errors.append(err)
        provider_registry = {}
    application_registry, err = _read_json(app_path)
    if err:
        errors.append(err)
        application_registry = {}
    network_adapter_registry, err = _read_json(nad_path)
    if err:
        errors.append(err)
        network_adapter_registry = {}

    if not isinstance(manifest, dict):
        errors.append("manifest.json root must be an object")
        manifest = {}
    if not isinstance(provider_registry, dict):
        errors.append("provider registry JSON root must be an object")
        provider_registry = {}
    if not isinstance(application_registry, dict):
        errors.append("application registry JSON root must be an object")
        application_registry = {}
    if not isinstance(network_adapter_registry, dict):
        errors.append("network adapter registry JSON root must be an object")
        network_adapter_registry = {}

    res = check_registry_hygiene(
        spec_root=spec_root,
        manifest=manifest,
        provider_registry=provider_registry,
        application_registry=application_registry,
        network_adapter_registry=network_adapter_registry,
    )
    if errors:
        # preserve computed results but surface file IO/parse errors
        return RegistryHygieneResult(
            provider_count=res.provider_count,
            application_count=res.application_count,
            adapter_count=res.adapter_count,
            missing_manifest_references=res.missing_manifest_references,
            missing_example_references=res.missing_example_references,
            risks=res.risks,
            recommended_next_task=res.recommended_next_task,
            errors=errors + res.errors,
        )
    return res

