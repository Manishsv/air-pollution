"""
Main agentic loop — finds the next ready task, runs preflight, invokes the
implementation agent, and routes the outcome.

Usage:
    python agentic/core/loop.py [--config PATH] [--tasks PATH] [--dry-run]

Exit codes:
    0  Task completed successfully (completion record written)
    1  Preflight failed (escalation record written)
    2  No ready task found
    3  Agent invocation failed
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentic.core.config import (
    load_config,
    get_state_dir,
    get_context_files,
    get_claude_timeout,
    get_implementation_role_path,
)
from agentic.core.invoke import (
    build_implementation_prompt,
    check_dirty_tree,
    invoke_claude,
    parse_completion_record,
)
from agentic.core.state import (
    build_escalation,
    check_depends_on,
    find_next_task,
    load_tasks_doc,
    set_task_status,
    write_completion,
    write_escalation,
    IN_PROGRESS_STATUS,
    DONE_STATUS,
    BLOCKED_STATUS,
)
from agentic.core.validate import validate_tasks_file

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Preflight ──────────────────────────────────────────────────────────────

def run_preflight(
    config: dict,
    tasks_path: Path,
    tasks_doc: dict,
    task: dict,
    repo_root: Optional[Path] = None,
) -> tuple:
    """
    Run all preflight checks for a task.

    Returns (ok: bool, stop_condition: str, context: str).
    """
    root = repo_root or REPO_ROOT

    # 1. Schema validation
    errors = validate_tasks_file(tasks_path)
    if errors:
        return (
            False,
            "tasks.yaml failed schema validation",
            "Errors:\n" + "\n".join(errors),
        )

    # 2. Dirty working tree
    if check_dirty_tree(root):
        return (
            False,
            "dirty working tree before agent invocation",
            "git status --porcelain returned uncommitted changes. "
            "Commit or stash before running the loop.",
        )

    # 3. Unsatisfied depends_on
    ok, blockers = check_depends_on(tasks_doc, task)
    if not ok:
        return (
            False,
            f"unmet dependencies: {', '.join(blockers)}",
            f"Task '{task['task_id']}' requires these tasks to be done first: "
            + ", ".join(blockers),
        )

    return (True, "", "")


# ── Main loop ──────────────────────────────────────────────────────────────

def run_loop(
    config_path: Optional[Path] = None,
    tasks_path: Optional[Path] = None,
    dry_run: bool = False,
    repo_root: Optional[Path] = None,
) -> int:
    root = repo_root or REPO_ROOT

    # Load config
    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    state_dir = get_state_dir(config, root)
    state_dir.mkdir(parents=True, exist_ok=True)

    resolved_tasks_path = tasks_path or (state_dir / "tasks.yaml")

    # Load tasks
    try:
        tasks_doc = load_tasks_doc(resolved_tasks_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Find next task
    task = find_next_task(tasks_doc)
    if task is None:
        print("No ready task found. Queue is empty or all tasks are done/blocked.")
        return 2

    task_id = task["task_id"]
    print(f"Next task: {task_id}")
    print(f"  {task.get('scope_description', '').strip()}")

    # Preflight
    ok, stop_condition, context = run_preflight(
        config, resolved_tasks_path, tasks_doc, task, root
    )

    if not ok:
        print(f"PREFLIGHT FAILED: {stop_condition}", file=sys.stderr)
        escalation = build_escalation(
            task_id=task_id,
            raised_by="loop",
            stop_condition=stop_condition,
            context=context,
        )
        esc_path = write_escalation(state_dir, escalation)
        set_task_status(resolved_tasks_path, task_id, BLOCKED_STATUS)
        print(f"Escalation written to: {esc_path}", file=sys.stderr)
        return 1

    if dry_run:
        print("[dry-run] Preflight passed. Skipping agent invocation.")
        return 0

    # Mark in-progress
    set_task_status(resolved_tasks_path, task_id, IN_PROGRESS_STATUS)

    # Build prompt
    role_path = get_implementation_role_path(config, root)
    if not role_path.exists():
        print(f"ERROR: role template not found: {role_path}", file=sys.stderr)
        return 3

    context_files = get_context_files(config, task.get("type", ""), root)
    prompt = build_implementation_prompt(role_path, task, context_files)

    # Invoke agent
    timeout = get_claude_timeout(config)
    debug_path = state_dir / f"debug_agent_output_{task_id}.txt"
    print(f"Invoking implementation agent (timeout: {timeout}s)…")
    print(f"  Debug output: {debug_path}")

    try:
        output = invoke_claude(prompt, timeout=timeout, debug_output_path=debug_path)
    except FileNotFoundError:
        msg = "claude CLI not found on PATH"
        print(f"ERROR: {msg}", file=sys.stderr)
        escalation = build_escalation(
            task_id=task_id,
            raised_by="loop",
            stop_condition=msg,
            context="Install Claude Code CLI: https://claude.ai/code",
        )
        write_escalation(state_dir, escalation)
        set_task_status(resolved_tasks_path, task_id, BLOCKED_STATUS)
        return 3
    except Exception as exc:
        print(f"ERROR invoking claude: {exc}", file=sys.stderr)
        set_task_status(resolved_tasks_path, task_id, BLOCKED_STATUS)
        return 3

    # Parse completion record
    completion = parse_completion_record(output)

    if completion is None:
        print("WARNING: no task_completion record found in agent output.")
        completion = {
            "task_id": task_id,
            "files_changed": [],
            "verification_run": False,
            "notes": "completion record not found in agent output",
        }

    write_completion(state_dir, completion)
    set_task_status(resolved_tasks_path, task_id, DONE_STATUS)

    print(f"Task {task_id} complete.")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the agentic loop for one task")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument("--tasks", type=Path, default=None, help="Path to tasks.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run preflight only; do not invoke the agent",
    )
    args = parser.parse_args(argv)
    return run_loop(
        config_path=args.config,
        tasks_path=args.tasks,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
