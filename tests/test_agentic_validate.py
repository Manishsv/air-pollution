"""Tests for agentic/core/validate.py."""

import textwrap
from pathlib import Path

import pytest
import yaml

from agentic.core.validate import validate_tasks_file, main

# ── Helpers ────────────────────────────────────────────────────────────────

def _write_tasks(tmp_path: Path, tasks: list[dict]) -> Path:
    doc = {"tasks": tasks}
    p = tmp_path / "tasks.yaml"
    p.write_text(yaml.dump(doc))
    return p


VALID_TASK = {
    "task_id": "example-task",
    "type": "code_edit",
    "scope_description": "Do something concrete.",
    "allowed_files": ["some/file.py"],
    "forbidden_actions": ["modify schemas"],
    "success_criteria": ["file.py exists and passes tests"],
    "escalation_conditions": ["verification fails after two attempts"],
    "status": "ready",
}


# ── Valid task ─────────────────────────────────────────────────────────────

class TestValidTask:
    def test_single_valid_task_returns_no_errors(self, tmp_path):
        p = _write_tasks(tmp_path, [VALID_TASK])
        errors = validate_tasks_file(p)
        assert errors == []

    def test_multiple_valid_tasks(self, tmp_path):
        second = {**VALID_TASK, "task_id": "second-task"}
        p = _write_tasks(tmp_path, [VALID_TASK, second])
        errors = validate_tasks_file(p)
        assert errors == []

    def test_valid_task_with_optional_fields(self, tmp_path):
        task = {
            **VALID_TASK,
            "depends_on": [],
            "owner_agent": "qa_agent",
            "context_hint": ["docs/PROTOCOLS.md"],
            "notes": "some note",
        }
        p = _write_tasks(tmp_path, [task])
        assert validate_tasks_file(p) == []

    def test_valid_task_all_type_values(self, tmp_path):
        valid_types = ["docs_edit", "code_edit", "spec_edit", "research", "review", "verify_commit"]
        for t in valid_types:
            task = {**VALID_TASK, "task_id": f"task-{t}", "type": t}
            p = _write_tasks(tmp_path, [task])
            assert validate_tasks_file(p) == [], f"type '{t}' should be valid"

    def test_valid_task_all_status_values(self, tmp_path):
        valid_statuses = ["ready", "in_progress", "blocked", "done", "rejected", "deferred"]
        tasks = []
        for i, s in enumerate(valid_statuses):
            tasks.append({**VALID_TASK, "task_id": f"task-{i}", "status": s})
        p = _write_tasks(tmp_path, tasks)
        assert validate_tasks_file(p) == []


# ── Invalid task ───────────────────────────────────────────────────────────

class TestInvalidTask:
    def test_missing_required_field_task_id(self, tmp_path):
        task = {k: v for k, v in VALID_TASK.items() if k != "task_id"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("task_id" in e for e in errors)

    def test_missing_required_field_type(self, tmp_path):
        task = {k: v for k, v in VALID_TASK.items() if k != "type"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("type" in e for e in errors)

    def test_missing_success_criteria(self, tmp_path):
        task = {k: v for k, v in VALID_TASK.items() if k != "success_criteria"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("success_criteria" in e for e in errors)

    def test_invalid_type_enum(self, tmp_path):
        task = {**VALID_TASK, "type": "make_coffee"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("make_coffee" in e for e in errors)

    def test_invalid_status_enum(self, tmp_path):
        task = {**VALID_TASK, "status": "pending"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("pending" in e for e in errors)

    def test_invalid_owner_agent_enum(self, tmp_path):
        task = {**VALID_TASK, "owner_agent": "robot"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("robot" in e for e in errors)

    def test_scope_description_too_long(self, tmp_path):
        task = {**VALID_TASK, "scope_description": "x" * 201}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("scope_description" in e and "200" in e for e in errors)

    def test_allowed_files_not_a_list(self, tmp_path):
        task = {**VALID_TASK, "allowed_files": "some/file.py"}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("allowed_files" in e and "list" in e for e in errors)

    def test_duplicate_task_ids(self, tmp_path):
        p = _write_tasks(tmp_path, [VALID_TASK, VALID_TASK])
        errors = validate_tasks_file(p)
        assert any("duplicate" in e for e in errors)

    def test_depends_on_unknown_task_id(self, tmp_path):
        task = {**VALID_TASK, "depends_on": ["nonexistent-task"]}
        p = _write_tasks(tmp_path, [task])
        errors = validate_tasks_file(p)
        assert any("nonexistent-task" in e for e in errors)

    def test_depends_on_known_task_id_is_valid(self, tmp_path):
        task_a = {**VALID_TASK, "task_id": "task-a"}
        task_b = {**VALID_TASK, "task_id": "task-b", "depends_on": ["task-a"]}
        p = _write_tasks(tmp_path, [task_a, task_b])
        assert validate_tasks_file(p) == []


# ── File-level errors ──────────────────────────────────────────────────────

class TestFileErrors:
    def test_missing_file(self, tmp_path):
        errors = validate_tasks_file(tmp_path / "nonexistent.yaml")
        assert any("not found" in e for e in errors)

    def test_invalid_yaml(self, tmp_path):
        p = tmp_path / "tasks.yaml"
        p.write_text("tasks: [\nunclosed")
        errors = validate_tasks_file(p)
        assert any("YAML" in e for e in errors)

    def test_missing_tasks_key(self, tmp_path):
        p = tmp_path / "tasks.yaml"
        p.write_text("current_track: foo\n")
        errors = validate_tasks_file(p)
        assert any("tasks" in e for e in errors)

    def test_tasks_not_a_list(self, tmp_path):
        p = tmp_path / "tasks.yaml"
        p.write_text("tasks: not-a-list\n")
        errors = validate_tasks_file(p)
        assert any("list" in e for e in errors)


# ── CLI ────────────────────────────────────────────────────────────────────

class TestCLI:
    def test_exits_0_on_valid_tasks(self, tmp_path):
        p = _write_tasks(tmp_path, [VALID_TASK])
        result = main(["--tasks", str(p)])
        assert result == 0

    def test_exits_1_on_invalid_tasks(self, tmp_path):
        task = {k: v for k, v in VALID_TASK.items() if k != "type"}
        p = _write_tasks(tmp_path, [task])
        result = main(["--tasks", str(p)])
        assert result == 1

    def test_default_path_validates_real_tasks_yaml(self):
        # Runs against the actual project tasks.yaml — must be valid
        result = main([])
        assert result == 0
