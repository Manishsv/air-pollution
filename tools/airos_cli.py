from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

import yaml

# Support `python tools/airos_cli.py ...` (repo root may not be on sys.path yet).
_CLI_FILE = Path(__file__).resolve()
_REPO_ROOT_FOR_IMPORTS = _CLI_FILE.parents[1]
if str(_REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORTS))

from tools.deployment_runner.validate_deployment import ValidationSummary, validate_deployment

from urban_platform import sdk as air_sdk


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


def _plan_deployment_run(repo_root: Path, deployment: str, *, store_dir: str | None = None) -> ExecPlan:
    argv: list[str] = [
        sys.executable,
        "tools/deployment_runner/run_deployment.py",
        "--deployment",
        deployment,
    ]
    if store_dir:
        argv += ["--store-dir", store_dir]
    return ExecPlan(argv=argv, cwd=repo_root)


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


def _read_yaml_file(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return doc


def _read_first_line(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s:
                return s
    except Exception:
        return None
    return None


def _examples_root(repo_root: Path) -> Path:
    return (repo_root / "deployments" / "examples").resolve()


def _example_dirs(repo_root: Path) -> list[Path]:
    root = _examples_root(repo_root)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir(), key=lambda x: x.name):
        if p.is_dir() and (p / "deployment_profile.yaml").is_file():
            out.append(p)
    return out


def _example_summary_row(repo_root: Path, example_dir: Path) -> dict:
    prof_path = example_dir / "deployment_profile.yaml"
    prof = _read_yaml_file(prof_path)
    deployment_id = str(prof.get("deployment_id") or "—")
    enabled_domains = prof.get("enabled_domains") or []
    if not isinstance(enabled_domains, list):
        enabled_domains = []
    enabled_domains = [str(x) for x in enabled_domains if x]

    readme = example_dir / "README.md"
    desc = _read_first_line(readme) if readme.is_file() else None
    if desc and desc.startswith("#"):
        desc = desc.lstrip("#").strip()

    return {
        "name": example_dir.name,
        "path": str(example_dir.relative_to(repo_root)),
        "deployment_id": deployment_id,
        "enabled_domains": enabled_domains,
        "description": desc or "",
    }


def _examples_list(repo_root: Path) -> int:
    rows = [_example_summary_row(repo_root, d) for d in _example_dirs(repo_root)]
    if not rows:
        print("No examples found under deployments/examples/")
        return 0

    print("AirOS examples (deployments/examples)")
    for r in rows:
        dom = ", ".join(r["enabled_domains"]) if r["enabled_domains"] else "—"
        line = f"- {r['name']}  (deployment_id={r['deployment_id']}, domains={dom})"
        print(line)
        if r["description"]:
            print(f"  {r['description']}")
    return 0


def _examples_describe(repo_root: Path, name: str) -> int:
    example_dir = (_examples_root(repo_root) / name).resolve()
    if not example_dir.is_dir():
        print(f"Example not found: deployments/examples/{name}", file=sys.stderr)
        print("Run: python tools/airos_cli.py examples list", file=sys.stderr)
        return 1

    prof_path = example_dir / "deployment_profile.yaml"
    if not prof_path.is_file():
        print(f"Invalid example (missing deployment_profile.yaml): {example_dir}", file=sys.stderr)
        return 1

    prof = _read_yaml_file(prof_path)
    deployment_id = str(prof.get("deployment_id") or "—")
    enabled_domains = prof.get("enabled_domains") or []
    if not isinstance(enabled_domains, list):
        enabled_domains = []
    enabled_domains = [str(x) for x in enabled_domains if x]

    provider_count = 0
    application_count = 0
    prov_reg_paths = prof.get("enabled_provider_registries") or []
    app_reg_paths = prof.get("enabled_application_registries") or []

    def _count_items(rel_paths: list, *, key: str) -> int:
        n = 0
        for rp in rel_paths:
            if not isinstance(rp, str) or not rp.strip():
                continue
            p = (repo_root / rp).resolve() if not Path(rp).is_absolute() else Path(rp).resolve()
            if not p.is_file():
                continue
            try:
                doc = _read_yaml_file(p)
                items = doc.get(key) or []
                if isinstance(items, list):
                    n += len([x for x in items if isinstance(x, dict)])
            except Exception:
                continue
        return n

    provider_count = _count_items(prov_reg_paths, key="providers")
    application_count = _count_items(app_reg_paths, key="applications")

    files_present = sorted([p.name for p in example_dir.iterdir() if p.is_file()])
    rel = str(example_dir.relative_to(repo_root))
    dom = ", ".join(enabled_domains) if enabled_domains else "—"

    print("AirOS example description")
    print(f"- name: {name}")
    print(f"- path: {rel}")
    print(f"- deployment_id: {deployment_id}")
    print(f"- enabled_domains: {dom}")
    print(f"- provider_count: {provider_count}")
    print(f"- application_count: {application_count}")
    print(f"- files: {', '.join(files_present) if files_present else '—'}")
    print("Recommended commands:")
    print(f"- validate: {sys.executable} tools/airos_cli.py deployment validate {rel}")
    print(f"- run: {sys.executable} tools/airos_cli.py deployment run {rel}")
    return 0


def _deployments_list(repo_root: Path) -> int:
    # Alias for clarity: examples == deployment examples (read-only metadata).
    return _examples_list(repo_root)


def _deployments_show(repo_root: Path, deployment_id: str) -> int:
    # Alias for clarity: deployment_id maps to the example folder name in deployments/examples/.
    return _examples_describe(repo_root, str(deployment_id or "").strip())


def _inventory(*, include_runtime: bool) -> int:
    inv = air_sdk.get_platform_inventory(include_runtime=include_runtime)

    print("AirOS Platform Inventory")
    print()

    contracts = inv.get("contracts") or {}
    apps = inv.get("apps") or {}
    adapters = inv.get("adapters") or {}
    catalogs = inv.get("catalogs") or {}
    deployments = inv.get("deployments") or {}

    print(f"Contracts: {int(contracts.get('contract_count') or 0)}")
    print(f"Apps: {int(apps.get('app_count') or 0)}")
    for x in (apps.get("app_ids") or []) if isinstance(apps.get("app_ids"), list) else []:
        print(f"  - {x}")
    print(f"Provider adapters: {int(adapters.get('adapter_count') or 0)}")
    for x in (adapters.get("adapter_ids") or []) if isinstance(adapters.get("adapter_ids"), list) else []:
        print(f"  - {x}")
    print(f"Reference catalogs: {int(catalogs.get('catalog_count') or 0)}")
    for x in (catalogs.get("catalog_ids") or []) if isinstance(catalogs.get("catalog_ids"), list) else []:
        print(f"  - {x}")
    print(f"Deployments: {int(deployments.get('deployment_count') or 0)}")
    for x in (deployments.get("deployment_ids") or []) if isinstance(deployments.get("deployment_ids"), list) else []:
        print(f"  - {x}")

    rt = inv.get("runtime") or {}
    if not include_runtime:
        print()
        print("Runtime store: not included. Use --include-runtime to inspect local store counts.")
        return 0

    print()
    if rt.get("runtime_available") is False:
        print("Runtime store: unavailable (no local store directory found).")
        note = rt.get("note")
        if isinstance(note, str) and note.strip():
            print(note.strip())
        return 0

    print("Runtime store:")
    print(f"Records: {int(rt.get('record_count') or 0)}")
    print(f"Runs: {int(rt.get('run_count') or 0)}")
    print(f"Outputs: {int(rt.get('output_count') or 0)}")
    print(f"Validation receipts: {int(rt.get('validation_receipt_count') or 0)}")
    print(f"Audit events: {int(rt.get('audit_event_count') or 0)}")
    return 0


def _evidence_export(
    repo_root: Path,
    *,
    run_id: str | None,
    deployment_id: str | None,
    store_dir: str,
    output_dir: str,
) -> int:
    rid = str(run_id or "").strip() or None
    did = str(deployment_id or "").strip() or None
    if (rid is None and did is None) or (rid is not None and did is not None):
        print("Exactly one of --run-id or --deployment-id is required.", file=sys.stderr)
        return 2

    sdir = Path(store_dir)
    sdir = sdir.resolve() if sdir.is_absolute() else (repo_root / sdir).resolve()
    if not sdir.exists() or not sdir.is_dir():
        print(f"store-dir not found: {sdir}", file=sys.stderr)
        return 2

    odir = Path(output_dir)
    odir = odir.resolve() if odir.is_absolute() else (repo_root / odir).resolve()
    odir.mkdir(parents=True, exist_ok=True)

    try:
        z = air_sdk.export_evidence_bundle(store_dir=sdir, output_dir=odir, run_id=rid, deployment_id=did)
    except Exception as exc:  # noqa: BLE001
        print(f"Evidence export failed: {exc}", file=sys.stderr)
        return 1

    try:
        import zipfile

        with zipfile.ZipFile(z, "r") as zz:
            names = set(zz.namelist())
        ok = {
            "README.md",
            "manifest.json",
            "runs.json",
            "records.json",
            "outputs.json",
            "validation_receipts.json",
            "audit_events.json",
            "safety_notes.md",
        }.issubset(names)
    except Exception:
        ok = True

    print("AirOS evidence bundle exported (read-only)")
    print(f"- path: {z}")
    if not ok:
        print("- warning: bundle missing expected files", file=sys.stderr)
    print("- note: traceability evidence only; not approval evidence")
    return 0


def _evidence_inspect(repo_root: Path, *, bundle_zip: str) -> int:
    p = Path(bundle_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Bundle not found: {bp}", file=sys.stderr)
        return 2

    try:
        rep = air_sdk.inspect_evidence_bundle(bundle_path=bp)
    except Exception as exc:  # noqa: BLE001
        print(f"Evidence bundle inspection failed: {exc}", file=sys.stderr)
        return 1

    b = rep.get("bundle") or {}
    runs = rep.get("runs") or {}
    outputs = rep.get("outputs") or {}
    vr = rep.get("validation_receipts") or {}
    audits = rep.get("audit_events") or {}
    hm = rep.get("hash_manifest") or {}

    print("AirOS evidence bundle inspection (read-only)")
    print()
    print("Bundle")
    print(f"- bundle_id: {b.get('bundle_id')}")
    print(f"- created_at: {b.get('created_at')}")
    if b.get("run_id"):
        print(f"- run_id: {b.get('run_id')}")
    if b.get("deployment_id"):
        print(f"- deployment_id: {b.get('deployment_id')}")
    print(f"- counts: {b.get('counts')}")
    print()
    print("Runs")
    sc = runs.get("status_counts") or {}
    print(f"- count: {runs.get('count')}")
    print(f"- status_counts: {sc}")
    print()
    print("Outputs")
    print(f"- count: {outputs.get('count')}")
    cks = outputs.get("contract_keys") or []
    if cks:
        print("- contract_keys:")
        for ck in cks:
            print(f"  - {ck}")
    print()
    print("Validation receipts")
    print(f"- count: {vr.get('count')}")
    print(f"- invalid_count: {vr.get('invalid_count')}")
    if int(vr.get("invalid_count") or 0) > 0:
        print()
        print("Needs attention (invalid validations)")
        for r in (vr.get("invalid_receipts") or [])[:25]:
            print(
                f"- {r.get('receipt_id')}  contract={r.get('contract_key')}  "
                f"target={r.get('validation_target_type')}:{r.get('validation_target_id')}  "
                f"errors={r.get('error_count')}"
            )
    print()
    print("Audit events")
    print(f"- count: {audits.get('count')}")
    print()
    print("Hash manifest")
    present = hm.get("present")
    print(f"- present: {present}")
    if present:
        print(f"- algorithm: {hm.get('algorithm')}")
        print(f"- hashed_files: {hm.get('hashed_file_count')}")
    print()
    print("Safety notes")
    print(f"- present: {bool(rep.get('safety_notes_present'))}")
    print()
    print("Result")
    print("Evidence bundle inspection is read-only. It does not approve, execute, import, or publish anything.")
    return 0


def _evidence_verify(repo_root: Path, *, bundle_zip: str) -> int:
    p = Path(bundle_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Bundle not found: {bp}", file=sys.stderr)
        return 2

    try:
        rep = air_sdk.verify_evidence_bundle(bundle_path=bp)
    except Exception as exc:  # noqa: BLE001
        print(f"Evidence bundle verification failed: {exc}", file=sys.stderr)
        return 1

    print("AirOS evidence bundle verification (read-only)")
    print(f"- status: {rep.get('status')}")
    print(f"- counts: {rep.get('counts')}")
    print(f"- note: {rep.get('note')}")
    print("- note: verification checks internal consistency + hashes only; it is not a digital signature, approval, or certification.")

    warns = rep.get("warnings") or []
    errs = rep.get("errors") or []
    if warns:
        print()
        print("Warnings")
        for w in warns[:50]:
            print(f"- {w}")
    if errs:
        print()
        print("Errors")
        for e in errs[:50]:
            print(f"- {e}")

    print()
    print("Result")
    print(
        "Evidence verification checks internal consistency only. It does not approve, certify, execute, import, or publish anything."
    )

    if str(rep.get("status") or "") == "invalid":
        return 1
    return 0


def _evidence_redact(repo_root: Path, *, bundle_zip: str, profile: str, output_dir: str) -> int:
    p = Path(bundle_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Bundle not found: {bp}", file=sys.stderr)
        return 2

    od = Path(output_dir)
    odir = od.resolve() if od.is_absolute() else (repo_root / od).resolve()
    odir.mkdir(parents=True, exist_ok=True)

    prof = str(profile or "").strip()
    if prof not in ("public_demo", "internal_review"):
        print("Invalid profile. Must be one of: public_demo, internal_review", file=sys.stderr)
        return 2

    try:
        outp = air_sdk.redact_evidence_bundle(bundle_path=bp, output_dir=odir, profile=prof)
        rep = air_sdk.inspect_evidence_bundle(bundle_path=outp)
    except Exception as exc:  # noqa: BLE001
        print(f"Evidence bundle redaction failed: {exc}", file=sys.stderr)
        return 1

    print("AirOS evidence bundle redaction (read-only)")
    print(f"- profile: {prof}")
    print(f"- redacted_bundle: {outp}")
    try:
        # best-effort: read fields_redacted_count
        import zipfile
        import json

        with zipfile.ZipFile(outp, "r") as zz:
            rr = json.loads(zz.read("redaction_report.json").decode("utf-8"))
        if isinstance(rr, dict):
            print(f"- fields_redacted_count: {rr.get('fields_redacted_count')}")
    except Exception:
        pass
    print("- note: redaction creates a sharing copy; it does not approve, certify, sign, execute, import, or publish anything.")
    return 0


def _health_local(repo_root: Path) -> int:
    # Local health is read-only and does not require the API to be running.
    # It loads governed metadata and reports counts; it does not execute builders or deployments.
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed = False

    def ok(name: str, **extra: Any) -> None:
        checks.append({"name": name, "status": "ok", **extra})

    def fail(name: str, detail: str) -> None:
        nonlocal failed
        failed = True
        checks.append({"name": name, "status": "fail", "detail": detail})

    try:
        from urban_platform.specifications.conformance import load_manifest

        m = load_manifest()
        ok("manifest", detail="manifest loaded")
        arts = m.get("artifacts") or {}
        contract_count = len(arts) if isinstance(arts, dict) else 0
        if contract_count > 0:
            ok("contracts", count=contract_count)
        else:
            fail("contracts", "no contracts found in manifest")
    except Exception:
        fail("manifest", "manifest load failed")
        fail("contracts", "contracts unavailable (manifest not loaded)")

    try:
        from urban_platform.sdk.apps import list_app_descriptors

        ok("apps", count=len(list_app_descriptors()))
    except Exception:
        fail("apps", "app descriptors unavailable")

    try:
        from urban_platform.sdk.adapters import list_provider_adapter_descriptors

        ok("adapters", count=len(list_provider_adapter_descriptors()))
    except Exception:
        fail("adapters", "provider adapter descriptors unavailable")

    try:
        from urban_platform.sdk.catalogs import list_reference_catalogs

        ok("catalogs", count=len(list_reference_catalogs()))
    except Exception:
        fail("catalogs", "reference catalogs unavailable")

    try:
        from urban_platform.sdk.deployments import list_deployment_profiles

        ok("deployments", count=len(list_deployment_profiles()))
    except Exception:
        fail("deployments", "deployment profiles unavailable")

    try:
        from urban_platform.deployments.builder_registry import list_builders

        ok("builder_registry", count=len(list_builders()))
    except Exception:
        fail("builder_registry", "builder registry unavailable")

    # Optional store presence check (do not create directories).
    if os.environ.get("AIROS_STORE_DIR", "").strip():
        try:
            from urban_platform.api.settings import api_store_dir

            p = api_store_dir()
            if p.exists() and p.is_dir():
                ok("store", detail="store directory present")
            else:
                warnings.append("AIROS_STORE_DIR is set but store directory is missing/unreadable.")
        except Exception:
            warnings.append("AIROS_STORE_DIR is set but store directory could not be resolved.")

    print("AirOS health (local, read-only)")
    for c in checks:
        if c.get("status") == "ok":
            extra = ""
            if "count" in c:
                extra = f" (count={c.get('count')})"
            elif "detail" in c:
                extra = f" ({c.get('detail')})"
            print(f"- {c.get('name')}: ok{extra}")
        else:
            print(f"- {c.get('name')}: fail ({c.get('detail')})")
    for w in warnings:
        print(f"- warning: {w}")
    print("- note: health checks are read-only; they do not execute apps, adapters, or deployments.")

    return 1 if failed else 0


def _http_get_json(url: str, *, timeout_s: float = 3.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    return obj


def _health_api(repo_root: Path, *, api_base_url: str) -> int:
    base = str(api_base_url or "").strip().rstrip("/")
    if not base:
        print("Missing --api-base-url", file=sys.stderr)
        return 2
    live_url = f"{base}/health/live"
    ready_url = f"{base}/health/ready"

    try:
        live = _http_get_json(live_url, timeout_s=3.0)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach {live_url}: {exc}", file=sys.stderr)
        return 1

    print("AirOS health (Core API, read-only)")
    print(f"- live: {live.get('status')} (service={live.get('service')})")

    try:
        ready = _http_get_json(ready_url, timeout_s=3.0)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read readiness from {ready_url}: {exc}", file=sys.stderr)
        return 1

    status = str(ready.get("status") or "")
    print(f"- ready: {status}")
    checks = ready.get("checks") or []
    if isinstance(checks, list):
        for c in checks[:50]:
            if not isinstance(c, dict):
                continue
            nm = c.get("name")
            st = c.get("status")
            if c.get("count") is not None:
                print(f"  - {nm}: {st} (count={c.get('count')})")
            elif c.get("detail"):
                print(f"  - {nm}: {st} ({c.get('detail')})")
            else:
                print(f"  - {nm}: {st}")
    print("- note: health checks are read-only; they do not execute apps, adapters, or deployments.")

    if str(live.get("status") or "") != "ok":
        return 1
    if status != "ready":
        return 1
    return 0


def _store_backup(repo_root: Path, *, store_dir: str, output_dir: str) -> int:
    sd = Path(store_dir)
    sdir = sd.resolve() if sd.is_absolute() else (repo_root / sd).resolve()
    if not sdir.exists() or not sdir.is_dir():
        print(f"Store directory not found: {sdir}", file=sys.stderr)
        return 2

    od = Path(output_dir)
    odir = od.resolve() if od.is_absolute() else (repo_root / od).resolve()
    odir.mkdir(parents=True, exist_ok=True)

    try:
        outp = air_sdk.backup_file_store(store_dir=sdir, output_dir=odir)
    except Exception as exc:  # noqa: BLE001
        print(f"Store backup failed: {exc}", file=sys.stderr)
        return 1

    included = 0
    missing = 0
    try:
        import zipfile
        import json

        with zipfile.ZipFile(outp, "r") as zz:
            mf = json.loads(zz.read("store_manifest.json").decode("utf-8"))
        if isinstance(mf, dict):
            included = len(mf.get("included_files") or []) if isinstance(mf.get("included_files"), list) else 0
            missing = len(mf.get("missing_expected_files") or []) if isinstance(mf.get("missing_expected_files"), list) else 0
    except Exception:
        pass

    print("AirOS pilot store backup created (read-only)")
    print(f"- backup_zip: {outp}")
    print(f"- included_files: {included}")
    print(f"- missing_expected_files: {missing}")
    print(
        "- note: operational backup only; not restore/import, not approval or certification, not a digital signature, not production-grade backup"
    )
    return 0


def _store_inspect_backup(repo_root: Path, *, backup_zip: str) -> int:
    p = Path(backup_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Backup not found: {bp}", file=sys.stderr)
        return 2

    try:
        rep = air_sdk.inspect_store_backup(backup_path=bp)
    except Exception as exc:  # noqa: BLE001
        print(f"Backup inspection failed: {exc}", file=sys.stderr)
        return 1

    print("AirOS pilot store backup inspection (read-only)")
    print()
    print("Backup")
    print(f"- backup_id: {rep.get('backup_id')}")
    print(f"- created_at: {rep.get('created_at')}")
    print(f"- status: {rep.get('status')}")
    print()
    print("Included files")
    items = rep.get("included_files") or []
    if isinstance(items, list) and items:
        for f in items[:50]:
            if not isinstance(f, dict):
                continue
            print(
                f"- {f.get('path')}  size={f.get('size_bytes')}  lines={f.get('line_count')}  sha256={(f.get('sha256') or 'present')}"
            )
    else:
        print("- (none)")
    print()
    print("Missing expected files")
    miss = rep.get("missing_expected_files") or []
    if isinstance(miss, list) and miss:
        for m in miss[:50]:
            print(f"- {m}")
    else:
        print("- (none)")
    print()
    print("Counts")
    print(f"- file_count: {rep.get('file_count')}")
    print(f"- total_size_bytes: {rep.get('total_size_bytes')}")
    print(f"- total_line_count: {rep.get('total_line_count')}")
    print()
    print("Safety notes")
    print(f"- present: {bool(rep.get('safety_notes_present'))}")
    warns = rep.get("warnings") or []
    if isinstance(warns, list) and warns:
        print()
        print("Warnings")
        for w in warns[:50]:
            print(f"- {w}")
    print()
    print("Result")
    print("Backup inspection is read-only. It does not restore, import, approve, sign, or certify anything.")
    print("Backup inspection is read-only. It does not restore anything.")
    print("Backup inspection is read-only. It does not import anything.")
    print("Backup inspection is read-only. It does not approve anything.")

    if str(rep.get("status") or "") == "invalid":
        return 1
    return 0


def _store_verify_backup(repo_root: Path, *, backup_zip: str) -> int:
    p = Path(backup_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Backup not found: {bp}", file=sys.stderr)
        return 2

    try:
        rep = air_sdk.verify_store_backup(backup_path=bp)
    except Exception as exc:  # noqa: BLE001
        print(f"Backup verification failed: {exc}", file=sys.stderr)
        return 1

    print("AirOS pilot store backup verification (read-only)")
    print()
    b = rep.get("backup") or {}
    print("Backup")
    print(f"- backup_id: {b.get('backup_id')}")
    print(f"- created_at: {b.get('created_at')}")
    print()
    print("Verification status")
    print(f"- status: {rep.get('status')}")
    print(f"- note: {rep.get('note')}")
    print()
    print("Counts")
    print(f"- counts: {rep.get('counts')}")

    warns = rep.get("warnings") or []
    errs = rep.get("errors") or []
    if warns:
        print()
        print("Warnings")
        for w in warns[:50]:
            print(f"- {w}")
    if errs:
        print()
        print("Errors")
        for e in errs[:50]:
            print(f"- {e}")

    print()
    print("Result")
    print(
        "Backup verification checks internal consistency and file hashes only. It does not restore, import, approve, sign, certify, or guarantee production recoverability."
    )
    print("Backup verification is read-only. It does not import anything.")
    print("Backup verification is read-only. It does not approve anything.")

    if str(rep.get("status") or "") == "invalid":
        return 1
    return 0


def _store_restore_dry_run(repo_root: Path, *, backup_zip: str, target_dir: str) -> int:
    p = Path(backup_zip)
    bp = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    if not bp.exists() or not bp.is_file():
        print(f"Backup not found: {bp}", file=sys.stderr)
        return 2

    td = Path(target_dir)
    tdir = td.resolve() if td.is_absolute() else (repo_root / td).resolve()

    try:
        rep = air_sdk.restore_file_store_dry_run(backup_path=bp, target_dir=tdir)
    except Exception as exc:  # noqa: BLE001
        print(f"Restore dry-run failed: {exc}", file=sys.stderr)
        return 1

    print("AirOS pilot store restore dry-run (read-only)")
    print()
    print("Backup verification")
    print(f"- verification_status: {rep.get('verification_status')}")
    print()
    print("Target directory")
    print(f"- target_dir: {tdir}")
    print(f"- target_exists: {rep.get('target_exists')}")
    print(f"- target_has_existing_store_files: {rep.get('target_has_existing_store_files')}")
    esm = rep.get("existing_store_members") or []
    owe = rep.get("paths_that_would_overwrite") or []
    if isinstance(esm, list) and esm:
        print("- existing_store_members:")
        for m in esm:
            print(f"  - {m}")
    else:
        print("- existing_store_members: (none)")
    if isinstance(owe, list) and owe:
        print("- paths_that_would_overwrite (hypothetical):")
        for m in owe:
            print(f"  - {m}")
    else:
        print("- paths_that_would_overwrite (hypothetical): (none)")
    print(f"- would_overwrite: {rep.get('would_overwrite')}")
    print()
    print("Files that would be restored")
    ftr = rep.get("files_to_restore") or []
    if isinstance(ftr, list) and ftr:
        for f in ftr:
            print(f"- {f}")
    else:
        print("- (none)")
    print()
    print("Counts")
    print(f"- total_size_bytes: {rep.get('total_size_bytes')}")
    print(f"- total_line_count: {rep.get('total_line_count')}")
    print()
    miss = rep.get("missing_expected_files") or []
    if isinstance(miss, list) and miss:
        print("Missing expected files")
        for m in miss[:50]:
            print(f"- {m}")

    warns = rep.get("warnings") or []
    errs = rep.get("errors") or []
    if warns:
        print()
        print("Warnings")
        for w in warns[:50]:
            print(f"- {w}")
    if errs:
        print()
        print("Errors")
        for e in errs[:50]:
            print(f"- {e}")

    print()
    print("Result")
    print(
        "Dry-run only. It does not write files; target_dir was not created or modified by this command."
    )
    print(
        "Dry-run does not overwrite, mutate, merge, restore, import, approve, sign, or certify anything."
    )
    print("Restore dry-run is read-only. It does not import anything.")

    if str(rep.get("status") or "") == "invalid":
        return 1
    return 0


def _contracts_list() -> int:
    keys = air_sdk.list_contract_keys()
    if not keys:
        print("No contracts found in specifications/manifest.json")
        return 0
    for k in keys:
        print(k)
    return 0


def _contracts_show(contract_key: str) -> int:
    ck = str(contract_key or "").strip()
    if not ck:
        print("contract_key is required", file=sys.stderr)
        return 2
    try:
        schema = air_sdk.get_contract_schema(ck)
    except Exception as exc:  # noqa: BLE001
        print(f"Unknown contract_key or schema not available: {ck!r}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _fixtures_validate(contract_key: str, path: str) -> int:
    ck = str(contract_key or "").strip()
    if not ck:
        print("contract_key is required", file=sys.stderr)
        return 2
    if not path:
        print("path is required", file=sys.stderr)
        return 2

    p = Path(path)
    if not p.exists():
        print(f"fixture file not found: {path}", file=sys.stderr)
        return 1
    if not p.is_file():
        print(f"fixture path is not a file: {path}", file=sys.stderr)
        return 1

    try:
        payload = air_sdk.load_json_fixture(p)
    except Exception as exc:  # noqa: BLE001
        print(f"failed to load fixture: {path}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    errs = air_sdk.validate_payload(ck, payload)
    if errs:
        print(f"invalid: {path} does not conform to {ck}", file=sys.stderr)
        for e in errs:
            pth = e.get("path") or "$"
            msg = e.get("message") or ""
            print(f"- {pth}: {msg}", file=sys.stderr)
        return 1

    print(f"valid: {path} conforms to {ck}")
    return 0


def _apps_list() -> int:
    desc = air_sdk.list_app_descriptors()
    if not desc:
        print("No app descriptors found under specifications/app_descriptors/")
        return 0
    for d in desc:
        aid = str(d.get("app_id") or "").strip()
        name = str(d.get("name") or "").strip()
        domain = str(d.get("domain_id") or "").strip()
        status = str(d.get("status") or "").strip()
        if not aid:
            continue
        print(f"{aid}\t{name}\t{domain}\t{status}")
    return 0


def _apps_show(app_id: str) -> int:
    aid = str(app_id or "").strip()
    if not aid:
        print("app_id is required", file=sys.stderr)
        return 2
    d = air_sdk.get_app_descriptor(aid)
    if not d:
        print(f"Unknown app_id: {aid}", file=sys.stderr)
        return 1
    print(yaml.safe_dump(d, sort_keys=False))
    return 0


def _apps_explain(repo_root: Path, app_id: str) -> int:
    aid = str(app_id or "").strip()
    if not aid:
        print("app_id is required", file=sys.stderr)
        return 2

    d = air_sdk.get_app_descriptor(aid)
    if not d:
        print(f"Unknown app_id: {aid}", file=sys.stderr)
        return 1

    def _schema_title(contract_key: str) -> str | None:
        try:
            s = air_sdk.get_contract_schema(contract_key)
        except Exception:
            return None
        if isinstance(s, dict):
            t = s.get("title")
            return str(t) if isinstance(t, str) and t.strip() else None
        return None

    # Header
    print("AirOS App Descriptor — explained")
    print(f"- name: {d.get('name')}")
    print(f"- app_id: {d.get('app_id')}")
    print(f"- domain_id: {d.get('domain_id')}")
    print(f"- version: {d.get('version')}")
    print(f"- status: {d.get('status')}")
    print(f"- app_type: {d.get('app_type')}")

    # What it does
    print("")
    print("## What it does")
    desc = d.get("description") or ""
    print(str(desc).strip() if isinstance(desc, str) else "")
    print(
        "This app produces review outputs and proposed actions for human review. "
        "It does not authorize outcomes or automate government action."
    )

    # Input contracts
    print("")
    print("## Input contracts")
    inputs = d.get("input_contracts") or []
    if not isinstance(inputs, list):
        inputs = []
    if not inputs:
        print("- (none)")
    for ck in inputs:
        if not isinstance(ck, str) or not ck.strip():
            continue
        exists = air_sdk.contract_exists(ck)
        title = _schema_title(ck) if exists else None
        extra = f" — {title}" if title else ""
        print(f"- {ck}  (manifest={'yes' if exists else 'no'}){extra}")

    # Output contracts
    print("")
    print("## Output contracts")
    outputs = d.get("output_contracts") or []
    if not isinstance(outputs, list):
        outputs = []
    if not outputs:
        print("- (none)")
    for ck in outputs:
        if not isinstance(ck, str) or not ck.strip():
            continue
        exists = air_sdk.contract_exists(ck)
        title = _schema_title(ck) if exists else None
        extra = f" — {title}" if title else ""
        print(f"- {ck}  (manifest={'yes' if exists else 'no'}){extra}")

    # Decision logic
    print("")
    print("## Decision logic")
    dl = d.get("decision_logic") if isinstance(d.get("decision_logic"), dict) else {}
    builder_ids = []
    if isinstance(dl, dict):
        builder_ids = dl.get("builder_ids") or []
    if not isinstance(builder_ids, list):
        builder_ids = []

    from urban_platform.deployments.builder_registry import has_builder  # noqa: WPS433

    if not builder_ids:
        print("- builder_ids: (none)")
    else:
        print("- builder_ids:")
        for bid in builder_ids:
            if not isinstance(bid, str) or not bid.strip():
                continue
            ok = has_builder(bid)
            print(f"  - {bid}  (safe_builder_registry={'yes' if ok else 'no'})")
    print("Builder IDs are resolved only through the safe builder registry. App descriptors do not dynamically load code.")

    # Deployment examples
    print("")
    print("## Deployment examples")
    ex = d.get("deployment_examples") or []
    if not isinstance(ex, list):
        ex = []
    if not ex:
        print("- (none)")
    for it in ex:
        if not isinstance(it, dict):
            continue
        dep_id = str(it.get("deployment_id") or "").strip()
        path = str(it.get("path") or "").strip()
        path_exists = False
        if path:
            p = Path(path)
            p2 = p if p.is_absolute() else (repo_root / p).resolve()
            path_exists = p2.exists()
        print(f"- deployment_id: {dep_id or '—'}")
        print(f"  path: {path or '—'}  (exists={'yes' if path_exists else 'no'})")
        if path:
            print(f"  validate: python tools/airos_cli.py deployment validate {path}")
            print(f"  run:      python tools/airos_cli.py deployment run {path}")

    # Dashboard
    print("")
    print("## Dashboard")
    dash = d.get("dashboard") if isinstance(d.get("dashboard"), dict) else {}
    panels = dash.get("panels") if isinstance(dash, dict) else None
    supports_file = dash.get("supports_file_mode") if isinstance(dash, dict) else None
    supports_api = dash.get("supports_api_mode") if isinstance(dash, dict) else None
    print(f"- panels: {panels if isinstance(panels, list) else (panels or '—')}")
    print(f"- supports_file_mode: {supports_file}")
    print(f"- supports_api_mode: {supports_api}")

    # Safety
    print("")
    print("## Safety")
    safety = d.get("safety") if isinstance(d.get("safety"), dict) else {}
    if not isinstance(safety, dict):
        safety = {}
    print(f"- review_support_only: {safety.get('review_support_only')}")
    print(f"- human_review_required: {safety.get('human_review_required')}")
    blocked = safety.get("blocked_uses") or []
    if not isinstance(blocked, list):
        blocked = []
    if blocked:
        print("- blocked_uses:")
        for b in blocked:
            if isinstance(b, str) and b.strip():
                print(f"  - {b}")
    else:
        print("- blocked_uses: (none)")
    notes = safety.get("notes")
    if isinstance(notes, str) and notes.strip():
        print(f"- notes: {notes.strip()}")

    # Suggested next steps
    print("")
    print("## Suggested next steps")
    print(f"- Inspect the app descriptor: python tools/airos_cli.py apps show {aid}")
    for ck in inputs[:2] if isinstance(inputs, list) else []:
        if isinstance(ck, str) and ck.strip():
            print(f"- Inspect input contract schema: python tools/airos_cli.py contracts show {ck}")
            break
    if aid == "program_reporting_review":
        print("- Validate a known fixture:")
        print(
            "  python tools/airos_cli.py fixtures validate consumer_city_program_submission "
            "specifications/examples/program_reporting/city_program_submission.sample.json"
        )
        print("- Run the program reporting example:")
        print("  python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo")
    if aid == "flood_risk_review":
        print("- Run the flood example:")
        print("  python tools/airos_cli.py deployment run deployments/examples/flood_local_demo")
    print("- Inspect outputs under data/outputs/deployments/<deployment_id>/ after a successful run.")
    print("- Open the review dashboard (presentation only) to inspect outputs.")

    return 0


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
    from_example: str | None,
    deployment_id: str,
    deployment_name: str,
    deployment_type: str | None,
    owner_organization: str | None,
    environment: str | None,
    domains_csv: str | None,
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
    domains = _parse_csv(domains_csv) if domains_csv is not None else []
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

    # ---------------------------------------------------------------------
    # Mode 1: Initialize from an existing runnable example (copy + override)
    # ---------------------------------------------------------------------
    if from_example:
        example_dir = (repo_root / "deployments" / "examples" / from_example).resolve()
        if not example_dir.is_dir():
            print(f"Example deployment not found: deployments/examples/{from_example}", file=sys.stderr)
            return 1

        if out_path.exists() and force:
            shutil.rmtree(out_path)

        # Copy example directory as-is to preserve runnable registries + fixtures.
        shutil.copytree(example_dir, out_path)

        # Update deployment_profile.yaml with safe identity overrides and local registry paths.
        prof_path = out_path / "deployment_profile.yaml"
        if not prof_path.is_file():
            print(f"Copied example is missing deployment_profile.yaml: {example_dir}", file=sys.stderr)
            return 1
        prof = _read_yaml_template(prof_path)
        prof["deployment_id"] = deployment_id
        prof["deployment_name"] = deployment_name
        if deployment_type:
            prof["deployment_type"] = deployment_type
        if owner_organization:
            prof["owner_organization"] = owner_organization
        if environment:
            prof["environment"] = environment
        if domains:
            prof["enabled_domains"] = domains

        # Ensure the copied workspace is self-contained (avoid hard-coded example paths).
        prof["enabled_provider_registries"] = ["provider_registry.yaml"]
        prof["enabled_application_registries"] = ["application_registry.yaml"]
        _write_yaml(prof_path, prof)

        # Keep registries valid; only override providers/applications if explicitly requested.
        prov_path = out_path / "provider_registry.yaml"
        if prov_path.is_file():
            prov_doc = _read_yaml_template(prov_path)
            prov_doc["deployment_id"] = deployment_id
            if provider_ids:
                prov_doc = _scaffold_provider_registry(
                    prov_doc, deployment_id=deployment_id, domains=(domains or list(prof.get("enabled_domains") or [])), provider_ids=provider_ids
                )
                prov_doc["deployment_id"] = deployment_id
            _write_yaml(prov_path, prov_doc)

        app_path = out_path / "application_registry.yaml"
        if app_path.is_file():
            app_doc = _read_yaml_template(app_path)
            app_doc["deployment_id"] = deployment_id
            if application_ids:
                app_doc = _scaffold_application_registry(app_doc, deployment_id=deployment_id, application_ids=application_ids)
                app_doc["deployment_id"] = deployment_id
            _write_yaml(app_path, app_doc)

        print(f"Initialized runnable deployment from example '{from_example}' at: {out_path}")
        rel = out_path
        try:
            rel = out_path.relative_to(repo_root)
        except ValueError:
            pass
        print("Next steps:")
        print(f"1) Validate config: {sys.executable} tools/airos_cli.py deployment validate {rel}")
        print(f"2) Run deployment: {sys.executable} tools/airos_cli.py deployment run {rel}")
        print(f"3) Inspect outputs under data/outputs/deployments/{deployment_id}/ after a successful run.")
        print(f"4) Run governance checks: {sys.executable} tools/airos_cli.py review --run-conformance")
        print("- Do not commit secrets, credentials, API keys, restricted datasets, or sensitive operational data.")
        return 0

    # ---------------------------------------------------------------------
    # Mode 2: Scaffold from templates (existing behavior)
    # ---------------------------------------------------------------------
    missing: list[str] = []
    if not deployment_type:
        missing.append("--deployment-type")
    if not owner_organization:
        missing.append("--owner-organization")
    if not environment:
        missing.append("--environment")
    if not domains_csv:
        missing.append("--domains")
    if missing:
        print("Missing required arguments for scaffold mode: " + ", ".join(missing), file=sys.stderr)
        print("Hint: use --from-example flood_local_demo to create a runnable workspace.", file=sys.stderr)
        return 2

    out_path.mkdir(parents=True, exist_ok=True)

    # deployment_profile.yaml
    dep_template = _read_yaml_template(templates_dir / "deployment_profile.yaml") if templates_dir.exists() else {}
    dep_prof = dict(dep_template)
    dep_prof["deployment_id"] = deployment_id
    dep_prof["deployment_name"] = deployment_name
    dep_prof["deployment_type"] = str(deployment_type)
    dep_prof["owner_organization"] = str(owner_organization)
    dep_prof["environment"] = str(environment)
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


_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_snake_case_id(s: str) -> bool:
    v = str(s or "").strip()
    return bool(v) and _SNAKE_CASE_RE.match(v) is not None and "__" not in v and not v.endswith("_")


def _apps_scaffold(
    repo_root: Path,
    *,
    app_id: str,
    domain_id: str,
    output_dir: str | None,
    force: bool,
) -> int:
    aid = str(app_id or "").strip()
    did = str(domain_id or "").strip()
    if not _is_snake_case_id(aid):
        print(f"Invalid app_id (expected lowercase snake_case): {aid!r}", file=sys.stderr)
        return 2
    if not _is_snake_case_id(did):
        print(f"Invalid domain_id (expected lowercase snake_case): {did!r}", file=sys.stderr)
        return 2

    out = Path(output_dir) if output_dir else Path("apps") / aid
    out_path = out if out.is_absolute() else (repo_root / out).resolve()

    if out_path.exists():
        if not force:
            print(f"Output directory already exists: {out_path}", file=sys.stderr)
            print("Re-run with --force to overwrite.", file=sys.stderr)
            return 1
        if not out_path.is_dir():
            print(f"Output path exists and is not a directory: {out_path}", file=sys.stderr)
            return 1
        shutil.rmtree(out_path)

    # Create directory structure
    (out_path / "contracts").mkdir(parents=True, exist_ok=True)
    (out_path / "examples").mkdir(parents=True, exist_ok=True)
    (out_path / "builders").mkdir(parents=True, exist_ok=True)
    (out_path / "dashboard").mkdir(parents=True, exist_ok=True)
    (out_path / "deployments").mkdir(parents=True, exist_ok=True)
    (out_path / "tests").mkdir(parents=True, exist_ok=True)

    # README.md
    (out_path / "README.md").write_text(
        "\n".join(
            [
                f"# AirOS App scaffold: {aid}",
                "",
                "This folder was generated by `python tools/airos_cli.py apps scaffold ...`.",
                "",
                "## Important",
                "",
                "- This is **scaffolding only**.",
                "- It is **not registered** in `specifications/manifest.json`.",
                "- It is **not executable** and is **not allowlisted** in the safe builder registry.",
                "- App descriptors are **metadata only**; they do not dynamically load code.",
                "",
                "## Next steps (safe sequence)",
                "",
                "1. Define an input contract schema under `contracts/` (or reuse an existing one).",
                "2. Define an output contract schema under `contracts/`.",
                "3. Add examples under `examples/` that conform to the schemas.",
                "4. Write decision logic in `builders/builder.py` (still not executable until allowlisted).",
                "5. Add tests under `tests/`.",
                "6. Register schemas/examples/descriptor in `specifications/manifest.json` (manual step).",
                "7. Request builder allowlisting in `urban_platform/deployments/builder_registry.py` only after review.",
                "8. Run: `python -m pytest -q` and `python main.py --step conformance`.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # app_descriptor.yaml (template)
    descriptor = {
        "app_id": aid,
        "name": f"{aid.replace('_', ' ').title()} (Scaffold)",
        "version": "v1",
        "status": "draft_demo",
        "domain_id": did,
        "description": "PLACEHOLDER: describe what this app reviews and what outputs it produces (review support only).",
        "app_type": "review_support",
        "input_contracts": [],
        "output_contracts": [],
        "decision_logic": {
            "builder_ids": [],
            "description": "PLACEHOLDER: describe decision logic at a high level (rules/models/workflow checks).",
            "execution_model": "allowlisted_python_builder",
        },
        "deployment_examples": [],
        "dashboard": {
            "panels": [],
            "supports_file_mode": False,
            "supports_api_mode": False,
        },
        "safety": {
            "review_support_only": True,
            "human_review_required": True,
            "blocked_uses": ["final_government_decision_without_authorized_review"],
            "notes": ["Placeholder app. Not registered or executable until reviewed."],
        },
        "provenance": {
            "publisher": "local_developer",
            "source": "airos_cli_scaffold",
        },
    }
    (out_path / "app_descriptor.yaml").write_text(
        yaml.safe_dump(descriptor, sort_keys=False),
        encoding="utf-8",
    )

    # Contract templates
    in_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "INPUT_CONTRACT_TITLE_PLACEHOLDER",
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": True,
    }
    out_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "OUTPUT_CONTRACT_TITLE_PLACEHOLDER",
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": True,
    }
    (out_path / "contracts" / "input_contract.template.schema.json").write_text(
        json.dumps(in_schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_path / "contracts" / "output_contract.template.schema.json").write_text(
        json.dumps(out_schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Example placeholders
    (out_path / "examples" / "input.sample.json").write_text(
        json.dumps({"PLACEHOLDER": "input sample"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_path / "examples" / "output.sample.json").write_text(
        json.dumps({"PLACEHOLDER": "output sample"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Builder stub (safe)
    (out_path / "builders" / "builder.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from typing import Any",
                "",
                "",
                "def build(*, inputs: dict[str, Any]) -> dict[str, Any]:",
                '    """',
                "    Scaffold-only decision logic stub.",
                "",
                "    - This module is NOT allowlisted or executed by AirOS automatically.",
                "    - Do not add dynamic imports or side effects here.",
                '    """',
                "    raise NotImplementedError('Scaffold-only stub. Implement after defining contracts and tests.')",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Dashboard panel stub (safe; no domain logic)
    (out_path / "dashboard" / "panel.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from typing import Any",
                "",
                "",
                "def render_panel(*, payload: dict[str, Any]) -> None:",
                '    """Scaffold-only panel stub (presentation only)."""',
                "    raise NotImplementedError('Scaffold-only stub. Do not encode domain logic in the dashboard.')",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Deployment YAML placeholders (not runnable; no secrets)
    (out_path / "deployments" / "deployment_profile.yaml").write_text(
        yaml.safe_dump(
            {
                "deployment_id": f"{aid}_local_scaffold",
                "deployment_name": f"{aid} local scaffold (not runnable)",
                "deployment_type": "single_agency",
                "owner_organization": "PLACEHOLDER",
                "environment": "local",
                "enabled_domains": [did],
                "enabled_provider_registries": ["provider_registry.yaml"],
                "enabled_application_registries": ["application_registry.yaml"],
                "notes": [
                    "Scaffold only. Not runnable until contracts, registries, and builders are reviewed and allowlisted.",
                    "Do not put secrets in this repo; use deployment-local secret stores in real deployments.",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_path / "deployments" / "application_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "deployment_id": f"{aid}_local_scaffold",
                "applications": [
                    {
                        "application_id": "APP_ID_PLACEHOLDER",
                        "label": "PLACEHOLDER",
                        "domain_id": did,
                        "consumer_contracts": [],
                        "payload_builders": [],
                        "examples": [],
                        "enabled_by_default": False,
                        "status": "placeholder",
                        "notes": "Scaffold only; does not register or execute builders.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_path / "deployments" / "provider_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "deployment_id": f"{aid}_local_scaffold",
                "providers": [
                    {
                        "provider_id": "PROVIDER_ID_PLACEHOLDER",
                        "label": "PLACEHOLDER",
                        "domain_ids": [did],
                        "provider_contract": "PROVIDER_CONTRACT_PLACEHOLDER",
                        "connector_module": "CONNECTOR_MODULE_PLACEHOLDER",
                        "input_method": "api",
                        "examples": [],
                        "enabled_by_default": False,
                        "status": "placeholder",
                        "notes": "Scaffold only; do not add credentials or secrets here.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # Test placeholder
    (out_path / "tests" / f"test_{aid}.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "",
                "def test_scaffold_placeholder() -> None:",
                f"    assert {aid!r}",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Scaffolded app at: {out_path}")
    return 0


def _apps_validate(repo_root: Path, app_path: str) -> int:
    p = Path(app_path)
    app_dir = p if p.is_absolute() else (repo_root / p).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    print("AirOS app validation (local)")
    print(f"- path: {app_dir}")

    if not app_dir.exists():
        print("Result: invalid", file=sys.stderr)
        print(f"- error: path not found: {app_dir}", file=sys.stderr)
        return 1
    if not app_dir.is_dir():
        print("Result: invalid", file=sys.stderr)
        print(f"- error: path is not a directory: {app_dir}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Structure
    # ------------------------------------------------------------------
    required = [
        ("README.md", "file"),
        ("app_descriptor.yaml", "file"),
        ("contracts", "dir"),
        ("examples", "dir"),
        ("builders", "dir"),
        ("dashboard", "dir"),
        ("deployments", "dir"),
        ("tests", "dir"),
    ]
    print("")
    print("## Structure")
    for rel, kind in required:
        rp = app_dir / rel
        ok = rp.is_file() if kind == "file" else rp.is_dir()
        print(f"- {rel}: {'ok' if ok else 'missing'}")
        if not ok:
            errors.append(f"missing required {kind}: {rel}")

    # ------------------------------------------------------------------
    # Descriptor
    # ------------------------------------------------------------------
    desc_path = app_dir / "app_descriptor.yaml"
    descriptor: dict | None = None
    print("")
    print("## App descriptor")
    if desc_path.is_file():
        try:
            obj = yaml.safe_load(desc_path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("descriptor YAML root must be an object/dict")
            descriptor = obj
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid app_descriptor.yaml: {exc}")
    else:
        descriptor = None

    if descriptor is not None:
        is_scaffold = False
        prov = descriptor.get("provenance") if isinstance(descriptor.get("provenance"), dict) else {}
        if isinstance(prov, dict) and str(prov.get("source") or "").strip() == "airos_cli_scaffold":
            is_scaffold = True
        # Validate against schema (shape only).
        try:
            from urban_platform.api.app_descriptors import _load_descriptor_schema_validator  # noqa: WPS433

            v = _load_descriptor_schema_validator()
            if v is None:
                warnings.append("descriptor schema validator not available (manifest missing platform_air_os_app_descriptor)")
            else:
                v.validate(descriptor)
                print("- schema: ok (air_os_app_descriptor.v1)")
        except Exception as exc:  # noqa: BLE001
            msg = f"descriptor schema validation failed: {exc}"
            if is_scaffold:
                warnings.append(msg)
                print("- schema: not yet conformant (scaffold; warning)")
            else:
                errors.append(msg)

        app_id = str(descriptor.get("app_id") or "").strip()
        domain_id = str(descriptor.get("domain_id") or "").strip()
        status = str(descriptor.get("status") or "").strip()
        folder_name = app_dir.name

        if not _is_snake_case_id(app_id):
            errors.append(f"descriptor app_id is invalid (lowercase snake_case required): {app_id!r}")
        if not _is_snake_case_id(domain_id):
            errors.append(f"descriptor domain_id is invalid (lowercase snake_case required): {domain_id!r}")
        if app_id and folder_name and app_id != folder_name:
            warnings.append(f"descriptor app_id {app_id!r} does not match folder name {folder_name!r}")

        safety = descriptor.get("safety") if isinstance(descriptor.get("safety"), dict) else {}
        if not isinstance(safety, dict):
            safety = {}
        if safety.get("review_support_only") is not True:
            errors.append("safety.review_support_only must be true")
        if safety.get("human_review_required") is not True:
            errors.append("safety.human_review_required must be true")
        blocked = safety.get("blocked_uses") or []
        if not isinstance(blocked, list) or not [b for b in blocked if isinstance(b, str) and b.strip()]:
            errors.append("safety.blocked_uses must be a non-empty list")
        print(f"- app_id: {app_id or '—'}")
        print(f"- domain_id: {domain_id or '—'}")
        print(f"- status: {status or '—'}")

        # ------------------------------------------------------------------
        # Contracts
        # ------------------------------------------------------------------
        print("")
        print("## Contracts")
        contracts_dir = app_dir / "contracts"
        local_schema_files = []
        if contracts_dir.is_dir():
            local_schema_files = sorted(list(contracts_dir.glob("*.schema.json")))

        def _check_contract_ref(ck: str) -> None:
            c = str(ck or "").strip()
            if not c:
                return
            if air_sdk.contract_exists(c):
                print(f"- {c}: ok (manifest)")
                return
            # Allow local schema references during scaffolding.
            cand = contracts_dir / f"{c}.schema.json"
            cand2 = contracts_dir / f"{c}.template.schema.json"
            if cand.is_file() or cand2.is_file():
                print(f"- {c}: local (unregistered)")
                warnings.append(f"contract {c!r} is local/unregistered (not in manifest)")
                return
            # If there are schema files but none match the key, treat as local/unregistered.
            if local_schema_files:
                print(f"- {c}: local (unregistered, no matching filename)")
                warnings.append(f"contract {c!r} not in manifest; local contracts/ exists (scaffold phase)")
                return
            errors.append(f"contract reference missing: {c!r} (not in manifest and no local schema found)")

        in_contracts = descriptor.get("input_contracts") or []
        out_contracts = descriptor.get("output_contracts") or []
        if not isinstance(in_contracts, list):
            in_contracts = []
        if not isinstance(out_contracts, list):
            out_contracts = []
        if not in_contracts and not out_contracts:
            warnings.append("descriptor has empty input_contracts/output_contracts (scaffold phase)")
        for ck in in_contracts:
            if isinstance(ck, str):
                _check_contract_ref(ck)
        for ck in out_contracts:
            if isinstance(ck, str):
                _check_contract_ref(ck)

        # ------------------------------------------------------------------
        # Examples
        # ------------------------------------------------------------------
        print("")
        print("## Examples")
        examples_dir = app_dir / "examples"
        json_files = sorted(list(examples_dir.glob("*.json"))) if examples_dir.is_dir() else []
        if not json_files:
            warnings.append("no example JSON files found under examples/")
            print("- (none)")
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"invalid JSON example: {jf.name}: {exc}")
                continue
            # Placeholder detection
            if isinstance(data, dict) and ("PLACEHOLDER" in data or any("PLACEHOLDER" in str(k) for k in data.keys())):
                warnings.append(f"placeholder example detected: {jf.name}")
                print(f"- {jf.name}: placeholder (warning)")
                continue

            # Optional contract validation for simple conventions.
            validated = False
            if jf.name.startswith("input") and in_contracts:
                ck = str(in_contracts[0])
                errs = air_sdk.validate_payload(ck, data if isinstance(data, dict) else {})
                if errs:
                    errors.append(f"{jf.name}: does not conform to {ck}")
                else:
                    print(f"- {jf.name}: ok (conforms to {ck})")
                validated = True
            if jf.name.startswith("output") and out_contracts:
                ck = str(out_contracts[0])
                errs = air_sdk.validate_payload(ck, data if isinstance(data, dict) else {})
                if errs:
                    errors.append(f"{jf.name}: does not conform to {ck}")
                else:
                    print(f"- {jf.name}: ok (conforms to {ck})")
                validated = True
            if not validated:
                print(f"- {jf.name}: ok (json)")

        # ------------------------------------------------------------------
        # Decision logic metadata
        # ------------------------------------------------------------------
        print("")
        print("## Decision logic")
        dl = descriptor.get("decision_logic") if isinstance(descriptor.get("decision_logic"), dict) else {}
        bids = dl.get("builder_ids") if isinstance(dl, dict) else []
        if not isinstance(bids, list):
            bids = []
        from urban_platform.deployments.builder_registry import has_builder  # noqa: WPS433

        if not bids:
            warnings.append("no decision_logic.builder_ids set (scaffold phase)")
            print("- builder_ids: (none)")
        for bid in bids:
            if not isinstance(bid, str) or not bid.strip():
                continue
            allow = has_builder(bid)
            if allow:
                print(f"- {bid}: allowlisted (safe builder registry)")
            else:
                msg = f"- {bid}: not allowlisted (safe builder registry)"
                print(msg)
                if status == "draft_demo":
                    warnings.append(f"builder_id not allowlisted yet (draft): {bid}")
                else:
                    warnings.append(f"builder_id not allowlisted: {bid}")
        print("Note: builders are not imported or executed by this command.")

        # ------------------------------------------------------------------
        # Deployment files
        # ------------------------------------------------------------------
        print("")
        print("## Deployment files")
        dep_dir = app_dir / "deployments"
        ymls = sorted(list(dep_dir.glob("*.yaml")) + list(dep_dir.glob("*.yml"))) if dep_dir.is_dir() else []
        if not ymls:
            warnings.append("no deployment YAML files found under deployments/")
            print("- (none)")
        try:
            from tools.deployment_runner.validate_deployment import _check_no_secrets  # noqa: WPS433
        except Exception:
            _check_no_secrets = None  # type: ignore[assignment]
        for yp in ymls:
            try:
                doc = yaml.safe_load(yp.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"invalid YAML: {yp.name}: {exc}")
                continue
            print(f"- {yp.name}: ok (yaml)")
            text = yp.read_text(encoding="utf-8")
            if "PLACEHOLDER" in text:
                warnings.append(f"placeholder values detected in {yp.name}")
            if _check_no_secrets is not None:
                _check_no_secrets(doc, context=f"app_deployments/{yp.name}", warnings=warnings, errors=errors)

        # ------------------------------------------------------------------
        # Safety summary
        # ------------------------------------------------------------------
        print("")
        print("## Safety")
        print(f"- review_support_only: {safety.get('review_support_only')}")
        print(f"- human_review_required: {safety.get('human_review_required')}")
        print(f"- blocked_uses_count: {len([b for b in blocked if isinstance(b, str) and b.strip()])}")

    # Final result
    print("")
    print("## Result")
    if errors:
        print("status: invalid")
        print("errors:")
        for e in errors:
            print(f"- {e}")
        if warnings:
            print("warnings:")
            for w in warnings:
                print(f"- {w}")
        return 1
    if warnings:
        print("status: valid_with_warnings")
        print("warnings:")
        for w in warnings:
            print(f"- {w}")
        return 0
    print("status: valid")
    return 0


def _is_secret_like_filename(name: str) -> bool:
    n = str(name or "").lower()
    if not n:
        return False
    if n.endswith(".env") or "/.env" in n:
        return True
    if n.endswith(".pem") or n.endswith(".key"):
        return True
    if "secret" in n or "credential" in n:
        return True
    return False


def _iter_package_files(app_dir: Path) -> tuple[list[Path], list[str]]:
    """
    Return (files, errors). Does not follow symlinks outside app_dir.
    """
    errors: list[str] = []
    files: list[Path] = []
    exclude_dirnames = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    exclude_filenames = {".DS_Store"}
    for p in app_dir.rglob("*"):
        try:
            rel = p.relative_to(app_dir)
        except Exception:
            continue
        rel_str = str(rel).replace("\\", "/")
        if not rel_str or rel_str == ".":
            continue
        if any(part in exclude_dirnames for part in rel.parts):
            continue
        if p.name in exclude_filenames:
            continue
        if p.is_symlink():
            errors.append(f"symlink not allowed in app package: {rel_str}")
            continue
        if p.is_dir():
            continue
        if _is_secret_like_filename(rel_str):
            errors.append(f"secret-like file is not allowed in app package: {rel_str}")
            continue
        files.append(p)
    return files, errors


def _apps_package(repo_root: Path, app_path: str, *, output_dir: str | None, force: bool) -> int:
    """
    Package a local app folder into a zip review artifact.

    Packaging does not install/register/allowlist/execute the app.
    """
    p = Path(app_path)
    app_dir = p if p.is_absolute() else (repo_root / p).resolve()
    if not app_dir.exists() or not app_dir.is_dir():
        print(f"app_path not found or not a directory: {app_dir}", file=sys.stderr)
        return 1

    # Run validation (capture output).
    import io  # noqa: WPS433
    from contextlib import redirect_stdout  # noqa: WPS433

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _apps_validate(repo_root, str(app_dir))
    report = buf.getvalue()
    print(report.rstrip())
    if rc != 0:
        print("Packaging aborted: app validation status is invalid.", file=sys.stderr)
        return 1

    validation_status = "valid"
    validation_warnings: list[str] = []
    in_warnings = False
    for line in report.splitlines():
        s = line.strip()
        if s.startswith("status:"):
            validation_status = s.split(":", 1)[1].strip()
        if s == "warnings:":
            in_warnings = True
            continue
        if in_warnings and line.startswith("- "):
            validation_warnings.append(line[2:].strip())

    # Load descriptor for app_id/version/safety_summary
    desc_path = app_dir / "app_descriptor.yaml"
    if not desc_path.is_file():
        print("Packaging aborted: missing app_descriptor.yaml", file=sys.stderr)
        return 1
    try:
        descriptor = yaml.safe_load(desc_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Packaging aborted: invalid app_descriptor.yaml: {exc}", file=sys.stderr)
        return 1
    if not isinstance(descriptor, dict):
        print("Packaging aborted: app_descriptor.yaml must be a YAML object", file=sys.stderr)
        return 1
    app_id = str(descriptor.get("app_id") or app_dir.name).strip() or app_dir.name
    version = str(descriptor.get("version") or "v1").strip() or "v1"

    # Output path
    out_root = Path(output_dir) if output_dir else Path("dist") / "apps"
    out_dir_path = out_root if out_root.is_absolute() else (repo_root / out_root).resolve()
    out_dir_path.mkdir(parents=True, exist_ok=True)
    zip_path = (out_dir_path / f"{app_id}-{version}.zip").resolve()
    if zip_path.exists() and not force:
        print(f"package already exists: {zip_path}", file=sys.stderr)
        print("Re-run with --force to overwrite.", file=sys.stderr)
        return 1
    if zip_path.exists() and force:
        zip_path.unlink()

    files, file_errors = _iter_package_files(app_dir)
    if file_errors:
        for e in file_errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    packaged_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    package_id = f"{app_id}:{version}"
    safety = descriptor.get("safety") if isinstance(descriptor.get("safety"), dict) else {}
    safety_summary = {
        "review_support_only": (safety.get("review_support_only") if isinstance(safety, dict) else None),
        "human_review_required": (safety.get("human_review_required") if isinstance(safety, dict) else None),
        "blocked_uses": (safety.get("blocked_uses") if isinstance(safety, dict) else []),
    }
    included_files = sorted({str(f.relative_to(app_dir)).replace("\\", "/") for f in files})

    pkg_manifest = {
        "package_id": package_id,
        "app_id": app_id,
        "version": version,
        "packaged_at": packaged_at,
        "source_app_path": str(app_dir),
        "validation_status": validation_status,
        "validation_warnings": validation_warnings,
        "included_files": included_files,
        "safety_summary": safety_summary,
        "note": "This package is not installed, registered, allowlisted, or executable by packaging alone.",
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            rel = str(f.relative_to(app_dir)).replace("\\", "/")
            zf.write(str(f), arcname=f"app/{rel}")
        zf.writestr("airos_package_manifest.json", json.dumps(pkg_manifest, indent=2, sort_keys=True) + "\n")

    print("")
    print("AirOS app packaged")
    print(f"- package_path: {zip_path}")
    print(f"- app_id: {app_id}")
    print(f"- version: {version}")
    print(f"- validation_status: {validation_status}")
    print(f"- warnings_count: {len(validation_warnings)}")
    print("- note: packaging does not install/register/allowlist/execute the app")
    return 0


def _zip_is_safe_member_name(name: str) -> bool:
    n = str(name or "")
    if not n or n.startswith("/") or n.startswith("\\"):
        return False
    if ".." in n.replace("\\", "/").split("/"):
        return False
    if ":" in n[:3]:
        return False
    if "\\" in n:
        return False
    return True


def _inspect_package_metadata(repo_root: Path, zpath: Path) -> tuple[str, list[str], dict[str, Any] | None, list[str]]:
    """
    Return (status, warnings, metadata, errors).

    status in {"inspectable","inspectable_with_warnings","invalid"}.
    """
    warnings: list[str] = []
    errors: list[str] = []

    if not zpath.exists():
        return "invalid", [], None, [f"package not found: {zpath}"]
    if zpath.suffix.lower() != ".zip":
        return "invalid", [], None, [f"not a .zip file: {zpath}"]

    try:
        zf = zipfile.ZipFile(zpath, "r")
    except Exception as exc:  # noqa: BLE001
        return "invalid", [], None, [f"failed to open zip: {exc}"]

    with zf:
        names = zf.namelist()
        for n in names:
            if not _zip_is_safe_member_name(n):
                errors.append(f"unsafe zip entry path: {n!r}")
            if _is_secret_like_filename(n):
                errors.append(f"secret-like file present in package: {n}")
        if errors:
            return "invalid", warnings, None, errors

        if "airos_package_manifest.json" not in names:
            return "invalid", warnings, None, ["missing airos_package_manifest.json"]

        try:
            pkg_manifest = json.loads(zf.read("airos_package_manifest.json").decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return "invalid", warnings, None, [f"invalid airos_package_manifest.json: {exc}"]
        if not isinstance(pkg_manifest, dict):
            return "invalid", warnings, None, ["airos_package_manifest.json must be a JSON object"]

        desc_name = "app/app_descriptor.yaml"
        if desc_name not in names:
            return "invalid", warnings, None, ["missing app/app_descriptor.yaml"]
        try:
            desc = yaml.safe_load(zf.read(desc_name).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return "invalid", warnings, None, [f"invalid app_descriptor.yaml in package: {exc}"]
        if not isinstance(desc, dict):
            return "invalid", warnings, None, ["app_descriptor.yaml in package must be a YAML object"]

        vstatus = str(pkg_manifest.get("validation_status") or "").strip()

        # Validate descriptor against schema (strict unless package was valid_with_warnings).
        try:
            from urban_platform.api.app_descriptors import _load_descriptor_schema_validator  # noqa: WPS433

            v = _load_descriptor_schema_validator()
            if v is None:
                warnings.append("descriptor schema validator not available in repo")
            else:
                v.validate(desc)
        except Exception as exc:  # noqa: BLE001
            msg = f"descriptor schema validation failed: {exc}"
            if vstatus == "valid_with_warnings":
                warnings.append(msg)
            else:
                return "invalid", warnings, None, [msg]

        man_app_id = str(pkg_manifest.get("app_id") or "").strip()
        man_ver = str(pkg_manifest.get("version") or "").strip()
        desc_app_id = str(desc.get("app_id") or "").strip()
        desc_ver = str(desc.get("version") or "").strip()
        if man_app_id and desc_app_id and man_app_id != desc_app_id:
            errors.append(f"package manifest app_id {man_app_id!r} != descriptor app_id {desc_app_id!r}")
        if man_ver and desc_ver and man_ver != desc_ver:
            errors.append(f"package manifest version {man_ver!r} != descriptor version {desc_ver!r}")
        if errors:
            return "invalid", warnings, None, errors

        # Build metadata
        dl = desc.get("decision_logic") if isinstance(desc.get("decision_logic"), dict) else {}
        bids = dl.get("builder_ids") if isinstance(dl, dict) else []
        if not isinstance(bids, list):
            bids = []
        dash = desc.get("dashboard") if isinstance(desc.get("dashboard"), dict) else {}
        safety = desc.get("safety") if isinstance(desc.get("safety"), dict) else {}
        blocked = safety.get("blocked_uses") if isinstance(safety, dict) else []
        if not isinstance(blocked, list):
            blocked = []

        vw = pkg_manifest.get("validation_warnings") or []
        if not isinstance(vw, list):
            vw = []

        local_contracts = sorted([n for n in names if n.startswith("app/contracts/") and n.endswith(".schema.json")])

        md: dict[str, Any] = {
            "package_id": pkg_manifest.get("package_id"),
            "app_id": desc.get("app_id"),
            "name": desc.get("name"),
            "version": desc.get("version"),
            "domain_id": desc.get("domain_id"),
            "status": desc.get("status"),
            "app_type": desc.get("app_type"),
            "packaged_at": pkg_manifest.get("packaged_at"),
            "validation_status": vstatus,
            "warnings_count": len(vw) + len(warnings),
            "input_contracts": desc.get("input_contracts") or [],
            "output_contracts": desc.get("output_contracts") or [],
            "builder_ids": bids,
            "dashboard": dash,
            "safety": {
                "blocked_uses": blocked,
                "review_support_only": (safety.get("review_support_only") if isinstance(safety, dict) else None),
                "human_review_required": (safety.get("human_review_required") if isinstance(safety, dict) else None),
            },
            "local_contract_files": local_contracts,
            "package_note": pkg_manifest.get("note"),
        }

        final_status = "inspectable_with_warnings" if (warnings or vw) else "inspectable"
        return final_status, warnings, md, []


def _apps_inspect_package(repo_root: Path, package_zip: str) -> int:
    p = Path(package_zip)
    zpath = p if p.is_absolute() else (repo_root / p).resolve()
    status, warns, md, errs = _inspect_package_metadata(repo_root, zpath)
    if status == "invalid" or md is None:
        for e in errs:
            print(f"- {e}", file=sys.stderr)
        return 1

    print("AirOS app package inspection")
    print(f"- package: {zpath}")

    print("")
    print("## Package")
    for k in ["package_id", "app_id", "version", "packaged_at", "validation_status"]:
        print(f"- {k}: {md.get(k)}")
    print(f"- warnings_count: {md.get('warnings_count')}")
    if md.get("package_note"):
        print(f"- note: {md.get('package_note')}")

    print("")
    print("## App descriptor")
    for k in ["app_id", "name", "domain_id", "status", "app_type"]:
        print(f"- {k}: {md.get(k)}")
    print(f"- input_contracts: {md.get('input_contracts')}")
    print(f"- output_contracts: {md.get('output_contracts')}")
    print(f"- builder_ids: {md.get('builder_ids')}")
    print(f"- dashboard: {md.get('dashboard')}")
    safety = md.get("safety") if isinstance(md.get("safety"), dict) else {}
    print(f"- safety.blocked_uses: {(safety.get('blocked_uses') if isinstance(safety, dict) else None)}")

    print("")
    print("## Safety scan")
    print("- secret_like_files: none detected")
    if warns:
        print("- warnings:")
        for w in warns:
            print(f"  - {w}")

    print("")
    print("## Contracts")
    for ck in (md.get("input_contracts") or []) + (md.get("output_contracts") or []):
        if isinstance(ck, str):
            known = air_sdk.contract_exists(ck)
            print(f"- {ck}: {'known (repo manifest)' if known else 'package-local or unknown'}")
    local_contracts = md.get("local_contract_files") or []
    if isinstance(local_contracts, list) and local_contracts:
        print("- local_contract_files:")
        for n in local_contracts:
            print(f"  - {n}")

    print("")
    print("## Decision logic metadata")
    from urban_platform.deployments.builder_registry import has_builder  # noqa: WPS433

    bids = md.get("builder_ids") or []
    if isinstance(bids, list) and bids:
        for bid in bids:
            if isinstance(bid, str):
                print(f"- {bid}: {'allowlisted in this repo' if has_builder(bid) else 'not allowlisted in this repo'}")
    else:
        print("- builder_ids: (none)")
    print("Inspection does not execute builders. Non-allowlisted builders cannot run in AirOS Core.")

    print("")
    print("## Result")
    print(f"status: {status}")
    return 0


def _catalog_dir(repo_root: Path, catalog_dir: str | None) -> Path:
    base = Path(catalog_dir) if catalog_dir else (repo_root / ".airos" / "catalog")
    return base if base.is_absolute() else (repo_root / base).resolve()


def _catalog_index_path(repo_root: Path, catalog_dir: str | None) -> Path:
    d = _catalog_dir(repo_root, catalog_dir)
    return d / "index.json"


def _load_catalog_index(repo_root: Path, catalog_dir: str | None) -> dict[str, Any]:
    p = _catalog_index_path(repo_root, catalog_dir)
    if not p.exists():
        return {"apps": {}}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"apps": {}}
    if not isinstance(obj, dict):
        return {"apps": {}}
    if not isinstance(obj.get("apps"), dict):
        obj["apps"] = {}
    return obj  # type: ignore[return-value]


def _save_catalog_index(repo_root: Path, catalog_dir: str | None, idx: dict[str, Any]) -> None:
    d = _catalog_dir(repo_root, catalog_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = _catalog_index_path(repo_root, catalog_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)


def _catalog_add_package(repo_root: Path, package_zip: str, *, catalog_dir: str | None, force: bool) -> int:
    p = Path(package_zip)
    zpath = p if p.is_absolute() else (repo_root / p).resolve()

    status, warns, md, errs = _inspect_package_metadata(repo_root, zpath)
    if status == "invalid" or md is None:
        print("catalog add-package failed (package is invalid)", file=sys.stderr)
        for e in errs:
            print(f"- {e}", file=sys.stderr)
        return 1

    app_id = str(md.get("app_id") or "").strip()
    version = str(md.get("version") or "").strip()
    if not app_id or not version:
        print("catalog add-package failed: missing app_id/version in package metadata", file=sys.stderr)
        return 1

    idx = _load_catalog_index(repo_root, catalog_dir)
    apps = idx.get("apps") if isinstance(idx.get("apps"), dict) else {}
    if not isinstance(apps, dict):
        apps = {}
    by_ver = apps.get(app_id) if isinstance(apps.get(app_id), dict) else {}
    if not isinstance(by_ver, dict):
        by_ver = {}
    if version in by_ver and not force:
        print(f"catalog already has {app_id}@{version}. Re-run with --force to overwrite.", file=sys.stderr)
        return 1

    try:
        pkg_path_str = str(zpath.relative_to(repo_root))
    except Exception:
        pkg_path_str = str(zpath)

    added_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    safety = md.get("safety") if isinstance(md.get("safety"), dict) else {}
    entry = {
        "app_id": app_id,
        "name": md.get("name"),
        "version": version,
        "domain_id": md.get("domain_id"),
        "status": md.get("status"),
        "app_type": md.get("app_type"),
        "package_path": pkg_path_str,
        "package_id": md.get("package_id"),
        "packaged_at": md.get("packaged_at"),
        "added_at": added_at,
        "validation_status": md.get("validation_status"),
        "warnings_count": md.get("warnings_count"),
        "input_contracts": md.get("input_contracts") or [],
        "output_contracts": md.get("output_contracts") or [],
        "builder_ids": md.get("builder_ids") or [],
        "dashboard": md.get("dashboard") or {},
        "safety": {
            "blocked_uses": (safety.get("blocked_uses") if isinstance(safety, dict) else []),
            "review_support_only": (safety.get("review_support_only") if isinstance(safety, dict) else None),
            "human_review_required": (safety.get("human_review_required") if isinstance(safety, dict) else None),
        },
        "catalog_note": "Catalog entry is metadata only. Package is not installed, registered, allowlisted, or executable.",
    }
    by_ver[version] = entry
    apps[app_id] = by_ver
    idx["apps"] = apps
    _save_catalog_index(repo_root, catalog_dir, idx)

    print("Catalog add-package: ok")
    print(f"- catalog_dir: {_catalog_dir(repo_root, catalog_dir)}")
    print(f"- app_id: {app_id}")
    print(f"- version: {version}")
    print(f"- inspection_status: {status}")
    if warns:
        print(f"- inspection_warnings: {len(warns)}")
    return 0


def _catalog_list(repo_root: Path, *, catalog_dir: str | None) -> int:
    idx = _load_catalog_index(repo_root, catalog_dir)
    apps = idx.get("apps") if isinstance(idx.get("apps"), dict) else {}
    if not isinstance(apps, dict) or not apps:
        print("Catalog is empty. Add a package with: python tools/airos_cli.py catalog add-package <zip>")
        return 0
    for app_id in sorted(apps.keys()):
        by_ver = apps.get(app_id)
        if not isinstance(by_ver, dict):
            continue
        for ver in sorted(by_ver.keys()):
            e = by_ver.get(ver)
            if not isinstance(e, dict):
                continue
            print(
                f"{app_id}\t{e.get('name')}\t{ver}\t{e.get('domain_id')}\t{e.get('status')}\t{e.get('validation_status')}"
            )
    return 0


def _catalog_show(repo_root: Path, app_id: str, *, catalog_dir: str | None) -> int:
    aid = str(app_id or "").strip()
    if not aid:
        print("app_id is required", file=sys.stderr)
        return 2
    idx = _load_catalog_index(repo_root, catalog_dir)
    apps = idx.get("apps") if isinstance(idx.get("apps"), dict) else {}
    if not isinstance(apps, dict) or aid not in apps:
        print(f"Unknown app_id in catalog: {aid}", file=sys.stderr)
        return 1
    by_ver = apps.get(aid)
    if not isinstance(by_ver, dict) or not by_ver:
        print(f"Unknown app_id in catalog: {aid}", file=sys.stderr)
        return 1
    print(yaml.safe_dump({"app_id": aid, "versions": by_ver}, sort_keys=False))
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

    health = sub.add_parser(
        "health",
        help="Report liveness/readiness (local or via Core API).",
        description=(
            "Without --api-base-url, runs local metadata checks (read-only). With --api-base-url, calls "
            "/health/live and /health/ready and exits non-zero if not ready."
        ),
    )
    health.add_argument(
        "--api-base-url",
        type=str,
        default=None,
        metavar="URL",
        help="Optional Core API base URL (e.g. http://127.0.0.1:8000). If set, checks API /health/live and /health/ready.",
    )

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
    dep_run.add_argument(
        "--store-dir",
        default=None,
        type=str,
        metavar="PATH",
        help="Optional FileAirOsStore root passed through to tools/deployment_runner/run_deployment.py (additive JSONL store).",
    )
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
    dep_init.add_argument(
        "--from-example",
        type=str,
        default=None,
        metavar="NAME",
        help="Initialize a runnable workspace by copying deployments/examples/<NAME> into --output-dir (overrides profile identity fields).",
    )
    dep_init.add_argument("--deployment-id", required=True, type=str, metavar="ID", help="Stable deployment identifier.")
    dep_init.add_argument("--deployment-name", required=True, type=str, metavar="NAME", help="Human-readable deployment name.")
    dep_init.add_argument(
        "--deployment-type",
        required=False,
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
    dep_init.add_argument("--owner-organization", required=False, type=str, metavar="ORG", help="Owning organization label or placeholder.")
    dep_init.add_argument(
        "--environment",
        required=False,
        type=str,
        metavar="ENV",
        choices=["local", "staging", "production"],
        help="Runtime environment label.",
    )
    dep_init.add_argument(
        "--domains",
        required=False,
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

    examples = sub.add_parser(
        "examples",
        help="Discover runnable deployment examples (read-only).",
        description="Scans deployments/examples/ and prints example metadata. Does not validate or run deployments.",
    )
    ex_sub = examples.add_subparsers(dest="examples_command", required=True)
    ex_sub.add_parser("list", help="List available examples under deployments/examples/.")
    ex_desc = ex_sub.add_parser("describe", help="Describe one example and print recommended commands.")
    ex_desc.add_argument("example_name", type=str, metavar="NAME", help="Example folder name under deployments/examples/.")

    deployments = sub.add_parser(
        "deployments",
        help="Discover example deployment profiles (read-only).",
        description="Alias for examples list/describe, using deployment_id as the lookup key.",
    )
    dsub = deployments.add_subparsers(dest="deployments_command", required=True)
    dsub.add_parser("list", help="Alias for: examples list")
    dshow = dsub.add_parser("show", help="Alias for: examples describe <deployment_id>")
    dshow.add_argument("deployment_id", type=str, metavar="DEPLOYMENT_ID")

    inv = sub.add_parser(
        "inventory",
        help="Show AirOS platform inventory (read-only).",
        description="Summarizes contracts, apps, adapters, catalogs, deployments, and optional runtime store counts.",
    )
    inv.add_argument(
        "--include-runtime",
        action="store_true",
        help="Include local FileAirOsStore counts (records/runs/outputs/receipts/audit). Never executes builders.",
    )

    evidence = sub.add_parser(
        "evidence",
        help="Evidence bundle export (read-only).",
        description="Exports a portable zip bundle of runs/records/outputs/receipts/audit events for review/debug/audit support. Does not execute builders.",
    )
    esub = evidence.add_subparsers(dest="evidence_command", required=True)
    exp = esub.add_parser("export", help="Export an evidence bundle zip for a run_id or deployment_id.")
    exp.add_argument("--run-id", required=False, type=str, default=None, metavar="RUN_ID", help="Export evidence for one run_id.")
    exp.add_argument(
        "--deployment-id",
        required=False,
        type=str,
        default=None,
        metavar="DEPLOYMENT_ID",
        help="Export evidence for a deployment_id (may include multiple runs).",
    )
    exp.add_argument("--store-dir", required=True, type=str, metavar="DIR", help="FileAirOsStore root (contains *.jsonl).")
    exp.add_argument("--output-dir", required=True, type=str, metavar="DIR", help="Directory to write the evidence bundle zip.")
    insp = esub.add_parser("inspect", help="Inspect an evidence bundle zip (offline, read-only).")
    insp.add_argument("bundle_zip", type=str, metavar="ZIP", help="Path to an evidence bundle zip.")
    ver = esub.add_parser("verify", help="Verify internal consistency of an evidence bundle zip (offline, read-only).")
    ver.add_argument("bundle_zip", type=str, metavar="ZIP", help="Path to an evidence bundle zip.")
    red = esub.add_parser("redact", help="Create a redacted sharing copy of an evidence bundle zip (read-only).")
    red.add_argument("bundle_zip", type=str, metavar="ZIP", help="Path to an evidence bundle zip.")
    red.add_argument("--profile", required=True, type=str, choices=["public_demo", "internal_review"], metavar="PROFILE")
    red.add_argument("--output-dir", required=True, type=str, metavar="DIR", help="Directory to write the redacted bundle zip.")

    store = sub.add_parser(
        "store",
        help="Pilot FileAirOsStore lifecycle helpers (read-only).",
        description="Backup helpers for the pilot FileAirOsStore (JSONL directory). Does not restore/import/compact and does not execute builders.",
    )
    ssub = store.add_subparsers(dest="store_command", required=True)
    sb = ssub.add_parser("backup", help="Create a safe zip backup of a pilot store directory (read-only).")
    sb.add_argument("--store-dir", required=True, type=str, metavar="DIR", help="FileAirOsStore root (contains *.jsonl).")
    sb.add_argument("--output-dir", required=True, type=str, metavar="DIR", help="Directory to write the backup zip.")
    si = ssub.add_parser("inspect-backup", help="Inspect a pilot store backup zip (offline, read-only).")
    si.add_argument("backup_zip", type=str, metavar="ZIP", help="Path to a pilot store backup zip.")
    sv = ssub.add_parser("verify-backup", help="Verify internal consistency of a pilot store backup zip (offline, read-only).")
    sv.add_argument("backup_zip", type=str, metavar="ZIP", help="Path to a pilot store backup zip.")
    srd = ssub.add_parser("restore-dry-run", help="Dry-run restore checks for a pilot store backup zip (no writes).")
    srd.add_argument("backup_zip", type=str, metavar="ZIP", help="Path to a pilot store backup zip.")
    srd.add_argument("--target-dir", required=True, type=str, metavar="DIR", help="Target store directory (not created).")

    contracts = sub.add_parser("contracts", help="Inspect manifest-backed contract schemas (read-only).")
    csub = contracts.add_subparsers(dest="contracts_command", required=True)
    csub.add_parser("list", help="List contract keys from specifications/manifest.json.")
    cshow = csub.add_parser("show", help="Print the JSON Schema for one contract_key.")
    cshow.add_argument("contract_key", type=str, metavar="CONTRACT_KEY")

    fixtures = sub.add_parser("fixtures", help="Validate fixture payloads against contracts (read-only).")
    fsub = fixtures.add_subparsers(dest="fixtures_command", required=True)
    fval = fsub.add_parser("validate", help="Validate a JSON fixture file against a contract_key.")
    fval.add_argument("contract_key", type=str, metavar="CONTRACT_KEY")
    fval.add_argument("path", type=str, metavar="PATH")

    apps = sub.add_parser("apps", help="Inspect AirOS app descriptors (read-only).")
    asub = apps.add_subparsers(dest="apps_command", required=True)
    asub.add_parser("list", help="List app descriptors under specifications/app_descriptors/.")
    ashow = asub.add_parser("show", help="Print one app descriptor by app_id.")
    ashow.add_argument("app_id", type=str, metavar="APP_ID")
    aexplain = asub.add_parser("explain", help="Explain one app descriptor in developer-friendly terms.")
    aexplain.add_argument("app_id", type=str, metavar="APP_ID")
    ascaffold = asub.add_parser("scaffold", help="Create a local scaffold for a new AirOS App (not registered/executable).")
    ascaffold.add_argument("app_id", type=str, metavar="APP_ID")
    ascaffold.add_argument("--domain-id", required=True, type=str, metavar="DOMAIN_ID")
    ascaffold.add_argument("--output-dir", required=False, type=str, default=None, metavar="DIR")
    ascaffold.add_argument("--force", action="store_true", help="Overwrite an existing output directory.")
    aval = asub.add_parser("validate", help="Validate a local AirOS App package folder (read-only).")
    aval.add_argument("app_path", type=str, metavar="APP_PATH")
    apkg = asub.add_parser("package", help="Package a local AirOS App folder into a zip (review artifact).")
    apkg.add_argument("app_path", type=str, metavar="APP_PATH")
    apkg.add_argument("--output-dir", required=False, type=str, default=None, metavar="DIR")
    apkg.add_argument("--force", action="store_true", help="Overwrite an existing package zip if present.")
    ainspect = asub.add_parser("inspect-package", help="Inspect a packaged AirOS App zip (read-only).")
    ainspect.add_argument("package_zip", type=str, metavar="ZIP")

    catalog = sub.add_parser("catalog", help="Local app package catalog (metadata only).")
    csub = catalog.add_subparsers(dest="catalog_command", required=True)
    cadd = csub.add_parser("add-package", help="Inspect and add a package's metadata to the local catalog.")
    cadd.add_argument("package_zip", type=str, metavar="ZIP")
    cadd.add_argument("--catalog-dir", required=False, type=str, default=None, metavar="DIR")
    cadd.add_argument("--force", action="store_true", help="Overwrite an existing app_id@version entry.")
    clist = csub.add_parser("list", help="List catalog entries.")
    clist.add_argument("--catalog-dir", required=False, type=str, default=None, metavar="DIR")
    cshow = csub.add_parser("show", help="Show catalog metadata for an app_id.")
    cshow.add_argument("app_id", type=str, metavar="APP_ID")
    cshow.add_argument("--catalog-dir", required=False, type=str, default=None, metavar="DIR")

    adapters = sub.add_parser("adapters", help="Inspect Provider Adapter Descriptors (read-only).")
    adsub = adapters.add_subparsers(dest="adapters_command", required=True)
    adsub.add_parser("list", help="List provider adapter descriptors under specifications/provider_adapters/.")
    adshow = adsub.add_parser("show", help="Show one provider adapter descriptor by adapter_id.")
    adshow.add_argument("adapter_id", type=str, metavar="ADAPTER_ID")

    catalogs = sub.add_parser("catalogs", help="Inspect reference catalog examples (read-only).")
    casub = catalogs.add_subparsers(dest="catalogs_command", required=True)
    casub.add_parser("list", help="List local reference catalog examples under specifications/examples/reference_data/.")
    cashow = casub.add_parser("show", help="Show one local reference catalog by catalog_id (pretty JSON).")
    cashow.add_argument("catalog_id", type=str, metavar="CATALOG_ID")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = _find_repo_root(Path(__file__).resolve())

    if args.command == "doctor":
        return _doctor(repo_root, run_conformance=bool(args.run_conformance))

    if args.command == "conformance":
        return _run(_plan_conformance(repo_root))

    if args.command == "health":
        api_base = getattr(args, "api_base_url", None)
        if api_base:
            return _health_api(repo_root, api_base_url=str(api_base))
        return _health_local(repo_root)

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
            from_example=args.from_example,
            deployment_id=str(args.deployment_id),
            deployment_name=str(args.deployment_name),
            deployment_type=(str(args.deployment_type) if args.deployment_type is not None else None),
            owner_organization=(str(args.owner_organization) if args.owner_organization is not None else None),
            environment=(str(args.environment) if args.environment is not None else None),
            domains_csv=(str(args.domains) if args.domains is not None else None),
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
        sdir = getattr(args, "store_dir", None)
        return _run(
            _plan_deployment_run(repo_root, str(args.deployment_path), store_dir=str(sdir) if sdir else None)
        )

    if args.command == "registry" and args.registry_command == "check":
        # Keep this simple: supervisor already includes registry hygiene probes.
        return _run(_plan_supervisor(repo_root, domain=None, run_conformance=False))

    if args.command == "examples" and args.examples_command == "list":
        return _examples_list(repo_root)

    if args.command == "examples" and args.examples_command == "describe":
        return _examples_describe(repo_root, str(args.example_name))

    if args.command == "deployments" and args.deployments_command == "list":
        return _deployments_list(repo_root)

    if args.command == "deployments" and args.deployments_command == "show":
        return _deployments_show(repo_root, str(args.deployment_id))

    if args.command == "inventory":
        return _inventory(include_runtime=bool(getattr(args, "include_runtime", False)))

    if args.command == "evidence" and args.evidence_command == "export":
        return _evidence_export(
            repo_root,
            run_id=getattr(args, "run_id", None),
            deployment_id=getattr(args, "deployment_id", None),
            store_dir=str(getattr(args, "store_dir")),
            output_dir=str(getattr(args, "output_dir")),
        )

    if args.command == "evidence" and args.evidence_command == "inspect":
        return _evidence_inspect(repo_root, bundle_zip=str(getattr(args, "bundle_zip")))

    if args.command == "evidence" and args.evidence_command == "verify":
        return _evidence_verify(repo_root, bundle_zip=str(getattr(args, "bundle_zip")))

    if args.command == "evidence" and args.evidence_command == "redact":
        return _evidence_redact(
            repo_root,
            bundle_zip=str(getattr(args, "bundle_zip")),
            profile=str(getattr(args, "profile")),
            output_dir=str(getattr(args, "output_dir")),
        )

    if args.command == "store" and args.store_command == "backup":
        return _store_backup(
            repo_root,
            store_dir=str(getattr(args, "store_dir")),
            output_dir=str(getattr(args, "output_dir")),
        )

    if args.command == "store" and args.store_command == "inspect-backup":
        return _store_inspect_backup(repo_root, backup_zip=str(getattr(args, "backup_zip")))

    if args.command == "store" and args.store_command == "verify-backup":
        return _store_verify_backup(repo_root, backup_zip=str(getattr(args, "backup_zip")))

    if args.command == "store" and args.store_command == "restore-dry-run":
        return _store_restore_dry_run(
            repo_root,
            backup_zip=str(getattr(args, "backup_zip")),
            target_dir=str(getattr(args, "target_dir")),
        )

    if args.command == "contracts" and args.contracts_command == "list":
        return _contracts_list()

    if args.command == "contracts" and args.contracts_command == "show":
        return _contracts_show(str(args.contract_key))

    if args.command == "fixtures" and args.fixtures_command == "validate":
        return _fixtures_validate(str(args.contract_key), str(args.path))

    if args.command == "apps" and args.apps_command == "list":
        return _apps_list()

    if args.command == "apps" and args.apps_command == "show":
        return _apps_show(str(args.app_id))

    if args.command == "apps" and args.apps_command == "explain":
        return _apps_explain(repo_root, str(args.app_id))

    if args.command == "apps" and args.apps_command == "scaffold":
        return _apps_scaffold(
            repo_root,
            app_id=str(args.app_id),
            domain_id=str(args.domain_id),
            output_dir=(str(args.output_dir) if args.output_dir is not None else None),
            force=bool(args.force),
        )

    if args.command == "apps" and args.apps_command == "validate":
        return _apps_validate(repo_root, str(args.app_path))

    if args.command == "apps" and args.apps_command == "package":
        return _apps_package(repo_root, str(args.app_path), output_dir=args.output_dir, force=bool(args.force))

    if args.command == "apps" and args.apps_command == "inspect-package":
        return _apps_inspect_package(repo_root, str(args.package_zip))

    if args.command == "catalog" and args.catalog_command == "add-package":
        return _catalog_add_package(
            repo_root,
            str(args.package_zip),
            catalog_dir=(str(args.catalog_dir) if args.catalog_dir is not None else None),
            force=bool(args.force),
        )

    if args.command == "catalog" and args.catalog_command == "list":
        return _catalog_list(repo_root, catalog_dir=(str(args.catalog_dir) if args.catalog_dir is not None else None))

    if args.command == "catalog" and args.catalog_command == "show":
        return _catalog_show(
            repo_root,
            str(args.app_id),
            catalog_dir=(str(args.catalog_dir) if args.catalog_dir is not None else None),
        )

    if args.command == "adapters" and args.adapters_command == "list":
        desc = air_sdk.list_provider_adapter_descriptors()
        if not desc:
            print("No provider adapter descriptors found under specifications/provider_adapters/")
            return 0
        for d in desc:
            aid = str(d.get("adapter_id") or "").strip()
            name = str(d.get("name") or "").strip()
            version = str(d.get("version") or "").strip()
            status = str(d.get("status") or "").strip()
            adapter_type = str(d.get("adapter_type") or "").strip()
            sst = str(d.get("source_system_type") or "").strip()
            outs = d.get("output_contracts") or []
            out_n = len(outs) if isinstance(outs, list) else 0
            if not aid:
                continue
            print(f"{aid}\t{name}\t{version}\t{status}\t{adapter_type}\t{sst}\toutput_contracts={out_n}")
        return 0

    if args.command == "adapters" and args.adapters_command == "show":
        aid = str(args.adapter_id or "").strip()
        d = air_sdk.get_provider_adapter_descriptor(aid)
        if not d:
            print(f"Unknown adapter_id: {aid}", file=sys.stderr)
            return 1
        print("# Provider Adapter Descriptor (metadata only; not executable)")
        print("# Runtime connector execution remains reviewed code + deployment configuration.")
        print(yaml.safe_dump(d, sort_keys=False))
        return 0

    if args.command == "catalogs" and args.catalogs_command == "list":
        items = air_sdk.list_reference_catalogs()
        if not items:
            print("No local reference catalog examples found under specifications/examples/reference_data/")
            return 0
        for c in items:
            cid = str(c.get("catalog_id") or "").strip()
            ver = str(c.get("version") or "").strip()
            ctype = str(c.get("catalog_type") or "").strip()
            pub = str(c.get("publisher_node_id") or "").strip()
            status = str(c.get("status") or "").strip()
            entries = c.get("entries") or []
            n = len(entries) if isinstance(entries, list) else 0
            exp = str(c.get("expires_at") or "").strip()
            if not cid:
                continue
            print(f"{cid}\t{ver}\t{ctype}\t{pub}\t{status}\tentries={n}\texpires_at={exp or '—'}")
        return 0

    if args.command == "catalogs" and args.catalogs_command == "show":
        cid = str(args.catalog_id or "").strip()
        c = air_sdk.get_reference_catalog(cid)
        if not c:
            print(f"Unknown catalog_id: {cid}", file=sys.stderr)
            return 1
        print("# Reference catalog example (local, read-only fixture)")
        print("# No pull/cache/TTL, publication workflows, signatures, or federation are implemented here.")
        print(json.dumps(c, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

