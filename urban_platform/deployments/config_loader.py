from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _safe_read_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path.name}: failed to read file ({exc})"
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        return None, f"{path.name}: YAML parse error ({exc})"
    if doc is None:
        return {}, None
    if not isinstance(doc, dict):
        return None, f"{path.name}: YAML root must be an object"
    return doc, None


def _norm_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if isinstance(x, str) and str(x).strip()]
    return []


@dataclass(frozen=True)
class ProviderRegistration:
    provider_id: str
    domain_ids: tuple[str, ...]
    provider_contract: str | None
    fixture_path: str | None
    enabled_by_default: bool | None
    label: str | None = None


@dataclass(frozen=True)
class ApplicationRegistration:
    application_id: str
    domain_id: str
    consumer_contracts: tuple[str, ...]
    enabled_by_default: bool | None
    label: str | None = None


@dataclass(frozen=True)
class NetworkAdapterRegistration:
    adapter_id: str
    supported_transport: str | None
    supported_network_contracts: tuple[str, ...]


def _parse_providers(doc: dict[str, Any] | None, *, warnings: list[str]) -> tuple[tuple[ProviderRegistration, ...], int]:
    if doc is None:
        return (), 0
    raw = doc.get("providers")
    if raw is None:
        return (), 0
    if not isinstance(raw, list):
        warnings.append("provider_registry.yaml: providers must be a list when present")
        return (), 0
    out: list[ProviderRegistration] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"provider_registry.yaml: skipping non-object providers[{i}]")
            continue
        pid = str(item.get("provider_id") or "").strip()
        out.append(
            ProviderRegistration(
                provider_id=pid,
                domain_ids=tuple(_norm_str_list(item.get("domain_ids"))),
                provider_contract=(str(item["provider_contract"]).strip() if item.get("provider_contract") else None),
                fixture_path=(str(item["fixture_path"]).strip() if item.get("fixture_path") is not None else None),
                enabled_by_default=item.get("enabled_by_default") if isinstance(item.get("enabled_by_default"), bool) else None,
                label=(str(item["label"]).strip() if item.get("label") else None),
            )
        )
    return tuple(out), len(out)


def _parse_applications(doc: dict[str, Any] | None, *, warnings: list[str]) -> tuple[tuple[ApplicationRegistration, ...], int]:
    if doc is None:
        return (), 0
    raw = doc.get("applications")
    if raw is None:
        return (), 0
    if not isinstance(raw, list):
        warnings.append("application_registry.yaml: applications must be a list when present")
        return (), 0
    out: list[ApplicationRegistration] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"application_registry.yaml: skipping non-object applications[{i}]")
            continue
        aid = str(item.get("application_id") or "").strip()
        did = str(item.get("domain_id") or "").strip()
        ccs = item.get("consumer_contracts")
        contracts: tuple[str, ...] = ()
        if isinstance(ccs, list):
            contracts = tuple(str(x).strip() for x in ccs if isinstance(x, str) and str(x).strip())
        elif ccs is not None:
            warnings.append(f"application_registry.yaml: applications[{i}] consumer_contracts is not a list")

        out.append(
            ApplicationRegistration(
                application_id=aid,
                domain_id=did,
                consumer_contracts=contracts,
                enabled_by_default=item.get("enabled_by_default") if isinstance(item.get("enabled_by_default"), bool) else None,
                label=(str(item["label"]).strip() if item.get("label") else None),
            )
        )
    return tuple(out), len(out)


def _parse_network_adapters(doc: dict[str, Any] | None, *, warnings: list[str]) -> tuple[tuple[NetworkAdapterRegistration, ...], int]:
    if doc is None:
        return (), 0
    raw = doc.get("adapters")
    if raw is None:
        return (), 0
    if not isinstance(raw, list):
        warnings.append("network_adapter_registry.yaml: adapters must be a list when present")
        return (), 0
    out: list[NetworkAdapterRegistration] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            warnings.append(f"network_adapter_registry.yaml: skipping non-object adapters[{i}]")
            continue
        aid = str(item.get("adapter_id") or "").strip()
        transport = str(item.get("supported_transport") or "").strip() or None
        snc = item.get("supported_network_contracts")
        contracts: tuple[str, ...] = ()
        if isinstance(snc, list):
            contracts = tuple(str(x).strip() for x in snc if isinstance(x, str) and str(x).strip())
        elif snc is not None:
            warnings.append(f"network_adapter_registry.yaml: adapters[{i}] supported_network_contracts is not a list")
        out.append(
            NetworkAdapterRegistration(
                adapter_id=aid,
                supported_transport=transport,
                supported_network_contracts=contracts,
            )
        )
    return tuple(out), len(out)


@dataclass(frozen=True)
class DeploymentConfig:
    """Read-only view of deployment YAML files (no connectors, no plugin execution)."""

    deployment_dir: Path
    deployment_id: str
    deployment_name: str | None
    enabled_domains: tuple[str, ...]
    provider_count: int
    application_count: int
    network_adapter_count: int
    providers: tuple[ProviderRegistration, ...]
    applications: tuple[ApplicationRegistration, ...]
    network_adapters: tuple[NetworkAdapterRegistration, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    profile_document: dict[str, Any] | None = None
    provider_registry_document: dict[str, Any] | None = None
    application_registry_document: dict[str, Any] | None = None
    network_adapter_registry_document: dict[str, Any] | None = None


def load_deployment_config(deployment_dir: Path) -> DeploymentConfig:
    """
    Parse deployment YAML files when present. Does not import connectors or execute applications.

    Missing optional files (e.g. network_adapter_registry.yaml) are represented as None without raising.
    """
    ddir = deployment_dir.resolve()
    warnings: list[str] = []
    errors: list[str] = []

    prof_path = ddir / "deployment_profile.yaml"
    prov_path = ddir / "provider_registry.yaml"
    app_path = ddir / "application_registry.yaml"
    net_path = ddir / "network_adapter_registry.yaml"

    profile_document: dict[str, Any] | None = None
    if prof_path.is_file():
        profile_document, perr = _safe_read_yaml(prof_path)
        if perr:
            errors.append(perr)
    else:
        warnings.append("deployment_profile.yaml not found")

    provider_registry_document: dict[str, Any] | None = None
    if prov_path.is_file():
        provider_registry_document, perr = _safe_read_yaml(prov_path)
        if perr:
            errors.append(perr)
    else:
        warnings.append("provider_registry.yaml not found")

    application_registry_document: dict[str, Any] | None = None
    if app_path.is_file():
        application_registry_document, perr = _safe_read_yaml(app_path)
        if perr:
            errors.append(perr)
    else:
        warnings.append("application_registry.yaml not found")

    network_adapter_registry_document: dict[str, Any] | None = None
    if net_path.is_file():
        network_adapter_registry_document, perr = _safe_read_yaml(net_path)
        if perr:
            errors.append(perr)

    deployment_id = ""
    deployment_name: str | None = None
    enabled_domains_t: tuple[str, ...] = ()
    if profile_document:
        did = profile_document.get("deployment_id")
        if isinstance(did, str) and did.strip():
            deployment_id = did.strip()
        dn = profile_document.get("deployment_name")
        if isinstance(dn, str) and dn.strip():
            deployment_name = dn.strip()
        ed = profile_document.get("enabled_domains")
        if isinstance(ed, list):
            enabled_domains_t = tuple(str(x).strip() for x in ed if isinstance(x, str) and str(x).strip())

    providers, pc = _parse_providers(provider_registry_document, warnings=warnings)
    applications, ac = _parse_applications(application_registry_document, warnings=warnings)
    adapters, nc = _parse_network_adapters(network_adapter_registry_document, warnings=warnings)

    return DeploymentConfig(
        deployment_dir=ddir,
        deployment_id=deployment_id,
        deployment_name=deployment_name,
        enabled_domains=enabled_domains_t,
        provider_count=pc,
        application_count=ac,
        network_adapter_count=nc,
        providers=providers,
        applications=applications,
        network_adapters=adapters,
        warnings=tuple(warnings),
        errors=tuple(errors),
        profile_document=profile_document,
        provider_registry_document=provider_registry_document,
        application_registry_document=application_registry_document,
        network_adapter_registry_document=network_adapter_registry_document,
    )
