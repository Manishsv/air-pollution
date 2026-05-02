from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


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

    if args.command == "deployment" and args.deployment_command == "run":
        return _run(_plan_deployment_run(repo_root, str(args.deployment_path)))

    if args.command == "registry" and args.registry_command == "check":
        # Keep this simple: supervisor already includes registry hygiene probes.
        return _run(_plan_supervisor(repo_root, domain=None, run_conformance=False))

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

