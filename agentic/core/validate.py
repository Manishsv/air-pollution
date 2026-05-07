"""
Validate .agent-loop/state/tasks.yaml against agentic/schemas/task.schema.yaml.

Usage:
    python agentic/core/validate.py [--tasks PATH] [--config PATH]

Exit 0: all tasks valid.
Exit 1: one or more tasks have validation errors (reasons printed to stderr).
"""

import argparse
import sys
from pathlib import Path
from typing import Any, List, Optional

import yaml

# ── Constants ──────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_TYPES = {
    "docs_edit", "code_edit", "spec_edit",
    "research", "review", "verify_commit",
}

VALID_STATUSES = {
    "ready", "in_progress", "blocked", "done", "rejected", "deferred",
}

VALID_OWNER_AGENTS = {"implementation_agent", "qa_agent"}

REQUIRED_FIELDS = [
    "task_id",
    "type",
    "scope_description",
    "allowed_files",
    "forbidden_actions",
    "success_criteria",
    "escalation_conditions",
]

REQUIRED_LIST_FIELDS = [
    "allowed_files",
    "forbidden_actions",
    "success_criteria",
    "escalation_conditions",
]

# ── Validation logic ───────────────────────────────────────────────────────

def _validate_task(task: Any, index: int) -> List[str]:
    """Return a list of error strings for a single task dict."""
    errors: List[str] = []
    task_id = task.get("task_id", f"<task[{index}]>")
    prefix = f"[{task_id}]"

    for field in REQUIRED_FIELDS:
        if field not in task:
            errors.append(f"{prefix} missing required field: {field}")

    raw_type = task.get("type")
    if raw_type is not None and raw_type not in VALID_TYPES:
        errors.append(
            f"{prefix} invalid type '{raw_type}'; "
            f"must be one of: {', '.join(sorted(VALID_TYPES))}"
        )

    scope = task.get("scope_description", "")
    if isinstance(scope, str) and len(scope) > 200:
        errors.append(
            f"{prefix} scope_description exceeds 200 characters ({len(scope)} chars)"
        )

    for field in REQUIRED_LIST_FIELDS:
        value = task.get(field)
        if value is not None and not isinstance(value, list):
            errors.append(f"{prefix} {field} must be a list")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    errors.append(f"{prefix} {field}[{i}] must be a string")

    status = task.get("status")
    if status is not None and status not in VALID_STATUSES:
        errors.append(
            f"{prefix} invalid status '{status}'; "
            f"must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )

    owner = task.get("owner_agent")
    if owner is not None and owner not in VALID_OWNER_AGENTS:
        errors.append(
            f"{prefix} invalid owner_agent '{owner}'; "
            f"must be one of: {', '.join(sorted(VALID_OWNER_AGENTS))}"
        )

    depends_on = task.get("depends_on")
    if depends_on is not None and not isinstance(depends_on, list):
        errors.append(f"{prefix} depends_on must be a list")

    context_hint = task.get("context_hint")
    if context_hint is not None and not isinstance(context_hint, list):
        errors.append(f"{prefix} context_hint must be a list")

    return errors


def validate_tasks_file(tasks_path: Path) -> List[str]:
    """Validate a tasks.yaml file. Returns list of all errors (empty = valid)."""
    if not tasks_path.exists():
        return [f"tasks file not found: {tasks_path}"]

    try:
        doc = yaml.safe_load(tasks_path.read_text())
    except yaml.YAMLError as exc:
        return [f"tasks file is not valid YAML: {exc}"]

    if not isinstance(doc, dict):
        return ["tasks file must be a YAML mapping at the top level"]

    tasks = doc.get("tasks")
    if tasks is None:
        return ["tasks file missing top-level 'tasks' key"]
    if not isinstance(tasks, list):
        return ["'tasks' must be a list"]

    errors: List[str] = []

    # Check for duplicate task_ids
    seen_ids = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"[task[{i}]] must be a mapping, got {type(task).__name__}")
            continue
        tid = task.get("task_id")
        if tid in seen_ids:
            errors.append(f"duplicate task_id: '{tid}'")
        elif tid:
            seen_ids.add(tid)
        errors.extend(_validate_task(task, i))

    # Verify depends_on references exist
    all_ids = {t.get("task_id") for t in tasks if isinstance(t, dict) and t.get("task_id")}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for dep in task.get("depends_on") or []:
            if dep not in all_ids:
                errors.append(
                    f"[{task.get('task_id', '?')}] depends_on unknown task_id: '{dep}'"
                )

    return errors


# ── CLI entry point ────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate agentic tasks.yaml")
    parser.add_argument(
        "--tasks",
        type=Path,
        default=REPO_ROOT / ".agent-loop" / "state" / "tasks.yaml",
        help="Path to tasks.yaml (default: .agent-loop/state/tasks.yaml)",
    )
    args = parser.parse_args(argv)

    errors = validate_tasks_file(args.tasks)

    if errors:
        print(f"Validation failed: {len(errors)} error(s)", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    task_count = _count_tasks(args.tasks)
    print(f"OK — {task_count} task(s) valid")
    return 0


def _count_tasks(tasks_path: Path) -> int:
    try:
        doc = yaml.safe_load(tasks_path.read_text())
        return len(doc.get("tasks", []))
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
