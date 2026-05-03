from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Support `python tools/airos_cli.py ...` (repo root may not be on sys.path yet).
_CLI_FILE = Path(__file__).resolve()
_REPO_ROOT_FOR_IMPORTS = _CLI_FILE.parents[1]
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from tools.deployment_runner.validate_deployment import ValidationSummary, validate_deployment


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
    rc = int(proc.returncode)
    if rc != 0:
        print(f"(subprocess exited with code {rc})", file=sys.stderr)
    return rc


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


def _resolve_deployment_dir(repo_root: Path, deployment_path: str) -> Path:
    p = Path(deployment_path)
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def _print_validation_summary(summary: ValidationSummary) -> None:
    status = "valid" if not summary.errors else "invalid"
    print("AirOS deployment validation")
    print(f"- status: {status}")
    print(f"- deployment_id: {summary.deployment_id or '<unknown>'}")
    print(f"- enabled_domains: {', '.join(summary.enabled_domains) if summary.enabled_domains else '<none>'}")
    print(f"- provider_count: {summary.provider_count}")
    print(f"- application_count: {summary.application_count}")
    print(f"- network_adapter_count: {summary.network_adapter_count}")
    if summary.warnings:
        print("- warnings:")
        for w in summary.warnings:
            print(f"  - {w}")
    else:
        print("- warnings: (none)")
    if summary.errors:
        print("- errors:")
        for e in summary.errors:
            print(f"  - {e}")
    else:
        print("- errors: (none)")
    print(f"- recommended_next_task: {summary.recommended_next_task}")


def _deployment_validate(repo_root: Path, deployment: str) -> int:
    validator = repo_root / "tools" / "deployment_runner" / "validate_deployment.py"
    if not validator.is_file():
        print("Deployment validation is not implemented yet.")
        print("Recommended next task: add tools/deployment_runner/validate_deployment.py")
        return 2
    dep_dir = _resolve_deployment_dir(repo_root, deployment)
    if not dep_dir.exists():
        print(f"Deployment path not found: {dep_dir}", file=sys.stderr)
        return 1
    if not dep_dir.is_dir():
        print(f"Deployment path is not a directory: {dep_dir}", file=sys.stderr)
        return 1
    summary = validate_deployment(deployment_dir=dep_dir, repo_root=repo_root)
    _print_validation_summary(summary)
    return 1 if summary.errors else 0


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
                "- Validate config (config-only):",
                "  - `python tools/airos_cli.py deployment validate <this-folder>`",
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
    rel = out_path
    try:
        rel = out_path.relative_to(repo_root)
    except ValueError:
        pass
    print("Next steps:")
    print("1) Edit the generated YAML (replace PLACEHOLDER values; align provider_contract and consumer_contracts with manifest keys).")
    print(
        "   Note: this workspace is scaffolding unless your provider/application IDs match a supported in-repo demo "
        "(e.g. flood fixtures: deployments/examples/flood_local_demo)."
    )
    print(f"2) Validate config only: {sys.executable} tools/airos_cli.py deployment validate {rel}")
    print(f"3) When valid and configured for a supported demo, run: {sys.executable} tools/airos_cli.py deployment run <path>")
    print(f"4) Inspect outputs under data/outputs/deployments/<deployment_id>/ after a successful run.")
    print(f"5) Run governance checks: {sys.executable} tools/airos_cli.py review --run-conformance")
    print(f"   (and {sys.executable} main.py --step conformance as needed)")
    print("- Do not commit secrets, credentials, API keys, restricted datasets, or sensitive operational data.")
    return 0


_DEPLOYMENT_INIT_EPILOG = """Example:
  python tools/airos_cli.py deployment init --deployment-id my_city --deployment-name "My City" \\
    --deployment-type single_agency --owner-organization "Demo Org" --environment local \\
    --domains air_quality --output-dir deployments/local/my_city

Notes:
  - Output is scaffolding from deployments/templates/; it is not guaranteed runnable until placeholders are fixed.
  - For a ready-made fixture demo (flood), use: deployments/examples/flood_local_demo
"""

_DEPLOYMENT_PATH_HELP = "Deployment directory path (relative to repo root or absolute)."


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="airos",
        description="AirOS CLI: thin wrappers over conformance, supervisor review, and deployment tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Typical flow: deployment init → deployment validate → deployment run (supported demo) → review --run-conformance",
    )
    sub = p.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser(
        "doctor",
        help="Print environment/repo health and run the AI supervisor (optional conformance).",
        description="Shows Python version, detected repo root, key spec folders, then runs tools/ai_dev_supervisor/run_review.py.",
    )
    doctor.add_argument("--run-conformance", action="store_true", help="Run conformance as part of the supervisor review.")

    sub.add_parser("conformance", help="Run python main.py --step conformance.")

    review = sub.add_parser(
        "review",
        help="Run the AI supervisor review.",
        description="Runs tools/ai_dev_supervisor/run_review.py (registry hygiene, deployment examples, domain maturity when --domain is used elsewhere).",
    )
    review.add_argument("--run-conformance", action="store_true", help="Also run the conformance step inside the supervisor.")

    domain = sub.add_parser("domain", help="Domain-scoped supervisor commands.")
    domain_sub = domain.add_subparsers(dest="domain_command", required=True)
    domain_review = domain_sub.add_parser(
        "review",
        help="Run supervisor review for one domain checklist.",
        description="Equivalent to run_review.py --domain <id>.",
    )
    domain_review.add_argument("domain_id", type=str, help="Domain id (e.g. air_quality, flood_risk, property_buildings).")
    domain_review.add_argument("--run-conformance", action="store_true")

    deployment = sub.add_parser(
        "deployment",
        help="Initialize, validate, or run a deployment workspace.",
        description="init: scaffold YAML from templates. validate: config-only checks (no connectors). run: POC runner (allowlisted).",
    )
    dep_sub = deployment.add_subparsers(dest="deployment_command", required=True)
    dep_validate = dep_sub.add_parser(
        "validate",
        help="Validate deployment YAML and registry references (no execution).",
        description=(
            "Loads deployment_profile.yaml, provider/application registries, optional profiles, and checks manifest "
            "artifact keys, required fields, fixture paths, and obvious secret-like keys. Does not run connectors or pipelines."
        ),
    )
    dep_validate.add_argument("deployment_path", type=str, help=_DEPLOYMENT_PATH_HELP)
    dep_run = dep_sub.add_parser(
        "run",
        help="Run the registry-driven deployment POC (fixtures / allowlist).",
        description=(
            "Runs tools/deployment_runner/run_deployment.py for deployments that the POC supports (e.g. flood_local_demo). "
            "Exits non-zero on failure; stderr/stdout are not captured."
        ),
    )
    dep_run.add_argument("deployment_path", type=str, help=_DEPLOYMENT_PATH_HELP)
    dep_init = dep_sub.add_parser(
        "init",
        help="Create a deployment workspace from templates (scaffolding).",
        description=(
            "Writes deployment_profile.yaml, registries, optional profiles, and README under --output-dir. "
            "Uses deployments/templates/ when present. Pass --force to overwrite an existing directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_DEPLOYMENT_INIT_EPILOG,
    )
    dep_init.add_argument("--deployment-id", required=True, type=str, metavar="ID", help="Stable deployment identifier.")
    dep_init.add_argument("--deployment-name", required=True, type=str, metavar="NAME", help="Human-readable deployment name.")
    dep_init.add_argument(
        "--deployment-type",
        required=True,
        type=str,
        metavar="TYPE",
        choices=[
            "single_agency",
            "multi_agency_city",
            "multi_city_agency",
            "state_coordination",
            "regional_corridor",
            "public_transparency",
        ],
        help="Deployment topology / coordination mode.",
    )
    dep_init.add_argument("--owner-organization", required=True, type=str, metavar="ORG", help="Owning organization label or placeholder.")
    dep_init.add_argument(
        "--environment",
        required=True,
        type=str,
        metavar="ENV",
        choices=["local", "staging", "production"],
        help="Runtime environment label.",
    )
    dep_init.add_argument(
        "--domains",
        required=True,
        type=str,
        metavar="LIST",
        help="Comma-separated enabled domain ids (e.g. air_quality,flood_risk).",
    )
    dep_init.add_argument(
        "--output-dir",
        required=True,
        type=str,
        metavar="DIR",
        help="Directory to create (absolute, or relative to repo root). Fails if it exists unless --force.",
    )
    dep_init.add_argument("--agency-id", type=str, default=None, metavar="ID", help="Optional agency id for agency_node_profile.")
    dep_init.add_argument("--agency-name", type=str, default=None, metavar="NAME", help="Optional agency display name.")
    dep_init.add_argument("--agency-type", type=str, default=None, metavar="TYPE", help="Optional agency type (e.g. ulb, pcb).")
    dep_init.add_argument(
        "--jurisdiction-type",
        type=str,
        default=None,
        choices=["city", "multi_city", "district", "regional", "state", "national"],
        metavar="TYPE",
        help="Optional jurisdiction type for profiles.",
    )
    dep_init.add_argument("--jurisdiction-id", type=str, default=None, metavar="ID", help="Optional jurisdiction id (with or without jurisdiction: prefix).")
    dep_init.add_argument("--jurisdiction-name", type=str, default=None, metavar="NAME", help="Optional jurisdiction display name.")
    dep_init.add_argument(
        "--providers",
        type=str,
        default=None,
        metavar="LIST",
        help="Optional comma-separated provider_id values. Unknown ids become placeholder rows (not runnable until fixed).",
    )
    dep_init.add_argument(
        "--applications",
        type=str,
        default=None,
        metavar="LIST",
        help="Optional comma-separated application_id values. Unknown ids become placeholder rows.",
    )
    dep_init.add_argument(
        "--network-adapters",
        type=str,
        default=None,
        metavar="LIST",
        help="Optional comma-separated adapter_id values for network_adapter_registry.yaml.",
    )
    dep_init.add_argument("--force", action="store_true", help="Overwrite an existing output directory.")

    reg = sub.add_parser("registry", help="Registry hygiene via the AI supervisor.")
    reg_sub = reg.add_subparsers(dest="registry_command", required=True)
    reg_sub.add_parser(
        "check",
        help="Run supervisor review (registry probe surfaces in the report).",
        description="Runs tools/ai_dev_supervisor/run_review.py without --run-conformance (fast).",
    )

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

