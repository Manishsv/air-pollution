"""Tests for agentic/core/dashboard.py."""

import io
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agentic.core.dashboard import (
    display_current_task,
    display_decisions,
    display_escalations,
    get_pending_decisions,
    get_pending_escalations,
    load_yaml_list,
    resolve_decision,
    run_dashboard,
    save_yaml_list,
)

# ── Fixtures ───────────────────────────────────────────────────────────────

MINIMAL_TASK = {
    "task_id": "test-task",
    "type": "code_edit",
    "scope_description": "Do something concrete.",
    "allowed_files": ["some/file.py"],
    "forbidden_actions": ["modify schemas"],
    "success_criteria": ["file.py exists"],
    "escalation_conditions": ["verification fails"],
    "status": "ready",
}

MINIMAL_CONFIG = {
    "project_name": "TestProject",
    "agents_dir": "agents/roles",
    "state_dir": ".agent-loop/state",
    "context": {"always_include": [], "by_task_type": {}},
    "verification": {
        "commands": [],
        "baseline": {"pytest_passed": 403, "conformance_checks": 148, "supervisor_exit_code": 0},
    },
    "claude": {"timeout_seconds": 10, "implementation_agent_role": "agents/roles/impl.md"},
}

SAMPLE_DECISION = {
    "decision_id": "dec-track-20260507",
    "question": "Which track should follow the SDK use case?",
    "status": "pending",
    "options": [
        {"label": "Option A", "consequence": "Do A", "effort": "small"},
        {"label": "Option B", "consequence": "Do B", "effort": "large"},
    ],
    "recommendation": "Option A is simpler.",
}

SAMPLE_ESCALATION = {
    "escalation_id": "escalation-test-task-20260507",
    "task_id": "test-task",
    "raised_by": "loop",
    "stop_condition": "dirty working tree",
    "context": "Uncommitted changes detected.",
    "options": [],
    "recommendation": "Commit or stash changes.",
    "status": "pending_human_decision",
}


def _setup(tmp_path: Path, tasks=None, decisions=None, escalations=None):
    state_dir = tmp_path / ".agent-loop" / "state"
    state_dir.mkdir(parents=True)

    tasks_path = state_dir / "tasks.yaml"
    tasks_path.write_text(
        yaml.dump({"tasks": tasks or [MINIMAL_TASK]}, default_flow_style=False)
    )

    if decisions is not None:
        (state_dir / "decisions.yaml").write_text(
            yaml.dump(decisions, default_flow_style=False)
        )

    if escalations is not None:
        (state_dir / "escalations.yaml").write_text(
            yaml.dump(escalations, default_flow_style=False)
        )

    config = {
        **MINIMAL_CONFIG,
        "state_dir": str(state_dir.relative_to(tmp_path)),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config))

    return config_path, tasks_path, state_dir


# ── load/save helpers ──────────────────────────────────────────────────────

class TestLoadSave:
    def test_load_yaml_list_missing_file(self, tmp_path):
        assert load_yaml_list(tmp_path / "nope.yaml") == []

    def test_load_yaml_list_empty_file(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        assert load_yaml_list(p) == []

    def test_load_yaml_list_returns_list(self, tmp_path):
        p = tmp_path / "data.yaml"
        p.write_text(yaml.dump([{"a": 1}]))
        assert load_yaml_list(p) == [{"a": 1}]

    def test_save_and_reload(self, tmp_path):
        p = tmp_path / "data.yaml"
        save_yaml_list(p, [{"x": 2}])
        assert load_yaml_list(p) == [{"x": 2}]


# ── get pending items ──────────────────────────────────────────────────────

class TestGetPending:
    def test_get_pending_decisions_filters_by_status(self, tmp_path):
        state_dir = tmp_path
        decisions = [
            {**SAMPLE_DECISION, "status": "pending"},
            {**SAMPLE_DECISION, "decision_id": "dec-b", "status": "resolved"},
        ]
        (state_dir / "decisions.yaml").write_text(yaml.dump(decisions))
        pending = get_pending_decisions(state_dir)
        assert len(pending) == 1
        assert pending[0]["decision_id"] == SAMPLE_DECISION["decision_id"]

    def test_get_pending_escalations_filters_by_status(self, tmp_path):
        state_dir = tmp_path
        escs = [
            {**SAMPLE_ESCALATION, "status": "pending_human_decision"},
            {**SAMPLE_ESCALATION, "escalation_id": "esc-b", "status": "resolved"},
        ]
        (state_dir / "escalations.yaml").write_text(yaml.dump(escs))
        pending = get_pending_escalations(state_dir)
        assert len(pending) == 1

    def test_get_pending_decisions_no_file(self, tmp_path):
        assert get_pending_decisions(tmp_path) == []

    def test_get_pending_escalations_no_file(self, tmp_path):
        assert get_pending_escalations(tmp_path) == []


# ── display functions ──────────────────────────────────────────────────────

class TestDisplay:
    def test_display_current_task_ready(self, capsys):
        tasks_doc = {"tasks": [MINIMAL_TASK]}
        display_current_task(tasks_doc)
        out = capsys.readouterr().out
        assert "test-task" in out
        assert "code_edit" in out

    def test_display_current_task_none_ready(self, capsys):
        done_task = {**MINIMAL_TASK, "status": "done"}
        tasks_doc = {"tasks": [done_task]}
        display_current_task(tasks_doc)
        out = capsys.readouterr().out
        assert "No pending tasks" in out

    def test_display_escalations_empty(self, capsys):
        display_escalations([])
        out = capsys.readouterr().out
        assert "None" in out

    def test_display_escalations_shows_details(self, capsys):
        display_escalations([SAMPLE_ESCALATION])
        out = capsys.readouterr().out
        assert SAMPLE_ESCALATION["escalation_id"] in out
        assert "dirty working tree" in out

    def test_display_decisions_empty(self, capsys):
        display_decisions([])
        out = capsys.readouterr().out
        assert "None" in out

    def test_display_decisions_shows_options(self, capsys):
        display_decisions([SAMPLE_DECISION])
        out = capsys.readouterr().out
        assert "Option A" in out
        assert "Option B" in out
        assert SAMPLE_DECISION["question"] in out


# ── resolve_decision ───────────────────────────────────────────────────────

class TestResolveDecision:
    def test_writes_chosen_option_and_timestamp(self, tmp_path):
        decisions = [SAMPLE_DECISION.copy()]
        (tmp_path / "decisions.yaml").write_text(yaml.dump(decisions))

        resolve_decision(tmp_path, SAMPLE_DECISION, "Option A", notes="test note")

        updated = load_yaml_list(tmp_path / "decisions.yaml")
        assert updated[0]["status"] == "resolved"
        assert updated[0]["chosen_option"] == "Option A"
        assert "resolved_at" in updated[0]
        assert updated[0]["notes"] == "test note"

    def test_resolve_without_notes(self, tmp_path):
        decisions = [SAMPLE_DECISION.copy()]
        (tmp_path / "decisions.yaml").write_text(yaml.dump(decisions))

        resolve_decision(tmp_path, SAMPLE_DECISION, "Option B")

        updated = load_yaml_list(tmp_path / "decisions.yaml")
        assert updated[0]["chosen_option"] == "Option B"
        assert "notes" not in updated[0]

    def test_other_decisions_untouched(self, tmp_path):
        dec2 = {**SAMPLE_DECISION, "decision_id": "dec-other", "status": "pending"}
        decisions = [SAMPLE_DECISION.copy(), dec2]
        (tmp_path / "decisions.yaml").write_text(yaml.dump(decisions))

        resolve_decision(tmp_path, SAMPLE_DECISION, "Option A")

        updated = load_yaml_list(tmp_path / "decisions.yaml")
        other = next(d for d in updated if d["decision_id"] == "dec-other")
        assert other["status"] == "pending"


# ── run_dashboard ──────────────────────────────────────────────────────────

class TestRunDashboard:
    def test_no_decisions_returns_0(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        result = run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=True,
            repo_root=tmp_path,
        )
        assert result == 0

    def test_pending_decisions_no_input_returns_2(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(
            tmp_path, decisions=[SAMPLE_DECISION]
        )

        result = run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=True,
            repo_root=tmp_path,
        )
        assert result == 2

    def test_pending_escalations_shown(self, tmp_path, capsys):
        config_path, tasks_path, state_dir = _setup(
            tmp_path, escalations=[SAMPLE_ESCALATION]
        )

        run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=True,
            repo_root=tmp_path,
        )
        out = capsys.readouterr().out
        assert SAMPLE_ESCALATION["escalation_id"] in out

    def test_interactive_resolves_decision(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(
            tmp_path, decisions=[SAMPLE_DECISION.copy()]
        )
        # User types "1" to pick Option A, then empty notes
        inputs = iter(["1", ""])

        result = run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=False,
            repo_root=tmp_path,
            input_fn=lambda _: next(inputs),
        )

        assert result == 0
        updated = load_yaml_list(state_dir / "decisions.yaml")
        assert updated[0]["status"] == "resolved"
        assert updated[0]["chosen_option"] == "Option A"

    def test_interactive_skip_leaves_pending(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(
            tmp_path, decisions=[SAMPLE_DECISION.copy()]
        )
        inputs = iter(["s"])

        result = run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=False,
            repo_root=tmp_path,
            input_fn=lambda _: next(inputs),
        )

        assert result == 2
        updated = load_yaml_list(state_dir / "decisions.yaml")
        assert updated[0]["status"] == "pending"

    def test_interactive_invalid_then_valid_choice(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(
            tmp_path, decisions=[SAMPLE_DECISION.copy()]
        )
        inputs = iter(["x", "99", "2", "my note"])

        result = run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=False,
            repo_root=tmp_path,
            input_fn=lambda _: next(inputs),
        )

        assert result == 0
        updated = load_yaml_list(state_dir / "decisions.yaml")
        assert updated[0]["chosen_option"] == "Option B"
        assert updated[0]["notes"] == "my note"

    def test_baseline_shown_in_output(self, tmp_path, capsys):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=True,
            repo_root=tmp_path,
        )
        out = capsys.readouterr().out
        assert "403" in out
        assert "148" in out

    def test_missing_config_returns_1(self, tmp_path):
        result = run_dashboard(
            config_path=tmp_path / "nope.yaml",
            tasks_path=tmp_path / "nope2.yaml",
            no_input=True,
            repo_root=tmp_path,
        )
        assert result == 1

    def test_all_tasks_done_shows_no_pending(self, tmp_path, capsys):
        done_task = {**MINIMAL_TASK, "status": "done"}
        config_path, tasks_path, state_dir = _setup(tmp_path, tasks=[done_task])

        run_dashboard(
            config_path=config_path,
            tasks_path=tasks_path,
            no_input=True,
            repo_root=tmp_path,
        )
        out = capsys.readouterr().out
        assert "No pending tasks" in out
