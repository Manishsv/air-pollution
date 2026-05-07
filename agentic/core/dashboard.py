"""
Terminal dashboard for the agentic loop.

Shows: current task, verification baseline, open escalations, open decisions.
For each pending decision, prompts the human to pick an option and writes
chosen_option + resolved_at back to decisions.yaml.

Usage:
    python agentic/core/dashboard.py [--config PATH] [--tasks PATH] [--no-input]

Exit codes:
    0  Displayed successfully; no pending decisions remain after interaction
    1  Config or state files could not be loaded
    2  Pending decisions remain (--no-input mode or non-interactive)
"""

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from agentic.core.config import load_config, get_state_dir
from agentic.core.state import find_next_task, load_tasks_doc

REPO_ROOT = Path(__file__).resolve().parents[2]

# ANSI colours — gracefully degraded when stdout is not a tty
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI code only when stdout is a tty."""
    if sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


# ── State loaders ──────────────────────────────────────────────────────────

def load_yaml_list(path: Path) -> List[Dict[str, Any]]:
    """Load a YAML file expected to be a list. Returns [] if missing or empty."""
    if not path.exists():
        return []
    content = yaml.safe_load(path.read_text())
    return content if isinstance(content, list) else []


def save_yaml_list(path: Path, records: List[Dict[str, Any]]) -> None:
    path.write_text(yaml.dump(records, default_flow_style=False, sort_keys=False))


def get_pending_escalations(state_dir: Path) -> List[Dict[str, Any]]:
    return [
        e for e in load_yaml_list(state_dir / "escalations.yaml")
        if e.get("status") == "pending_human_decision"
    ]


def get_pending_decisions(state_dir: Path) -> List[Dict[str, Any]]:
    return [
        d for d in load_yaml_list(state_dir / "decisions.yaml")
        if d.get("status") == "pending"
    ]


# ── Display helpers ────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print()
    print(_c(_BOLD, f"{'─' * 60}"))
    print(_c(_BOLD + _CYAN, f"  {title}"))
    print(_c(_BOLD, f"{'─' * 60}"))


def display_current_task(tasks_doc: Dict[str, Any]) -> None:
    _section("Current Task")
    task = find_next_task(tasks_doc)
    if task is None:
        done = sum(1 for t in tasks_doc.get("tasks", []) if t.get("status") == "done")
        total = len(tasks_doc.get("tasks", []))
        print(f"  {_c(_GREEN, 'No pending tasks.')}  ({done}/{total} done)")
    else:
        print(f"  ID:    {_c(_BOLD, task.get('task_id', ''))}")
        print(f"  Type:  {task.get('type', '')}")
        scope = task.get("scope_description", "").strip().replace("\n", " ")
        print(f"  Scope: {scope}")
        deps = task.get("depends_on") or []
        if deps:
            print(f"  Deps:  {', '.join(deps)}")


def display_baseline(config: Dict[str, Any]) -> None:
    _section("Verification Baseline")
    baseline = config.get("verification", {}).get("baseline", {})
    if not baseline:
        print(f"  {_c(_DIM, '(no baseline configured)')}")
        return
    print(f"  pytest  : {baseline.get('pytest_passed', '?')} passed")
    print(f"  conform : {baseline.get('conformance_checks', '?')} checks")
    print(f"  supervisor: exit {baseline.get('supervisor_exit_code', '?')}")


def display_escalations(escalations: List[Dict[str, Any]]) -> None:
    _section(f"Open Escalations ({len(escalations)})")
    if not escalations:
        print(f"  {_c(_GREEN, 'None.')}")
        return
    for esc in escalations:
        print(f"  {_c(_YELLOW, esc.get('escalation_id', '?'))}")
        print(f"    Task       : {esc.get('task_id', '?')}")
        print(f"    Raised by  : {esc.get('raised_by', '?')}")
        print(f"    Condition  : {esc.get('stop_condition', '?')}")
        ctx = (esc.get("context") or "").strip()
        if ctx:
            print(f"    Context    : {ctx[:120]}{'…' if len(ctx) > 120 else ''}")
        rec = esc.get("recommendation", "")
        if rec:
            print(f"    Recommend  : {rec}")
        print()


def display_decisions(decisions: List[Dict[str, Any]]) -> None:
    _section(f"Pending Decisions ({len(decisions)})")
    if not decisions:
        print(f"  {_c(_GREEN, 'None.')}")
        return
    for dec in decisions:
        print(f"  {_c(_YELLOW, dec.get('decision_id', '?'))}")
        print(f"    Question: {dec.get('question', '?')}")
        if dec.get("why_now"):
            print(f"    Why now : {dec['why_now']}")
        if dec.get("recommendation"):
            print(f"    Recommend: {dec['recommendation']}")
        options = dec.get("options") or []
        for i, opt in enumerate(options, start=1):
            label = opt.get("label", "?")
            effort = opt.get("effort", "")
            consequence = opt.get("consequence", "")
            effort_str = f" [{effort}]" if effort else ""
            print(f"    [{i}] {label}{effort_str}")
            if consequence:
                print(f"        → {consequence}")
        print()


# ── Decision resolution ────────────────────────────────────────────────────

def resolve_decision(
    state_dir: Path,
    decision: Dict[str, Any],
    chosen_label: str,
    notes: str = "",
) -> None:
    """Write chosen_option, resolved_at, and status=resolved back to decisions.yaml."""
    path = state_dir / "decisions.yaml"
    records = load_yaml_list(path)
    for rec in records:
        if rec.get("decision_id") == decision.get("decision_id"):
            rec["status"] = "resolved"
            rec["chosen_option"] = chosen_label
            rec["resolved_by"] = "human"
            rec["resolved_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            if notes:
                rec["notes"] = notes
            break
    save_yaml_list(path, records)


def prompt_for_decision(decision: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    Interactive prompt for a single pending decision.

    Returns (chosen_label, notes) or None if the user skips.
    """
    options = decision.get("options") or []
    if not options:
        return None

    while True:
        raw = input(
            f"  Choose [1–{len(options)}] or s=skip, q=quit: "
        ).strip().lower()

        if raw == "q":
            print("  Quitting dashboard.")
            sys.exit(0)
        if raw == "s":
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                chosen = options[idx].get("label", str(idx + 1))
                notes_raw = input("  Optional notes (Enter to skip): ").strip()
                return chosen, notes_raw
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(options)}.")


# ── Main ───────────────────────────────────────────────────────────────────

def run_dashboard(
    config_path: Optional[Path] = None,
    tasks_path: Optional[Path] = None,
    no_input: bool = False,
    repo_root: Optional[Path] = None,
    input_fn=None,
) -> int:
    """
    Render the dashboard and handle decision resolution.

    input_fn is injected in tests to replace built-in input().
    Returns exit code.
    """
    root = repo_root or REPO_ROOT

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    state_dir = get_state_dir(config, root)
    resolved_tasks_path = tasks_path or (state_dir / "tasks.yaml")

    try:
        tasks_doc = load_tasks_doc(resolved_tasks_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(_c(_BOLD, "\nAirOS Agentic Loop — Dashboard"))

    display_current_task(tasks_doc)
    display_baseline(config)

    escalations = get_pending_escalations(state_dir)
    display_escalations(escalations)

    decisions = get_pending_decisions(state_dir)
    display_decisions(decisions)

    if not decisions:
        print()
        return 0

    interactive = input_fn is not None or sys.stdin.isatty()
    if no_input or not interactive:
        print(
            f"\n  {_c(_YELLOW, f'{len(decisions)} pending decision(s) require human input.')}",
            file=sys.stderr,
        )
        return 2

    # Interactive resolution loop
    _section("Resolve Decisions")
    _input = input_fn or input
    resolved_count = 0

    for decision in decisions:
        dec_id = decision.get("decision_id", "?")
        question = decision.get("question", "?")
        options = decision.get("options") or []

        print(f"\n  {_c(_BOLD, dec_id)}")
        print(f"  {question}")
        for i, opt in enumerate(options, start=1):
            label = opt.get("label", "?")
            effort = opt.get("effort", "")
            effort_str = f" [{effort}]" if effort else ""
            print(f"    [{i}] {label}{effort_str}")

        while True:
            raw = _input(
                f"  Choose [1–{len(options)}] or s=skip, q=quit: "
            ).strip().lower()

            if raw == "q":
                print("  Quitting.")
                sys.exit(0)
            if raw == "s":
                print(f"  Skipped: {dec_id}")
                break
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(options):
                    chosen_label = options[idx].get("label", str(idx + 1))
                    notes_raw = _input("  Optional notes (Enter to skip): ").strip()
                    resolve_decision(state_dir, decision, chosen_label, notes_raw)
                    print(f"  {_c(_GREEN, f'Resolved: {chosen_label}')}")
                    resolved_count += 1
                    break
            except ValueError:
                pass
            print(f"  Please enter a number between 1 and {len(options)}.")

    remaining = get_pending_decisions(state_dir)
    print()
    if remaining:
        print(f"  {_c(_YELLOW, f'{len(remaining)} decision(s) still pending.')}")
        return 2
    print(_c(_GREEN, "  All decisions resolved. Loop may resume."))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AirOS agentic loop dashboard")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--tasks", type=Path, default=None)
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Display only; do not prompt for decisions",
    )
    args = parser.parse_args(argv)
    return run_dashboard(
        config_path=args.config,
        tasks_path=args.tasks,
        no_input=args.no_input,
    )


if __name__ == "__main__":
    sys.exit(main())
