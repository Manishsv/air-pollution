"""Read and write the agentic loop's state files (tasks, escalations, completions)."""

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

READY_STATUS = "ready"
IN_PROGRESS_STATUS = "in_progress"
DONE_STATUS = "done"
BLOCKED_STATUS = "blocked"


# ── Tasks ──────────────────────────────────────────────────────────────────

def load_tasks_doc(tasks_path: Path) -> Dict[str, Any]:
    if not tasks_path.exists():
        raise FileNotFoundError(f"Tasks file not found: {tasks_path}")
    return yaml.safe_load(tasks_path.read_text()) or {}


def find_next_task(tasks_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first task with status 'ready', or None."""
    for task in tasks_doc.get("tasks", []):
        if task.get("status") == READY_STATUS:
            return task
    return None


def get_task_by_id(tasks_doc: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for task in tasks_doc.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def check_depends_on(tasks_doc: Dict[str, Any], task: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (ok, list_of_blocking_task_ids)."""
    blockers = []
    for dep_id in task.get("depends_on") or []:
        dep = get_task_by_id(tasks_doc, dep_id)
        if dep is None or dep.get("status") != DONE_STATUS:
            blockers.append(dep_id)
    return (len(blockers) == 0, blockers)


def set_task_status(tasks_path: Path, task_id: str, status: str, **extra: Any) -> None:
    """Update a task's status in-place and optionally set extra fields."""
    doc = load_tasks_doc(tasks_path)
    for task in doc.get("tasks", []):
        if task.get("task_id") == task_id:
            task["status"] = status
            task.update(extra)
            break
    tasks_path.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False))


# ── Escalations ────────────────────────────────────────────────────────────

def write_escalation(state_dir: Path, escalation: Dict[str, Any]) -> Path:
    """Append an escalation record to escalations.yaml. Returns path."""
    path = state_dir / "escalations.yaml"
    existing: List[Dict[str, Any]] = []
    if path.exists():
        loaded = yaml.safe_load(path.read_text())
        if isinstance(loaded, list):
            existing = loaded
    existing.append(escalation)
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    return path


def build_escalation(
    task_id: str,
    raised_by: str,
    stop_condition: str,
    context: str,
    recommendation: str = "",
) -> Dict[str, Any]:
    now = datetime.datetime.utcnow().strftime("%Y%m%d")
    return {
        "escalation_id": f"escalation-{task_id}-{now}",
        "task_id": task_id,
        "raised_by": raised_by,
        "stop_condition": stop_condition,
        "context": context,
        "options": [],
        "recommendation": recommendation,
        "status": "pending_human_decision",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


# ── Completions ────────────────────────────────────────────────────────────

def write_completion(state_dir: Path, record: Dict[str, Any]) -> Path:
    """Append a task completion record to completions.yaml. Returns path."""
    path = state_dir / "completions.yaml"
    existing: List[Dict[str, Any]] = []
    if path.exists():
        loaded = yaml.safe_load(path.read_text())
        if isinstance(loaded, list):
            existing = loaded
    existing.append(record)
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    return path
