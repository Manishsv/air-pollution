from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ExecPlan:
    argv: list[str]
    cwd: Path


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(12):
        if (cur / "specifications" / "manifest.json").is_file() and (cur / "main.py").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve().parents[1]


def _run(plan: ExecPlan) -> int:
    proc = subprocess.run(plan.argv, cwd=str(plan.cwd))
    return int(proc.returncode)


def _plan_supervisor(repo_root: Path, *, domain: str | None, run_conformance: bool) -> ExecPlan:
    argv = [
        sys.executable,
        "tools/ai_dev_supervisor/run_review.py",
    ]
    if domain:
        argv += ["--domain", domain]
    if run_conformance:
        argv += ["--run-conformance"]
    return ExecPlan(argv=argv, cwd=repo_root)


def _plan_conformance(repo_root: Path) -> ExecPlan:
    return ExecPlan(argv=[sys.executable, "main.py", "--step", "conformance"], cwd=repo_root)


def _plan_deployment_validate(repo_root: Path, deployment: str) -> ExecPlan:
    return ExecPlan(
        argv=[
            sys.executable,
            "tools/deployment_runner/validate_deployment.py",
            "--deployment",
            deployment,
        ],
        cwd=repo_root,
    )


def _plan_deployment_run(repo_root: Path, deployment: str) -> ExecPlan:
    return ExecPlan(
        argv=[
            sys.executable,
            "tools/deployment_runner/run_deployment.py",
            "--deployment",
            deployment,
        ],
        cwd=repo_root,
    )


def _doctor(repo_root: Path, *, run_conformance: bool) -> int:
    print("AirOS doctor")
    print(f"- python: {sys.version.splitlines()[0]}")
    print(f"- platform: {platform.platform()}")
    print(f"- repo_root: {repo_root}")

    manifest = repo_root / "specifications" / "manifest.json"
    print(f"- manifest: {'ok' if manifest.is_file() else 'missing'} ({manifest})")

    folders = [
        "specifications/provider_contracts",
        "specifications/consumer_contracts",
        "specifications/domain_specs",
        "specifications/network_contracts",
        "specifications/registry_contracts",
        "deployments/examples",
    ]
    for rel in folders:
        p = repo_root / rel
        print(f"- {rel}: {'ok' if p.exists() else 'missing'}")

    # Delegates to the AI supervisor (no internals changed).
    return _run(_plan_supervisor(repo_root, domain=None, run_conformance=run_conformance))


def _deployment_validate(repo_root: Path, deployment: str) -> int:
    validator = repo_root / "tools" / "deployment_runner" / "validate_deployment.py"
    if not validator.is_file():
        print("Deployment validation is not implemented yet.")
        print("Recommended next task: add tools/deployment_runner/validate_deployment.py")
        return 2
    return _run(_plan_deployment_validate(repo_root, deployment))


def _parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    out: list[str] = []
    for part in value.split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out


def _read_yaml_template(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"Template YAML root must be an object: {path}")
    return doc


def _write_yaml(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _ensure_jurisdiction_ref(jurisdiction_id: str | None) -> str:
    if not jurisdiction_id:
        return "jurisdiction:PLACEHOLDER"
    j = jurisdiction_id.strip()
    if j.startswith("jurisdiction:"):
        return j
    return f"jurisdiction:{j}"


def _scaffold_provider_registry(
    template: dict,
    *,
    deployment_id: str,
    domains: list[str],
    provider_ids: list[str],
) -> dict:
    doc = dict(template)
    doc["deployment_id"] = deployment_id
    providers = template.get("providers")
    if provider_ids:
        kept: list[dict] = []
        if isinstance(providers, list):
            by_id = {p.get("provider_id"): p for p in providers if isinstance(p, dict)}
            for pid in provider_ids:
                if pid in by_id:
                    kept.append(by_id[pid])
        if not kept:
            kept = [
                {
                    "provider_id": pid,
                    "label": f"{pid} (placeholder)",
                    "domain_ids": domains or ["DOMAIN_PLACEHOLDER"],
                    "provider_contract": "PROVIDER_CONTRACT_PLACEHOLDER",
                    "connector_module": "CONNECTOR_MODULE_PLACEHOLDER",
                    "input_method": "api",
                    "output_platform_object_types": ["Observation"],
                    "examples": [],
                    "enabled_by_default": False,
                    "status": "placeholder",
                }
                for pid in provider_ids
            ]
        doc["providers"] = kept
    return doc


def _scaffold_application_registry(
    template: dict,
    *,
    deployment_id: str,
    application_ids: list[str],
) -> dict:
    doc = dict(template)
    doc["deployment_id"] = deployment_id
    apps = template.get("applications")
    if application_ids:
        kept: list[dict] = []
        if isinstance(apps, list):
            by_id = {a.get("application_id"): a for a in apps if isinstance(a, dict)}
            for aid in application_ids:
                if aid in by_id:
                    kept.append(by_id[aid])
        if not kept:
            kept = [
                {
                    "application_id": aid,
                    "label": f"{aid} (placeholder)",
                    "domain_id": "DOMAIN_PLACEHOLDER",
                    "consumer_contracts": ["CONSUMER_CONTRACT_PLACEHOLDER"],
                    "payload_builders": ["PAYLOAD_BUILDER_PLACEHOLDER"],
                    "sdk_api_outputs_consumed": [],
                    "packet_types": [],
                    "field_task_types": [],
                    "safety_gates_and_blocked_uses": ["specifications/domain_specs/DOMAIN.v1.yaml#blocked_uses"],
                    "examples": [],
                    "enabled_by_default": False,
                    "status": "placeholder",
                }
                for aid in application_ids
            ]
        doc["applications"] = kept
    return doc


def _scaffold_network_adapter_registry(
    template: dict,
    *,
    deployment_id: str,
    adapter_ids: list[str],
) -> dict:
    doc = dict(template)
    doc["deployment_id"] = deployment_id
    adapters = template.get("adapters")
    if adapter_ids:
        kept: list[dict] = []
        if isinstance(adapters, list):
            by_id = {a.get("adapter_id"): a for a in adapters if isinstance(a, dict)}
            for adid in adapter_ids:
                if adid in by_id:
                    kept.append(by_id[adid])
        if not kept:
            kept = [
                {
                    "adapter_id": adid,
                    "label": f"{adid} (placeholder)",
                    "supported_transport": "TRANSPORT_PLACEHOLDER",
                    "supported_network_contracts": ["network_message_envelope_v1"],
                    "configuration_ref": "DEPLOYMENT_LOCAL:CONFIG_PLACEHOLDER",
                    "enabled_by_default": False,
                    "status": "placeholder",
                    "notes": "No credentials here. Use deployment-local secrets/config stores.",
                }
                for adid in adapter_ids
            ]
        doc["adapters"] = kept
    return doc


def _deployment_init(
    repo_root: Path,
    *,
    deployment_id: str,
    deployment_name: str,
    deployment_type: str,
    owner_organization: str,
    environment: str,
    domains_csv: str,
    output_dir: str,
    agency_id: str | None,
    agency_name: str | None,
    agency_type: str | None,
    jurisdiction_type: str | None,
    jurisdiction_id: str | None,
    jurisdiction_name: str | None,
    providers_csv: str | None,
    applications_csv: str | None,
    network_adapters_csv: str | None,
    force: bool,
) -> int:
    templates_dir = repo_root / "deployments" / "templates"
    domains = _parse_csv(domains_csv)
    provider_ids = _parse_csv(providers_csv)
    application_ids = _parse_csv(applications_csv)
    adapter_ids = _parse_csv(network_adapters_csv)

    out_path = Path(output_dir)
    if not out_path.is_absolute():
        out_path = (repo_root / out_path).resolve()

    if out_path.exists():
        if not force:
            print(f"Output directory already exists: {out_path}")
            print("Re-run with --force to overwrite.")
            return 1
        if not out_path.is_dir():
            print(f"Output path exists and is not a directory: {out_path}")
            return 1
    out_path.mkdir(parents=True, exist_ok=True)

    # deployment_profile.yaml
    dep_template = _read_yaml_template(templates_dir / "deployment_profile.yaml") if templates_dir.exists() else {}
    dep_prof = dict(dep_template)
    dep_prof["deployment_id"] = deployment_id
    dep_prof["deployment_name"] = deployment_name
    dep_prof["deployment_type"] = deployment_type
    dep_prof["owner_organization"] = owner_organization
    dep_prof["environment"] = environment
    dep_prof["enabled_domains"] = domains or ["DOMAIN_PLACEHOLDER"]
    dep_prof["enabled_provider_registries"] = ["provider_registry.yaml"]
    dep_prof["enabled_application_registries"] = ["application_registry.yaml"]
    dep_prof["enabled_network_adapter_registries"] = ["network_adapter_registry.yaml"]
    dep_prof.setdefault(
        "no_secrets_notice",
        "No secrets, credentials, API keys, mailbox passwords, or restricted personal data belong in this workspace.",
    )
    _write_yaml(out_path / "deployment_profile.yaml", dep_prof)

    # provider_registry.yaml
    prov_template = _read_yaml_template(templates_dir / "provider_registry.yaml") if templates_dir.exists() else {"providers": []}
    prov_reg = _scaffold_provider_registry(prov_template, deployment_id=deployment_id, domains=domains, provider_ids=provider_ids)
    prov_reg["deployment_id"] = deployment_id
    _write_yaml(out_path / "provider_registry.yaml", prov_reg)

    # application_registry.yaml
    app_template = _read_yaml_template(templates_dir / "application_registry.yaml") if templates_dir.exists() else {"applications": []}
    app_reg = _scaffold_application_registry(app_template, deployment_id=deployment_id, application_ids=application_ids)
    app_reg["deployment_id"] = deployment_id
    _write_yaml(out_path / "application_registry.yaml", app_reg)

    # network_adapter_registry.yaml
    net_template = _read_yaml_template(templates_dir / "network_adapter_registry.yaml") if templates_dir.exists() else {"adapters": []}
    net_reg = _scaffold_network_adapter_registry(net_template, deployment_id=deployment_id, adapter_ids=adapter_ids)
    net_reg["deployment_id"] = deployment_id
    _write_yaml(out_path / "network_adapter_registry.yaml", net_reg)

    # agency_node_profile.yaml
    agency_template = _read_yaml_template(templates_dir / "agency_node_profile.yaml") if (templates_dir / "agency_node_profile.yaml").is_file() else {}
    agency_doc = dict(agency_template)
    agency_doc["node_id"] = f"node:{(agency_id or 'AGENCY_ID_PLACEHOLDER')}"
    agency_doc["agency_id"] = agency_id or "AGENCY_ID_PLACEHOLDER"
    agency_doc["agency_name"] = agency_name or "Agency Name Placeholder"
    agency_doc["agency_type"] = agency_type or agency_doc.get("agency_type") or "ulb"
    agency_doc["jurisdiction_type"] = jurisdiction_type or agency_doc.get("jurisdiction_type") or "city"
    agency_doc["jurisdiction_refs"] = [_ensure_jurisdiction_ref(jurisdiction_id)]
    agency_doc["enabled_domains"] = domains or ["DOMAIN_PLACEHOLDER"]
    agency_doc["data_sharing_policy_ref"] = f"policy:{deployment_id}"
    _write_yaml(out_path / "agency_node_profile.yaml", agency_doc)

    # network_participant_profile.yaml
    participant_template = _read_yaml_template(templates_dir / "network_participant_profile.yaml") if (templates_dir / "network_participant_profile.yaml").is_file() else {}
    participant_doc = dict(participant_template)
    participant_doc["participant_id"] = f"participant:{deployment_id}"
    participant_doc["node_id"] = agency_doc["node_id"]
    _write_yaml(out_path / "network_participant_profile.yaml", participant_doc)

    # jurisdiction_profile.yaml
    jurisdiction_template = _read_yaml_template(templates_dir / "jurisdiction_profile.yaml") if (templates_dir / "jurisdiction_profile.yaml").is_file() else {}
    jurisdiction_doc = dict(jurisdiction_template)
    jurisdiction_doc["jurisdiction_id"] = _ensure_jurisdiction_ref(jurisdiction_id)
    jurisdiction_doc["jurisdiction_type"] = jurisdiction_type or jurisdiction_doc.get("jurisdiction_type") or "city"
    jurisdiction_doc["name"] = jurisdiction_name or jurisdiction_doc.get("name") or "Jurisdiction Name Placeholder"
    _write_yaml(out_path / "jurisdiction_profile.yaml", jurisdiction_doc)

    # data_sharing_policy.yaml
    policy_template = _read_yaml_template(templates_dir / "data_sharing_policy.yaml") if (templates_dir / "data_sharing_policy.yaml").is_file() else {}
    policy_doc = dict(policy_template)
    policy_doc["policy_id"] = f"policy:{deployment_id}"
    policy_doc["allowed_jurisdiction_refs"] = [_ensure_jurisdiction_ref(jurisdiction_id)]
    policy_doc["allowed_senders"] = [agency_doc["node_id"]]
    policy_doc["allowed_receivers"] = [agency_doc["node_id"]]
    _write_yaml(out_path / "data_sharing_policy.yaml", policy_doc)

    # README.md
    (out_path / "README.md").write_text(
        "\n".join(
            [
                "# AirOS deployment workspace (scaffolded)",
                "",
                "This folder was generated from `deployments/templates/` via the AirOS CLI.",
                "",
                "## Next steps",
                "",
                "- Review and edit the generated YAML files (replace placeholders).",
                "- Validate config:",
                "  - `python tools/deployment_runner/validate_deployment.py --deployment <this-folder>`",
                "- Run conformance:",
                "  - `python main.py --step conformance`",
                "- Do not commit secrets, credentials, API keys, mailbox passwords, restricted datasets, or sensitive operational details to the public AirOS repository.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Initialized deployment workspace at: {out_path}")
    print("Next steps:")
    print("- Review generated YAML and replace placeholders.")
    print(f"- Validate: {sys.executable} tools/deployment_runner/validate_deployment.py --deployment {out_path}")
    print(f"- Conformance: {sys.executable} main.py --step conformance")
    print("- Do not commit sensitive deployment data to the public repo.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airos", description="Minimal AirOS CLI (thin wrappers over existing tools).")
    sub = p.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Health summary + optional supervisor checks.")
    doctor.add_argument("--run-conformance", action="store_true", help="Run conformance as part of the supervisor review.")

    sub.add_parser("conformance", help="Run conformance checks (main.py --step conformance).")

    review = sub.add_parser("review", help="Run AI supervisor review.")
    review.add_argument("--run-conformance", action="store_true", help="Run conformance as part of the review.")

    domain = sub.add_parser("domain", help="Domain-focused commands.")
    domain_sub = domain.add_subparsers(dest="domain_command", required=True)
    domain_review = domain_sub.add_parser("review", help="Run AI supervisor review for a domain.")
    domain_review.add_argument("domain_id", type=str)
    domain_review.add_argument("--run-conformance", action="store_true")

    deployment = sub.add_parser("deployment", help="Deployment-focused commands.")
    dep_sub = deployment.add_subparsers(dest="deployment_command", required=True)
    dep_validate = dep_sub.add_parser("validate", help="Validate a deployment configuration directory.")
    dep_validate.add_argument("deployment_path", type=str)
    dep_run = dep_sub.add_parser("run", help="Run a registry-driven deployment (POC).")
    dep_run.add_argument("deployment_path", type=str)
    dep_init = dep_sub.add_parser("init", help="Initialize a deployment workspace from templates.")
    dep_init.add_argument("--deployment-id", required=True, type=str)
    dep_init.add_argument("--deployment-name", required=True, type=str)
    dep_init.add_argument(
        "--deployment-type",
        required=True,
        type=str,
        choices=[
            "single_agency",
            "multi_agency_city",
            "multi_city_agency",
            "state_coordination",
            "regional_corridor",
            "public_transparency",
        ],
    )
    dep_init.add_argument("--owner-organization", required=True, type=str)
    dep_init.add_argument("--environment", required=True, type=str, choices=["local", "staging", "production"])
    dep_init.add_argument("--domains", required=True, type=str, help="Comma-separated domain ids.")
    dep_init.add_argument("--output-dir", required=True, type=str)
    dep_init.add_argument("--agency-id", type=str, default=None)
    dep_init.add_argument("--agency-name", type=str, default=None)
    dep_init.add_argument("--agency-type", type=str, default=None)
    dep_init.add_argument("--jurisdiction-type", type=str, default=None, choices=["city", "multi_city", "district", "regional", "state", "national"])
    dep_init.add_argument("--jurisdiction-id", type=str, default=None)
    dep_init.add_argument("--jurisdiction-name", type=str, default=None)
    dep_init.add_argument("--providers", type=str, default=None, help="Comma-separated provider ids.")
    dep_init.add_argument("--applications", type=str, default=None, help="Comma-separated application ids.")
    dep_init.add_argument("--network-adapters", type=str, default=None, help="Comma-separated adapter ids.")
    dep_init.add_argument("--force", action="store_true")

    sub.add_parser("registry", help="Registry hygiene checks (via supervisor).").add_subparsers(
        dest="registry_command", required=True
    ).add_parser("check", help="Run supervisor review and surface registry hygiene info.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = _find_repo_root(Path(__file__).resolve())

    if args.command == "doctor":
        return _doctor(repo_root, run_conformance=bool(args.run_conformance))

    if args.command == "conformance":
        return _run(_plan_conformance(repo_root))

    if args.command == "review":
        return _run(_plan_supervisor(repo_root, domain=None, run_conformance=bool(args.run_conformance)))

    if args.command == "domain" and args.domain_command == "review":
        return _run(
            _plan_supervisor(repo_root, domain=str(args.domain_id), run_conformance=bool(args.run_conformance))
        )

    if args.command == "deployment" and args.deployment_command == "validate":
        return _deployment_validate(repo_root, str(args.deployment_path))

    if args.command == "deployment" and args.deployment_command == "init":
        return _deployment_init(
            repo_root,
            deployment_id=str(args.deployment_id),
            deployment_name=str(args.deployment_name),
            deployment_type=str(args.deployment_type),
            owner_organization=str(args.owner_organization),
            environment=str(args.environment),
            domains_csv=str(args.domains),
            output_dir=str(args.output_dir),
            agency_id=args.agency_id,
            agency_name=args.agency_name,
            agency_type=args.agency_type,
            jurisdiction_type=args.jurisdiction_type,
            jurisdiction_id=args.jurisdiction_id,
            jurisdiction_name=args.jurisdiction_name,
            providers_csv=args.providers,
            applications_csv=args.applications,
            network_adapters_csv=args.network_adapters,
            force=bool(args.force),
        )

    if args.command == "deployment" and args.deployment_command == "run":
        return _run(_plan_deployment_run(repo_root, str(args.deployment_path)))

    if args.command == "registry" and args.registry_command == "check":
        # Keep this simple: supervisor already includes registry hygiene probes.
        return _run(_plan_supervisor(repo_root, domain=None, run_conformance=False))

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

