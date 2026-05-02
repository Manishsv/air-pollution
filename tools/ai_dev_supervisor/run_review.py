from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Optional

# Allow running as a standalone script:
# `python tools/ai_dev_supervisor/run_review.py`
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from conformance_probe import probe_conformance  # noqa: E402
from dashboard_probe import probe_dashboard  # noqa: E402
from domain_maturity_probe import probe_domain_maturity  # noqa: E402
from spec_policy_probe import probe_spec_policy  # noqa: E402


EXPECTED_SPEC_FOLDERS = [
    "specifications/provider_contracts",
    "specifications/platform_objects",
    "specifications/domain_specs",
    "specifications/consumer_contracts",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_repo_root(start: Path) -> Path:
    """
    Find repo root by walking upward for expected governance anchors.
    """
    cur = start.resolve()
    for _ in range(10):
        if (
            (cur / "README.md").exists()
            and (cur / "AGENTS.md").exists()
            and (cur / "specifications").exists()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve().parents[3]


def _read_text_if_exists(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None


def _md_bool(v: Optional[bool]) -> str:
    if v is True:
        return "PASS"
    if v is False:
        return "FAIL"
    return "UNKNOWN"


@dataclass(frozen=True)
class RepoGovernanceStatus:
    readme_exists: bool
    readme_mentions_specs_first: Optional[bool]
    agents_exists: bool
    agents_mentions_specs_first: Optional[bool]


def _probe_repo_governance(repo_root: Path) -> RepoGovernanceStatus:
    readme = repo_root / "README.md"
    agents = repo_root / "AGENTS.md"

    readme_text = _read_text_if_exists(readme)
    agents_text = _read_text_if_exists(agents)

    def has_specs_first_mentions(text: Optional[str]) -> Optional[bool]:
        if text is None:
            return None
        needles = [
            "SPECS_FIRST_DEVELOPMENT",
            "specs-first",
            "specifications/",
        ]
        return any(n.lower() in text.lower() for n in needles)

    return RepoGovernanceStatus(
        readme_exists=readme.exists(),
        readme_mentions_specs_first=has_specs_first_mentions(readme_text),
        agents_exists=agents.exists(),
        agents_mentions_specs_first=has_specs_first_mentions(agents_text),
    )


def _probe_spec_folders(repo_root: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for rel in EXPECTED_SPEC_FOLDERS:
        out[rel] = (repo_root / rel).exists()
    return out


def _risk_register(
    *,
    spec_policy_loaded: bool,
    specs_first_flag: Optional[bool],
    spec_folders: dict[str, bool],
    governance: RepoGovernanceStatus,
    conformance_attempted: bool,
    conformance_exit_code: Optional[int],
    conformance_report_loaded: bool,
) -> list[str]:
    risks: list[str] = []

    if not spec_policy_loaded:
        risks.append(
            "Machine-readable specs-first policy not loaded (missing or invalid YAML)."
        )
    if specs_first_flag is False:
        risks.append("Spec policy indicates specs_first=false (unexpected for AirOS).")

    missing_folders = [k for k, ok in spec_folders.items() if not ok]
    if missing_folders:
        risks.append(
            "Expected specification folders missing: " + ", ".join(missing_folders)
        )

    if governance.readme_exists and governance.readme_mentions_specs_first is False:
        risks.append("README exists but does not mention specs-first governance/docs.")
    if not governance.readme_exists:
        risks.append("README.md missing (project governance entrypoint absent).")

    if governance.agents_exists and governance.agents_mentions_specs_first is False:
        risks.append("AGENTS.md exists but does not mention specs-first rules.")
    if not governance.agents_exists:
        risks.append("AGENTS.md missing (agent governance rules absent).")

    if conformance_attempted and conformance_exit_code not in (0, None):
        risks.append("Conformance run failed (non-zero exit code).")
    if conformance_attempted and not conformance_report_loaded:
        risks.append("Conformance was run but conformance report was not found/loaded.")

    if not conformance_attempted and not conformance_report_loaded:
        risks.append("No conformance evidence available (report missing and not run).")

    return risks


def _recommended_next_task(
    *,
    spec_folders: dict[str, bool],
    conformance_report_loaded: bool,
    conformance_attempted: bool,
    conformance_exit_code: Optional[int],
    risks: list[str],
) -> str:
    missing_folders = [k for k, ok in spec_folders.items() if not ok]
    if missing_folders:
        return "Create missing specification family folders and add initial README placeholders."

    if conformance_attempted and conformance_exit_code not in (0, None):
        return "Fix conformance failures and regenerate `data/outputs/conformance_report.json`."

    if not conformance_report_loaded:
        return "Run conformance to generate `data/outputs/conformance_report.json` and attach evidence."

    if risks:
        return "Resolve the top risk in this report, starting with specs-first policy/folder governance."

    return "Add new provider/domain/consumer work only via specs-first sequence (update specs, then run conformance)."


def _render_markdown(report: dict[str, Any]) -> str:
    ts = report.get("timestamp_utc", "UNKNOWN")

    policy = report.get("spec_policy", {})
    policy_path = policy.get("policy_path") or "NOT FOUND"
    specs_first = policy.get("specs_first")

    folders = report.get("expected_spec_folders", {})
    governance = report.get("governance", {})
    conformance = report.get("conformance", {})
    dashboard = report.get("dashboard_probe")
    domain_maturity = report.get("domain_maturity")

    risks = report.get("risks", [])
    next_task = report.get("recommended_next_task", "UNKNOWN")

    lines: list[str] = []
    lines.append("## AirOS AI Dev Supervisor — Local Review")
    lines.append("")
    lines.append(f"- **timestamp**: `{ts}`")
    lines.append("")
    lines.append("### Specs-first policy status")
    lines.append(f"- **policy_file**: `{policy_path}`")
    lines.append(f"- **specs_first**: **{_md_bool(specs_first)}**")
    if policy.get("errors"):
        lines.append("- **policy_errors**:")
        for e in policy["errors"]:
            lines.append(f"  - `{e}`")
    lines.append("")

    lines.append("### Expected folders status")
    for k in EXPECTED_SPEC_FOLDERS:
        ok = bool(folders.get(k))
        lines.append(f"- **{k}**: {'PASS' if ok else 'FAIL'}")
    lines.append("")

    lines.append("### README/AGENTS governance status")
    lines.append(f"- **README.md exists**: {'PASS' if governance.get('readme_exists') else 'FAIL'}")
    rm = governance.get("readme_mentions_specs_first")
    lines.append(f"- **README mentions specs-first/docs**: **{_md_bool(rm)}**")
    lines.append(f"- **AGENTS.md exists**: {'PASS' if governance.get('agents_exists') else 'FAIL'}")
    ag = governance.get("agents_mentions_specs_first")
    lines.append(f"- **AGENTS mentions specs-first rules**: **{_md_bool(ag)}**")
    lines.append("")

    lines.append("### Conformance status (if available)")
    attempted = bool(conformance.get("attempted"))
    lines.append(f"- **attempted**: `{attempted}`")
    if attempted:
        lines.append(f"- **exit_code**: `{conformance.get('exit_code')}`")
        lines.append(f"- **duration_s**: `{conformance.get('duration_s')}`")
    lines.append(f"- **report_path**: `{conformance.get('conformance_report_path')}`")
    lines.append(f"- **report_loaded**: `{bool(conformance.get('conformance_report_loaded'))}`")
    if conformance.get("errors"):
        lines.append("- **conformance_errors**:")
        for e in conformance["errors"]:
            lines.append(f"  - `{e}`")
    lines.append("")

    if dashboard is not None:
        lines.append("### Dashboard smoke probe (optional)")
        lines.append(f"- **dashboard_url**: `{dashboard.get('dashboard_url')}`")
        lines.append(f"- **attempted**: `{bool(dashboard.get('attempted'))}`")
        lines.append(f"- **reachable**: `{bool(dashboard.get('reachable'))}`")
        if dashboard.get("status_code") is not None:
            lines.append(f"- **status_code**: `{dashboard.get('status_code')}`")
        matched = dashboard.get("matched_labels") or []
        missing = dashboard.get("missing_labels") or []
        lines.append(f"- **matched_labels**: `{len(matched)}`")
        if matched:
            for lab in matched:
                lines.append(f"  - `{lab}`")
        lines.append(f"- **missing_labels**: `{len(missing)}`")
        if missing:
            for lab in missing:
                lines.append(f"  - `{lab}`")
        if dashboard.get("risks"):
            lines.append("- **dashboard_risks**:")
            for r in dashboard["risks"]:
                lines.append(f"  - {r}")
        if dashboard.get("errors"):
            lines.append("- **dashboard_errors**:")
            for e in dashboard["errors"]:
                lines.append(f"  - `{e}`")
        lines.append("")

    if domain_maturity is not None:
        lines.append("### Domain maturity")
        lines.append(f"- **domain**: `{domain_maturity.get('domain')}`")
        lines.append(f"- **maturity_stage**: `{domain_maturity.get('maturity_stage')}`")
        lines.append(f"- **completed_items**: `{len(domain_maturity.get('completed_items') or [])}`")
        lines.append(f"- **missing_items**: `{len(domain_maturity.get('missing_items') or [])}`")
        if domain_maturity.get("missing_items"):
            lines.append("- **missing**:")
            for p in domain_maturity["missing_items"]:
                lines.append(f"  - `{p}`")
        lines.append("- **recommended_next_task**:")
        lines.append(f"  - {domain_maturity.get('recommended_next_task')}")
        if domain_maturity.get("errors"):
            lines.append("- **domain_maturity_errors**:")
            for e in domain_maturity["errors"]:
                lines.append(f"  - `{e}`")
        lines.append("")

    lines.append("### Risks")
    if risks:
        for r in risks:
            lines.append(f"- {r}")
    else:
        lines.append("- No material risks detected by lightweight checks.")
    lines.append("")

    lines.append("### Recommended next task")
    lines.append(f"- {next_task}")
    lines.append("")

    return "\n".join(lines)


def _write_reports(repo_root: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    reports_dir = repo_root / "tools" / "ai_dev_supervisor" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / "agent_review_report.json"
    md_path = reports_dir / "agent_review_report.md"

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Local specs-first supervisor review (no external LLM).")
    parser.add_argument(
        "--dashboard-url",
        type=str,
        default=None,
        help="Optional Streamlit dashboard URL to smoke-probe (e.g. http://localhost:8501).",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Optional domain key to report maturity for (e.g. flood_risk).",
    )
    parser.add_argument(
        "--run-conformance",
        action="store_true",
        help="If set, run `python main.py --step conformance` before reporting.",
    )
    args = parser.parse_args()

    repo_root = _find_repo_root(Path(__file__).resolve())

    policy = probe_spec_policy(repo_root)
    spec_folders = _probe_spec_folders(repo_root)
    governance = _probe_repo_governance(repo_root)
    conformance = probe_conformance(repo_root, run=bool(args.run_conformance))
    domain_maturity = (
        probe_domain_maturity(repo_root, args.domain) if args.domain else None
    )
    dashboard_probe = probe_dashboard(args.dashboard_url) if args.dashboard_url else None

    risks = _risk_register(
        spec_policy_loaded=policy.loaded,
        specs_first_flag=policy.specs_first,
        spec_folders=spec_folders,
        governance=governance,
        conformance_attempted=conformance.attempted,
        conformance_exit_code=conformance.exit_code,
        conformance_report_loaded=conformance.conformance_report_loaded,
    )

    report: dict[str, Any] = {
        "timestamp_utc": _utc_now_iso(),
        "repo_root": str(repo_root),
        "spec_policy": policy.to_dict(),
        "expected_spec_folders": spec_folders,
        "governance": asdict(governance),
        "conformance": conformance.to_dict(),
        "dashboard_probe": dashboard_probe.to_dict() if dashboard_probe else None,
        "domain_maturity": domain_maturity.to_dict() if domain_maturity else None,
        "risks": risks,
        "recommended_next_task": _recommended_next_task(
            spec_folders=spec_folders,
            conformance_report_loaded=conformance.conformance_report_loaded,
            conformance_attempted=conformance.attempted,
            conformance_exit_code=conformance.exit_code,
            risks=risks,
        ),
    }

    _write_reports(repo_root, report)

    # Exit code semantics:
    # - If conformance was run, return its exit code (0 for success).
    # - Otherwise, succeed (0) as this is a lightweight report generator.
    if conformance.attempted and conformance.exit_code is not None:
        return int(conformance.exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

