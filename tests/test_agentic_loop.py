"""Tests for agentic/core/loop.py, state.py, config.py, and invoke.py."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

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
)
from agentic.core.loop import run_loop, run_preflight

# ── Fixtures ───────────────────────────────────────────────────────────────

MINIMAL_TASK = {
    "task_id": "test-task",
    "type": "code_edit",
    "scope_description": "Do something.",
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
    "verification": {"commands": [], "baseline": {}},
    "claude": {
        "timeout_seconds": 60,
        "implementation_agent_role": "agents/roles/implementation_agent.md",
    },
}


def _write_tasks(tmp_path: Path, tasks: list) -> Path:
    p = tmp_path / "tasks.yaml"
    p.write_text(yaml.dump({"tasks": tasks}, default_flow_style=False))
    return p


def _write_config(tmp_path: Path, config: dict = None) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(config or MINIMAL_CONFIG))
    return p


def _write_role(tmp_path: Path) -> Path:
    role_dir = tmp_path / "agents" / "roles"
    role_dir.mkdir(parents=True)
    role_path = role_dir / "implementation_agent.md"
    role_path.write_text("# Agent\n\n{{TASK_YAML}}\n\n## When done\n```yaml\n{{TASK_ID}}\n```\n")
    return role_path


# ── config.py ─────────────────────────────────────────────────────────────

class TestConfig:
    def test_load_config_returns_dict(self, tmp_path):
        p = _write_config(tmp_path)
        cfg = load_config(p)
        assert cfg["project_name"] == "TestProject"

    def test_load_config_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_get_state_dir(self, tmp_path):
        cfg = {"state_dir": "custom/state"}
        d = get_state_dir(cfg, tmp_path)
        assert d == tmp_path / "custom/state"

    def test_get_context_files_always_include(self, tmp_path):
        readme = tmp_path / "docs" / "AGENTS.md"
        readme.parent.mkdir()
        readme.write_text("hi")
        cfg = {"context": {"always_include": ["docs/AGENTS.md"], "by_task_type": {}}}
        files = get_context_files(cfg, "code_edit", tmp_path)
        assert readme in files

    def test_get_context_files_by_task_type(self, tmp_path):
        spec = tmp_path / "specifications" / "manifest.json"
        spec.parent.mkdir()
        spec.write_text("{}")
        cfg = {
            "context": {
                "always_include": [],
                "by_task_type": {"code_edit": ["specifications/manifest.json"]},
            }
        }
        files = get_context_files(cfg, "code_edit", tmp_path)
        assert spec in files

    def test_get_claude_timeout_default(self):
        assert get_claude_timeout({}) == 600

    def test_get_claude_timeout_custom(self):
        assert get_claude_timeout({"claude": {"timeout_seconds": 30}}) == 30


# ── state.py ──────────────────────────────────────────────────────────────

class TestState:
    def test_load_tasks_doc(self, tmp_path):
        p = _write_tasks(tmp_path, [MINIMAL_TASK])
        doc = load_tasks_doc(p)
        assert len(doc["tasks"]) == 1

    def test_load_tasks_doc_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_tasks_doc(tmp_path / "nope.yaml")

    def test_find_next_task_returns_first_ready(self, tmp_path):
        done = {**MINIMAL_TASK, "task_id": "done-task", "status": "done"}
        ready = {**MINIMAL_TASK, "task_id": "ready-task", "status": "ready"}
        doc = {"tasks": [done, ready]}
        task = find_next_task(doc)
        assert task["task_id"] == "ready-task"

    def test_find_next_task_none_when_empty(self):
        assert find_next_task({"tasks": []}) is None

    def test_find_next_task_none_when_all_done(self):
        doc = {"tasks": [{**MINIMAL_TASK, "status": "done"}]}
        assert find_next_task(doc) is None

    def test_check_depends_on_satisfied(self):
        dep = {**MINIMAL_TASK, "task_id": "dep-task", "status": "done"}
        task = {**MINIMAL_TASK, "depends_on": ["dep-task"]}
        doc = {"tasks": [dep, task]}
        ok, blockers = check_depends_on(doc, task)
        assert ok
        assert blockers == []

    def test_check_depends_on_unsatisfied(self):
        dep = {**MINIMAL_TASK, "task_id": "dep-task", "status": "ready"}
        task = {**MINIMAL_TASK, "depends_on": ["dep-task"]}
        doc = {"tasks": [dep, task]}
        ok, blockers = check_depends_on(doc, task)
        assert not ok
        assert "dep-task" in blockers

    def test_set_task_status(self, tmp_path):
        p = _write_tasks(tmp_path, [MINIMAL_TASK])
        set_task_status(p, "test-task", "in_progress")
        doc = load_tasks_doc(p)
        assert doc["tasks"][0]["status"] == "in_progress"

    def test_write_escalation_creates_file(self, tmp_path):
        esc = build_escalation("t1", "loop", "dirty tree", "context text")
        write_escalation(tmp_path, esc)
        path = tmp_path / "escalations.yaml"
        assert path.exists()
        records = yaml.safe_load(path.read_text())
        assert records[0]["task_id"] == "t1"

    def test_write_escalation_appends(self, tmp_path):
        esc1 = build_escalation("t1", "loop", "reason1", "ctx")
        esc2 = build_escalation("t2", "loop", "reason2", "ctx")
        write_escalation(tmp_path, esc1)
        write_escalation(tmp_path, esc2)
        records = yaml.safe_load((tmp_path / "escalations.yaml").read_text())
        assert len(records) == 2

    def test_write_completion(self, tmp_path):
        record = {"task_id": "t1", "files_changed": ["a.py"], "verification_run": True}
        write_completion(tmp_path, record)
        loaded = yaml.safe_load((tmp_path / "completions.yaml").read_text())
        assert loaded[0]["task_id"] == "t1"


# ── invoke.py ─────────────────────────────────────────────────────────────

class TestInvoke:
    def test_build_prompt_fills_task_yaml(self, tmp_path):
        role = tmp_path / "role.md"
        role.write_text("# Agent\n{{TASK_YAML}}\n## End\n{{TASK_ID}}")
        prompt = build_implementation_prompt(role, MINIMAL_TASK)
        assert "test-task" in prompt
        assert "code_edit" in prompt

    def test_build_prompt_appends_context_files(self, tmp_path):
        role = tmp_path / "role.md"
        role.write_text("{{TASK_YAML}}{{TASK_ID}}")
        ctx = tmp_path / "ctx.md"
        ctx.write_text("important context")
        prompt = build_implementation_prompt(role, MINIMAL_TASK, [ctx])
        assert "important context" in prompt

    def test_build_prompt_skips_missing_context(self, tmp_path):
        role = tmp_path / "role.md"
        role.write_text("{{TASK_YAML}}{{TASK_ID}}")
        missing = tmp_path / "does_not_exist.md"
        prompt = build_implementation_prompt(role, MINIMAL_TASK, [missing])
        assert "does_not_exist" not in prompt

    def test_check_dirty_tree_clean(self, tmp_path):
        with patch("agentic.core.invoke.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            assert check_dirty_tree(tmp_path) is False

    def test_check_dirty_tree_dirty(self, tmp_path):
        with patch("agentic.core.invoke.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=" M some/file.py\n", returncode=0)
            assert check_dirty_tree(tmp_path) is True

    def test_parse_completion_record_found(self):
        output = """
Some text before.
```yaml
task_completion:
  task_id: test-task
  files_changed:
    - a.py
  verification_run: true
```
Some text after.
"""
        result = parse_completion_record(output)
        assert result is not None
        assert result["task_id"] == "test-task"
        assert result["verification_run"] is True

    def test_parse_completion_record_not_found(self):
        assert parse_completion_record("no yaml blocks here") is None

    def test_parse_completion_record_wrong_key(self):
        output = "```yaml\nsome_other_key: value\n```"
        assert parse_completion_record(output) is None


# ── loop.py ───────────────────────────────────────────────────────────────

class TestLoop:
    def _setup(self, tmp_path, task=None, extra_tasks=None):
        """Create config, tasks, role template, and state dir under tmp_path."""
        tasks = [task or MINIMAL_TASK] + (extra_tasks or [])
        tasks_path = _write_tasks(tmp_path, tasks)

        state_dir = tmp_path / ".agent-loop" / "state"
        state_dir.mkdir(parents=True)

        config = {
            **MINIMAL_CONFIG,
            "state_dir": str(state_dir.relative_to(tmp_path)),
            "claude": {
                "timeout_seconds": 10,
                "implementation_agent_role": "agents/roles/implementation_agent.md",
            },
        }
        config_path = _write_config(tmp_path, config)
        role_path = _write_role(tmp_path)

        return config_path, tasks_path, state_dir, role_path

    # Preflight: clean tree, no deps → passes

    def test_preflight_passes_clean_tree_no_deps(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)
        config = load_config(config_path)
        tasks_doc = load_tasks_doc(tasks_path)
        task = find_next_task(tasks_doc)

        with patch("agentic.core.loop.check_dirty_tree", return_value=False):
            ok, stop, ctx = run_preflight(config, tasks_path, tasks_doc, task, tmp_path)

        assert ok is True
        assert stop == ""

    # Preflight: dirty tree → fails and writes escalation

    def test_preflight_fails_dirty_tree(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)
        config = load_config(config_path)
        tasks_doc = load_tasks_doc(tasks_path)
        task = find_next_task(tasks_doc)

        with patch("agentic.core.loop.check_dirty_tree", return_value=True):
            ok, stop, ctx = run_preflight(config, tasks_path, tasks_doc, task, tmp_path)

        assert ok is False
        assert "dirty" in stop

    def test_run_loop_dirty_tree_writes_escalation(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)

        with patch("agentic.core.loop.check_dirty_tree", return_value=True):
            result = run_loop(
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert result == 1
        esc_file = state_dir / "escalations.yaml"
        assert esc_file.exists()
        records = yaml.safe_load(esc_file.read_text())
        assert any("dirty" in r.get("stop_condition", "") for r in records)

    # Preflight: unsatisfied depends_on → fails

    def test_preflight_fails_unmet_dependency(self, tmp_path):
        task_with_dep = {**MINIMAL_TASK, "depends_on": ["unfinished-task"]}
        other = {**MINIMAL_TASK, "task_id": "unfinished-task", "status": "ready"}
        config_path, tasks_path, state_dir, _ = self._setup(
            tmp_path, task=task_with_dep, extra_tasks=[other]
        )
        config = load_config(config_path)
        tasks_doc = load_tasks_doc(tasks_path)
        task = find_next_task(tasks_doc)

        with patch("agentic.core.loop.check_dirty_tree", return_value=False):
            ok, stop, ctx = run_preflight(config, tasks_path, tasks_doc, task, tmp_path)

        assert ok is False
        assert "unfinished-task" in stop

    # No ready task → exit 2

    def test_run_loop_no_ready_task(self, tmp_path):
        done_task = {**MINIMAL_TASK, "status": "done"}
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path, task=done_task)

        result = run_loop(
            config_path=config_path,
            tasks_path=tasks_path,
            repo_root=tmp_path,
        )
        assert result == 2

    # Dry run: preflight passes, agent not invoked

    def test_run_loop_dry_run_no_invocation(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)

        with patch("agentic.core.loop.check_dirty_tree", return_value=False), \
             patch("agentic.core.loop.invoke_claude") as mock_invoke:
            result = run_loop(
                config_path=config_path,
                tasks_path=tasks_path,
                dry_run=True,
                repo_root=tmp_path,
            )

        assert result == 0
        mock_invoke.assert_not_called()

    # Successful agent invocation → completion record written, task marked done

    def test_run_loop_success_writes_completion(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)

        agent_output = """
Done!
```yaml
task_completion:
  task_id: test-task
  files_changed:
    - some/file.py
  verification_run: true
  notes: ""
```
"""
        with patch("agentic.core.loop.check_dirty_tree", return_value=False), \
             patch("agentic.core.loop.invoke_claude", return_value=agent_output):
            result = run_loop(
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert result == 0
        completions_file = state_dir / "completions.yaml"
        assert completions_file.exists()
        records = yaml.safe_load(completions_file.read_text())
        assert records[0]["task_id"] == "test-task"

        doc = load_tasks_doc(tasks_path)
        task = doc["tasks"][0]
        assert task["status"] == "done"

    # Missing claude binary → escalation written, exit 3

    def test_run_loop_missing_claude_writes_escalation(self, tmp_path):
        config_path, tasks_path, state_dir, _ = self._setup(tmp_path)

        with patch("agentic.core.loop.check_dirty_tree", return_value=False), \
             patch("agentic.core.loop.invoke_claude", side_effect=FileNotFoundError("claude not found")):
            result = run_loop(
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert result == 3
        esc_file = state_dir / "escalations.yaml"
        assert esc_file.exists()
