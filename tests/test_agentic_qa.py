"""Tests for agentic/core/qa.py."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agentic.core.qa import (
    build_qa_prompt,
    get_diff_filenames,
    parse_review_record,
    run_qa,
    validate_review_record,
    write_review,
)

# ── Fixtures ───────────────────────────────────────────────────────────────

MINIMAL_TASK = {
    "task_id": "test-task",
    "type": "code_edit",
    "scope_description": "Do something.",
    "allowed_files": ["some/file.py"],
    "forbidden_actions": ["modify schemas"],
    "success_criteria": ["file.py exists", "tests pass"],
    "escalation_conditions": ["verification fails"],
    "status": "done",
    "commit": "abc1234",
}

VALID_REVIEW = {
    "review_id": "review-test-task-20260507",
    "task_id": "test-task",
    "reviewer": "qa_agent",
    "outcome": "approved",
    "timestamp": "2026-05-07T10:00:00Z",
    "checks": [
        {"criterion": "file.py exists", "result": "pass", "note": ""},
        {"criterion": "tests pass", "result": "pass", "note": ""},
    ],
    "diff_files_checked": ["some/file.py"],
    "diff_files_outside_allowed": [],
    "reason": "",
}

MINIMAL_CONFIG = {
    "project_name": "TestProject",
    "agents_dir": "agents/roles",
    "state_dir": ".agent-loop/state",
    "context": {"always_include": [], "by_task_type": {}},
    "verification": {"commands": [], "baseline": {}},
    "claude": {
        "timeout_seconds": 10,
        "implementation_agent_role": "agents/roles/implementation_agent.md",
        "qa_agent_role": "agents/roles/qa_agent.md",
    },
}


def _write_tasks(tmp_path: Path, tasks: list) -> Path:
    state_dir = tmp_path / ".agent-loop" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / "tasks.yaml"
    p.write_text(yaml.dump({"tasks": tasks}, default_flow_style=False))
    return p


def _write_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(MINIMAL_CONFIG))
    return p


def _write_qa_role(tmp_path: Path) -> Path:
    role_dir = tmp_path / "agents" / "roles"
    role_dir.mkdir(parents=True, exist_ok=True)
    role_path = role_dir / "qa_agent.md"
    role_path.write_text(
        "# QA\n\n**Task:** {{TASK_YAML}}\n\n"
        "**Diff:** {{GIT_DIFF}}\n\n"
        "**Completion:** {{COMPLETION_RECORD}}\n\n"
        "review_id: review-{{TASK_ID}}-{{DATE}}\n"
    )
    return role_path


def _setup(tmp_path: Path, task=None):
    tasks_path = _write_tasks(tmp_path, [task or MINIMAL_TASK])
    config_path = _write_config(tmp_path)
    _write_qa_role(tmp_path)
    state_dir = tmp_path / ".agent-loop" / "state"
    return config_path, tasks_path, state_dir


# ── get_diff_filenames ─────────────────────────────────────────────────────

class TestGetDiffFilenames:
    def test_extracts_filenames(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1 @@\n"
            "+hello\n"
        )
        assert get_diff_filenames(diff) == ["foo.py"]

    def test_multiple_files(self):
        diff = (
            "+++ b/a.py\n"
            "+++ b/b.py\n"
        )
        assert get_diff_filenames(diff) == ["a.py", "b.py"]

    def test_empty_diff(self):
        assert get_diff_filenames("") == []


# ── build_qa_prompt ────────────────────────────────────────────────────────

class TestBuildQaPrompt:
    def test_fills_all_placeholders(self, tmp_path):
        role = tmp_path / "qa.md"
        role.write_text(
            "Task: {{TASK_YAML}}\n"
            "Diff: {{GIT_DIFF}}\n"
            "Completion: {{COMPLETION_RECORD}}\n"
            "ID: {{TASK_ID}}\n"
        )
        prompt = build_qa_prompt(role, MINIMAL_TASK, "diff text", {"task_id": "test-task"})
        assert "test-task" in prompt
        assert "diff text" in prompt
        assert "code_edit" in prompt

    def test_handles_missing_completion_record(self, tmp_path):
        role = tmp_path / "qa.md"
        role.write_text("{{COMPLETION_RECORD}}")
        prompt = build_qa_prompt(role, MINIMAL_TASK, "", None)
        assert "no completion record" in prompt


# ── parse_review_record ────────────────────────────────────────────────────

class TestParseReviewRecord:
    def test_parses_fenced_yaml(self):
        output = f"""
Some preamble text.
```yaml
{yaml.dump(VALID_REVIEW)}
```
"""
        result = parse_review_record(output)
        assert result is not None
        assert result["outcome"] == "approved"
        assert result["task_id"] == "test-task"

    def test_parses_unfenced_yaml(self):
        output = yaml.dump(VALID_REVIEW)
        result = parse_review_record(output)
        assert result is not None
        assert result["outcome"] == "approved"

    def test_returns_none_if_not_found(self):
        assert parse_review_record("no review here") is None

    def test_skips_blocks_without_review_id(self):
        output = "```yaml\nsome_key: value\n```"
        assert parse_review_record(output) is None

    def test_parses_rejected_outcome(self):
        review = {**VALID_REVIEW, "outcome": "rejected", "reason": "criterion failed"}
        output = f"```yaml\n{yaml.dump(review)}\n```"
        result = parse_review_record(output)
        assert result["outcome"] == "rejected"

    def test_parses_needs_human_decision(self):
        review = {
            **VALID_REVIEW,
            "outcome": "needs_human_decision",
            "reason": "ambiguous criterion",
        }
        output = f"```yaml\n{yaml.dump(review)}\n```"
        result = parse_review_record(output)
        assert result["outcome"] == "needs_human_decision"


# ── validate_review_record ─────────────────────────────────────────────────

class TestValidateReviewRecord:
    def test_valid_approved_record(self):
        assert validate_review_record(VALID_REVIEW) == []

    def test_valid_rejected_with_reason(self):
        review = {
            **VALID_REVIEW,
            "outcome": "rejected",
            "reason": "criterion X failed",
            "checks": [{"criterion": "file.py exists", "result": "fail", "note": "file missing"}],
        }
        assert validate_review_record(review) == []

    def test_valid_needs_human_decision(self):
        review = {
            **VALID_REVIEW,
            "outcome": "needs_human_decision",
            "reason": "human needed",
            "checks": [{"criterion": "content accurate", "result": "skip", "note": "requires human"}],
        }
        assert validate_review_record(review) == []

    def test_missing_required_fields(self):
        errors = validate_review_record({})
        assert any("review_id" in e for e in errors)
        assert any("outcome" in e for e in errors)
        assert any("checks" in e for e in errors)

    def test_invalid_outcome(self):
        review = {**VALID_REVIEW, "outcome": "maybe"}
        errors = validate_review_record(review)
        assert any("maybe" in e for e in errors)

    def test_invalid_reviewer(self):
        review = {**VALID_REVIEW, "reviewer": "robot"}
        errors = validate_review_record(review)
        assert any("robot" in e for e in errors)

    def test_invalid_check_result(self):
        review = {
            **VALID_REVIEW,
            "checks": [{"criterion": "x", "result": "maybe"}],
        }
        errors = validate_review_record(review)
        assert any("maybe" in e for e in errors)

    def test_fail_result_requires_note(self):
        review = {
            **VALID_REVIEW,
            "checks": [{"criterion": "x", "result": "fail"}],
        }
        errors = validate_review_record(review)
        assert any("note" in e for e in errors)

    def test_skip_result_requires_note(self):
        review = {
            **VALID_REVIEW,
            "checks": [{"criterion": "x", "result": "skip"}],
        }
        errors = validate_review_record(review)
        assert any("note" in e for e in errors)

    def test_rejected_requires_reason(self):
        review = {**VALID_REVIEW, "outcome": "rejected"}
        errors = validate_review_record(review)
        assert any("reason" in e for e in errors)

    def test_needs_human_decision_requires_reason(self):
        review = {**VALID_REVIEW, "outcome": "needs_human_decision"}
        errors = validate_review_record(review)
        assert any("reason" in e for e in errors)


# ── write_review ───────────────────────────────────────────────────────────

class TestWriteReview:
    def test_creates_reviews_yaml(self, tmp_path):
        write_review(tmp_path, VALID_REVIEW)
        path = tmp_path / "reviews.yaml"
        assert path.exists()
        records = yaml.safe_load(path.read_text())
        assert records[0]["review_id"] == VALID_REVIEW["review_id"]

    def test_appends_multiple_reviews(self, tmp_path):
        r2 = {**VALID_REVIEW, "review_id": "review-test-task-20260508"}
        write_review(tmp_path, VALID_REVIEW)
        write_review(tmp_path, r2)
        records = yaml.safe_load((tmp_path / "reviews.yaml").read_text())
        assert len(records) == 2


# ── run_qa (integration) ───────────────────────────────────────────────────

class TestRunQa:
    def test_approved_outcome_writes_review(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)
        agent_output = f"```yaml\n{yaml.dump(VALID_REVIEW)}\n```"

        with patch("agentic.core.qa.invoke_claude", return_value=agent_output), \
             patch("agentic.core.qa.get_git_diff", return_value="diff text"):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 0
        assert review is not None
        assert review["outcome"] == "approved"
        records = yaml.safe_load((state_dir / "reviews.yaml").read_text())
        assert records[0]["outcome"] == "approved"

    def test_rejected_outcome_writes_review(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)
        rejected = {
            **VALID_REVIEW,
            "outcome": "rejected",
            "reason": "criterion X failed",
            "checks": [{"criterion": "file.py exists", "result": "fail", "note": "file missing"}],
        }
        agent_output = f"```yaml\n{yaml.dump(rejected)}\n```"

        with patch("agentic.core.qa.invoke_claude", return_value=agent_output), \
             patch("agentic.core.qa.get_git_diff", return_value="diff text"):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 0
        assert review["outcome"] == "rejected"
        records = yaml.safe_load((state_dir / "reviews.yaml").read_text())
        assert records[0]["outcome"] == "rejected"

    def test_needs_human_decision_outcome(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)
        nhd = {
            **VALID_REVIEW,
            "outcome": "needs_human_decision",
            "reason": "content accuracy requires human judgement",
            "checks": [
                {"criterion": "file.py exists", "result": "pass", "note": ""},
                {"criterion": "tests pass", "result": "skip", "note": "requires human review"},
            ],
        }
        agent_output = f"```yaml\n{yaml.dump(nhd)}\n```"

        with patch("agentic.core.qa.invoke_claude", return_value=agent_output), \
             patch("agentic.core.qa.get_git_diff", return_value="diff text"):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 0
        assert review["outcome"] == "needs_human_decision"

    def test_unparseable_output_returns_exit_2(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        with patch("agentic.core.qa.invoke_claude", return_value="no review here"), \
             patch("agentic.core.qa.get_git_diff", return_value=""):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 2
        assert review is None
        # Escalation should be written
        assert (state_dir / "escalations.yaml").exists()

    def test_invalid_schema_returns_exit_3(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)
        bad_review = {"review_id": "x", "outcome": "approved"}  # missing required fields
        agent_output = f"```yaml\n{yaml.dump(bad_review)}\n```"

        with patch("agentic.core.qa.invoke_claude", return_value=agent_output), \
             patch("agentic.core.qa.get_git_diff", return_value=""):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 3

    def test_unknown_task_id_returns_exit_1(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        exit_code, review = run_qa(
            task_id="nonexistent-task",
            config_path=config_path,
            tasks_path=tasks_path,
            repo_root=tmp_path,
        )
        assert exit_code == 1
        assert review is None

    def test_missing_claude_writes_escalation(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        with patch("agentic.core.qa.invoke_claude", side_effect=FileNotFoundError("claude")), \
             patch("agentic.core.qa.get_git_diff", return_value=""):
            exit_code, review = run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert exit_code == 1
        assert (state_dir / "escalations.yaml").exists()

    def test_uses_completion_record_when_present(self, tmp_path):
        config_path, tasks_path, state_dir = _setup(tmp_path)

        completions = [{"task_id": "test-task", "files_changed": ["some/file.py"], "verification_run": True}]
        (state_dir / "completions.yaml").write_text(yaml.dump(completions))

        captured_prompts = []

        def mock_invoke(prompt, **kwargs):
            captured_prompts.append(prompt)
            return f"```yaml\n{yaml.dump(VALID_REVIEW)}\n```"

        with patch("agentic.core.qa.invoke_claude", side_effect=mock_invoke), \
             patch("agentic.core.qa.get_git_diff", return_value=""):
            run_qa(
                task_id="test-task",
                config_path=config_path,
                tasks_path=tasks_path,
                repo_root=tmp_path,
            )

        assert len(captured_prompts) == 1
        assert "some/file.py" in captured_prompts[0]
