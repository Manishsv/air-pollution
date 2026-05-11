from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_examples_list_includes_known_examples() -> None:
    res = _run_cli("examples", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "flood_local_demo" in out
    assert "program_reporting_state_demo" in out


def test_examples_describe_works_for_flood() -> None:
    res = _run_cli("examples", "describe", "flood_local_demo")
    assert res.returncode == 0
    out = res.stdout or ""
    assert "deployment_id: flood_local_demo" in out
    assert "enabled_domains:" in out
    assert "provider_count:" in out
    assert "application_count:" in out
    assert "Recommended commands:" in out
    assert "deployment validate deployments/examples/flood_local_demo" in out


def test_examples_describe_works_for_program_reporting() -> None:
    res = _run_cli("examples", "describe", "program_reporting_state_demo")
    assert res.returncode == 0
    out = res.stdout or ""
    assert "deployment_id: program_reporting_state_demo" in out
    assert "enabled_domains:" in out
    assert "Recommended commands:" in out
    assert "deployment validate deployments/examples/program_reporting_state_demo" in out


def test_examples_describe_missing_example_gives_clear_error() -> None:
    res = _run_cli("examples", "describe", "does_not_exist")
    assert res.returncode != 0
    err = (res.stderr or "") + (res.stdout or "")
    assert "Example not found: deployments/examples/does_not_exist" in err
    assert "examples list" in err

