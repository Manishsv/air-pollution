"""Build agent prompts and invoke Claude Code via CLI."""

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def build_implementation_prompt(
    role_template_path: Path,
    task: Dict[str, Any],
    context_files: Optional[List[Path]] = None,
) -> str:
    """Fill the implementation agent template with task YAML and context file contents."""
    template = role_template_path.read_text()
    task_yaml = yaml.dump(task, default_flow_style=False, sort_keys=False)
    task_id = task.get("task_id", "")

    prompt = template.replace("{{TASK_YAML}}", task_yaml).replace("{{TASK_ID}}", task_id)

    if context_files:
        sections = []
        for path in context_files:
            if path.exists():
                sections.append(f"--- {path.name} ---\n{path.read_text()}")
        if sections:
            prompt += "\n\n## Context files\n\n" + "\n\n".join(sections)

    return prompt


def invoke_claude(
    prompt: str,
    timeout: int = 600,
    claude_bin: str = "claude",
    debug_output_path: Optional[Path] = None,
) -> str:
    """
    Invoke `claude -p` (non-interactive print mode) with the prompt piped to stdin.

    --tools default ensures the agent has access to Bash, Read, Edit, Write etc.
    --output-format text gives clean text output for completion record parsing.

    Returns the raw stdout string.
    Raises subprocess.CalledProcessError on non-zero exit.
    Raises FileNotFoundError if the claude binary is not on PATH.
    """
    result = subprocess.run(
        [claude_bin, "-p", "--tools", "default", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if debug_output_path:
        debug_output_path.write_text(
            f"=== returncode: {result.returncode} ===\n"
            f"=== stdout ===\n{result.stdout}\n"
            f"=== stderr ===\n{result.stderr}\n"
        )

    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            claude_bin,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout


def check_dirty_tree(repo_root: Optional[Path] = None) -> bool:
    """Return True if the working tree has uncommitted changes, False if clean."""
    cwd = str(repo_root) if repo_root else None
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return bool(result.stdout.strip())


def parse_completion_record(agent_output: str) -> Optional[Dict[str, Any]]:
    """
    Extract the first YAML block from agent output that contains
    a 'task_completion' key.

    Returns the parsed dict or None if not found.
    """
    import re

    blocks = re.findall(r"```(?:yaml)?\s*([\s\S]*?)```", agent_output)
    for block in blocks:
        try:
            parsed = yaml.safe_load(block)
            if isinstance(parsed, dict) and "task_completion" in parsed:
                return parsed["task_completion"]
        except yaml.YAMLError:
            continue
    return None
