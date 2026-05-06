from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_deployments_list_alias_works() -> None:
    res = _run_cli("deployments", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "flood_local_demo" in out
    assert "program_reporting_state_demo" in out


def test_cli_deployments_show_alias_works() -> None:
    res = _run_cli("deployments", "show", "flood_local_demo")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "deployment_id: flood_local_demo" in out
    assert "Recommended commands:" in out


def test_cli_examples_still_work() -> None:
    res = _run_cli("examples", "list")
    assert res.returncode == 0

