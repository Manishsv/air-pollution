"""Load and expose the project config from .agent-loop/config.yaml."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / ".agent-loop" / "config.yaml"


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return yaml.safe_load(path.read_text()) or {}


def get_state_dir(config: Dict[str, Any], repo_root: Optional[Path] = None) -> Path:
    root = repo_root or REPO_ROOT
    return root / config.get("state_dir", ".agent-loop/state")


def get_agents_dir(config: Dict[str, Any], repo_root: Optional[Path] = None) -> Path:
    root = repo_root or REPO_ROOT
    return root / config.get("agents_dir", "agents/roles")


def get_context_files(
    config: Dict[str, Any],
    task_type: str,
    repo_root: Optional[Path] = None,
) -> List[Path]:
    root = repo_root or REPO_ROOT
    ctx = config.get("context", {})
    paths = list(ctx.get("always_include", []))
    paths += ctx.get("by_task_type", {}).get(task_type, [])
    return [root / p for p in paths]


def get_verification_commands(config: Dict[str, Any]) -> List[str]:
    return config.get("verification", {}).get("commands", [])


def get_claude_timeout(config: Dict[str, Any]) -> int:
    return config.get("claude", {}).get("timeout_seconds", 600)


def get_implementation_role_path(
    config: Dict[str, Any], repo_root: Optional[Path] = None
) -> Path:
    root = repo_root or REPO_ROOT
    rel = config.get("claude", {}).get(
        "implementation_agent_role", "agents/roles/implementation_agent.md"
    )
    return root / rel
