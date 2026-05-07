"""
QA agent invocation — builds a review prompt from the task, git diff, and
completion record, invokes Claude Code, parses and validates the review record,
and writes it to .agent-loop/state/reviews.yaml.

Usage:
    python agentic/core/qa.py --task-id TASK_ID [--config PATH] [--tasks PATH]

Exit codes:
    0  Review written (check outcome field for approved/rejected/needs_human_decision)
    1  Prompt build or invocation failed
    2  Review record could not be parsed from agent output
    3  Review record failed schema validation
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from agentic.core.config import (
    load_config,
    get_state_dir,
    get_claude_timeout,
)
from agentic.core.invoke import invoke_claude
from agentic.core.state import load_tasks_doc, get_task_by_id, write_escalation, build_escalation

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_OUTCOMES = {"approved", "rejected", "needs_human_decision"}
VALID_REVIEWERS = {"qa_agent", "human"}
VALID_CHECK_RESULTS = {"pass", "fail", "skip"}


# ── Git diff ───────────────────────────────────────────────────────────────

def get_git_diff(commit: Optional[str] = None, repo_root: Optional[Path] = None) -> str:
    """
    Return the git diff for the task.

    If commit is provided, diffs that commit against its parent.
    Otherwise returns the diff of staged + unstaged changes (HEAD).
    """
    cwd = str(repo_root or REPO_ROOT)
    if commit and commit not in ("", "pending"):
        cmd = ["git", "diff", f"{commit}^", commit, "--unified=3"]
    else:
        cmd = ["git", "diff", "HEAD", "--unified=3"]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.stdout or "(no diff)"


def get_diff_filenames(diff_text: str) -> List[str]:
    """Extract changed filenames from a unified diff."""
    return re.findall(r"^\+\+\+ b/(.+)$", diff_text, re.MULTILINE)


# ── Prompt ─────────────────────────────────────────────────────────────────

def build_qa_prompt(
    role_template_path: Path,
    task: Dict[str, Any],
    diff_text: str,
    completion_record: Optional[Dict[str, Any]],
) -> str:
    template = role_template_path.read_text()
    task_yaml = yaml.dump(task, default_flow_style=False, sort_keys=False)
    task_id = task.get("task_id", "")
    now = datetime.datetime.utcnow()
    date_str = now.strftime("%Y%m%d")
    timestamp = now.isoformat() + "Z"

    completion_yaml = (
        yaml.dump(completion_record, default_flow_style=False, sort_keys=False)
        if completion_record
        else "(no completion record found)"
    )

    return (
        template
        .replace("{{TASK_YAML}}", task_yaml)
        .replace("{{GIT_DIFF}}", diff_text)
        .replace("{{COMPLETION_RECORD}}", completion_yaml)
        .replace("{{TASK_ID}}", task_id)
        .replace("{{DATE}}", date_str)
        .replace("{{TIMESTAMP}}", timestamp)
    )


# ── Parse & validate review record ────────────────────────────────────────

def parse_review_record(agent_output: str) -> Optional[Dict[str, Any]]:
    """Extract the first YAML block containing a review record from agent output."""
    blocks = re.findall(r"```(?:yaml)?\s*([\s\S]*?)```", agent_output)
    for block in blocks:
        try:
            parsed = yaml.safe_load(block)
            if isinstance(parsed, dict) and "review_id" in parsed and "outcome" in parsed:
                return parsed
        except yaml.YAMLError:
            continue
    # Try parsing the entire output as YAML (agent may not use fences)
    try:
        parsed = yaml.safe_load(agent_output)
        if isinstance(parsed, dict) and "review_id" in parsed and "outcome" in parsed:
            return parsed
    except yaml.YAMLError:
        pass
    return None


def validate_review_record(record: Dict[str, Any]) -> List[str]:
    """Return list of schema errors (empty = valid)."""
    errors: List[str] = []

    for field in ("review_id", "task_id", "reviewer", "outcome", "checks", "timestamp"):
        if field not in record:
            errors.append(f"missing required field: {field}")

    outcome = record.get("outcome")
    if outcome is not None and outcome not in VALID_OUTCOMES:
        errors.append(f"invalid outcome '{outcome}'; must be one of: {', '.join(sorted(VALID_OUTCOMES))}")

    reviewer = record.get("reviewer")
    if reviewer is not None and reviewer not in VALID_REVIEWERS:
        errors.append(f"invalid reviewer '{reviewer}'")

    checks = record.get("checks")
    if checks is not None:
        if not isinstance(checks, list):
            errors.append("checks must be a list")
        else:
            for i, check in enumerate(checks):
                if not isinstance(check, dict):
                    errors.append(f"checks[{i}] must be a mapping")
                    continue
                if "criterion" not in check:
                    errors.append(f"checks[{i}] missing 'criterion'")
                result = check.get("result")
                if result is not None and result not in VALID_CHECK_RESULTS:
                    errors.append(
                        f"checks[{i}] invalid result '{result}'; "
                        f"must be one of: {', '.join(sorted(VALID_CHECK_RESULTS))}"
                    )
                if result in ("fail", "skip") and not check.get("note"):
                    errors.append(f"checks[{i}] result='{result}' requires a note")

    if outcome in ("rejected", "needs_human_decision") and not record.get("reason"):
        errors.append(f"outcome='{outcome}' requires a reason")

    return errors


# ── Write review ───────────────────────────────────────────────────────────

def write_review(state_dir: Path, review: Dict[str, Any]) -> Path:
    """Append a review record to reviews.yaml. Returns path."""
    path = state_dir / "reviews.yaml"
    existing: List[Dict[str, Any]] = []
    if path.exists():
        loaded = yaml.safe_load(path.read_text())
        if isinstance(loaded, list):
            existing = loaded
    existing.append(review)
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))
    return path


# ── Main ───────────────────────────────────────────────────────────────────

def run_qa(
    task_id: str,
    config_path: Optional[Path] = None,
    tasks_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    """
    Run the QA agent for the given task_id.

    Returns (exit_code, review_record_or_None).
    """
    root = repo_root or REPO_ROOT

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1, None

    state_dir = get_state_dir(config, root)
    resolved_tasks_path = tasks_path or (state_dir / "tasks.yaml")

    try:
        tasks_doc = load_tasks_doc(resolved_tasks_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1, None

    task = get_task_by_id(tasks_doc, task_id)
    if task is None:
        print(f"ERROR: task_id '{task_id}' not found in tasks.yaml", file=sys.stderr)
        return 1, None

    # Load completion record for this task
    completions_path = state_dir / "completions.yaml"
    completion_record = None
    if completions_path.exists():
        records = yaml.safe_load(completions_path.read_text()) or []
        for rec in reversed(records):
            if isinstance(rec, dict) and rec.get("task_id") == task_id:
                completion_record = rec
                break

    # Get git diff
    commit = task.get("commit")
    diff_text = get_git_diff(commit, root)
    diff_files = get_diff_filenames(diff_text)

    # Load QA role template
    qa_role_key = config.get("claude", {}).get("qa_agent_role", "agents/roles/qa_agent.md")
    qa_role_path = root / qa_role_key
    if not qa_role_path.exists():
        print(f"ERROR: QA role template not found: {qa_role_path}", file=sys.stderr)
        return 1, None

    # Build prompt
    prompt = build_qa_prompt(qa_role_path, task, diff_text, completion_record)

    # Invoke agent
    timeout = get_claude_timeout(config)
    print(f"Invoking QA agent for task: {task_id} (timeout: {timeout}s)…")

    try:
        output = invoke_claude(prompt, timeout=timeout)
    except FileNotFoundError:
        msg = "claude CLI not found on PATH"
        print(f"ERROR: {msg}", file=sys.stderr)
        esc = build_escalation(task_id, "qa", msg, "Install Claude Code CLI")
        write_escalation(state_dir, esc)
        return 1, None
    except Exception as exc:
        print(f"ERROR invoking claude: {exc}", file=sys.stderr)
        return 1, None

    # Parse review record
    review = parse_review_record(output)
    if review is None:
        msg = "review record not found in QA agent output"
        print(f"ERROR: {msg}", file=sys.stderr)
        esc = build_escalation(task_id, "qa", msg, output[:500])
        write_escalation(state_dir, esc)
        return 2, None

    # Validate schema
    schema_errors = validate_review_record(review)
    if schema_errors:
        print("ERROR: review record failed schema validation:", file=sys.stderr)
        for err in schema_errors:
            print(f"  {err}", file=sys.stderr)
        return 3, review

    # Write review
    review_path = write_review(state_dir, review)
    outcome = review.get("outcome")
    print(f"Review written: {review_path}")
    print(f"Outcome: {outcome}")
    return 0, review


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run QA agent for a completed task")
    parser.add_argument("--task-id", required=True, help="task_id to review")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--tasks", type=Path, default=None)
    args = parser.parse_args(argv)

    exit_code, _ = run_qa(
        task_id=args.task_id,
        config_path=args.config,
        tasks_path=args.tasks,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
