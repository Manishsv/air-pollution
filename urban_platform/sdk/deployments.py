from __future__ import annotations

from pathlib import Path
from typing import Any

from urban_platform.deployments.config_loader import load_deployment_config
from urban_platform.specifications.conformance import SPEC_ROOT


def _repo_root() -> Path:
    return SPEC_ROOT.parent.resolve()


def _examples_root() -> Path:
    return (_repo_root() / "deployments" / "examples").resolve()


def _read_first_paragraph(readme_path: Path) -> str:
    try:
        lines = readme_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    buf: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if buf:
                break
            continue
        if s.startswith("#") and not buf:
            # skip title-only headers
            continue
        buf.append(s)
    return " ".join(buf).strip()


def _deployment_dir_summary(deployment_dir: Path) -> dict[str, Any] | None:
    repo_root = _repo_root()
    try:
        rel = deployment_dir.resolve().relative_to(repo_root)
    except Exception:
        return None

    cfg = load_deployment_config(deployment_dir)
    profile = cfg.profile_document or {}
    deployment_id = cfg.deployment_id or str(profile.get("deployment_id") or "").strip() or deployment_dir.name
    deployment_name = cfg.deployment_name or str(profile.get("deployment_name") or "").strip() or None

    desc = ""
    readme = deployment_dir / "README.md"
    if readme.is_file():
        desc = _read_first_paragraph(readme)
    if not desc:
        notes = profile.get("notes")
        if isinstance(notes, str):
            desc = notes.strip().splitlines()[0].strip()

    return {
        "deployment_id": deployment_id,
        "deployment_name": deployment_name or "",
        "path": str(rel).replace("\\", "/"),
        "enabled_domains": list(cfg.enabled_domains),
        "provider_count": int(cfg.provider_count),
        "application_count": int(cfg.application_count),
        "has_provider_registry": (deployment_dir / "provider_registry.yaml").is_file(),
        "has_application_registry": (deployment_dir / "application_registry.yaml").is_file(),
        "has_network_adapter_registry": (deployment_dir / "network_adapter_registry.yaml").is_file(),
        "description": desc,
    }


def list_deployment_profiles() -> list[dict[str, Any]]:
    root = _examples_root()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        if not (d / "deployment_profile.yaml").is_file():
            continue
        s = _deployment_dir_summary(d)
        if s:
            out.append(s)
    return out


def list_deployment_ids() -> list[str]:
    ids: list[str] = []
    for p in list_deployment_profiles():
        did = p.get("deployment_id")
        if isinstance(did, str) and did.strip():
            ids.append(did.strip())
    return sorted(set(ids))


def get_deployment_profile(deployment_id: str) -> dict[str, Any] | None:
    did = str(deployment_id or "").strip()
    if not did:
        return None
    root = _examples_root()
    if not root.is_dir():
        return None
    # In examples, folder name == deployment_id, but fall back to scanning safely.
    direct = (root / did).resolve()
    if direct.is_dir() and (direct / "deployment_profile.yaml").is_file():
        cfg = load_deployment_config(direct)
        summary = _deployment_dir_summary(direct) or {}
        repo_root = _repo_root()
        rel = str(direct.relative_to(repo_root)).replace("\\", "/")
        return {
            **summary,
            "relative_path": rel,
            "deployment_profile": cfg.profile_document or {},
            "provider_registry": cfg.provider_registry_document or {},
            "application_registry": cfg.application_registry_document or {},
            "network_adapter_registry": cfg.network_adapter_registry_document or {},
            "provider_registrations": [
                {
                    "provider_id": p.provider_id,
                    "domain_ids": list(p.domain_ids),
                    "provider_contract": p.provider_contract,
                    "fixture_path": p.fixture_path,
                    "enabled_by_default": p.enabled_by_default,
                    "label": p.label,
                }
                for p in cfg.providers
            ],
            "application_registrations": [
                {
                    "application_id": a.application_id,
                    "domain_id": a.domain_id,
                    "consumer_contracts": list(a.consumer_contracts),
                    "enabled_by_default": a.enabled_by_default,
                    "label": a.label,
                }
                for a in cfg.applications
            ],
            "network_adapter_registrations": [
                {
                    "adapter_id": a.adapter_id,
                    "supported_transport": a.supported_transport,
                    "supported_network_contracts": list(a.supported_network_contracts),
                }
                for a in cfg.network_adapters
            ],
            "warnings": list(cfg.warnings),
            "errors": list(cfg.errors),
        }

    # Fallback scan (handles rare mismatch between folder name and deployment_id).
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        if not d.is_dir() or not (d / "deployment_profile.yaml").is_file():
            continue
        cfg = load_deployment_config(d)
        if (cfg.deployment_id or "").strip() == did:
            return get_deployment_profile(d.name)

    return None

