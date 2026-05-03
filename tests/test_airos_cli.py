from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tools.airos_cli as cli


REPO_ROOT = Path(__file__).resolve().parents[1]


class _DummyProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_conformance_command_construction(monkeypatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append((list(argv), str(cwd)))
        return _DummyProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    plan = cli._plan_conformance(REPO_ROOT)
    rc = cli._run(plan)
    assert rc == 0
    assert calls[0][0] == [sys.executable, "main.py", "--step", "conformance"]


def test_review_run_conformance_flag(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        return _DummyProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cli.main(["review", "--run-conformance"])
    assert rc == 0
    assert calls
    assert calls[0][0] == sys.executable
    assert "tools/ai_dev_supervisor/run_review.py" in calls[0]
    assert "--run-conformance" in calls[0]


def test_domain_review_command_construction(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        return _DummyProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cli.main(["domain", "review", "air_quality", "--run-conformance"])
    assert rc == 0
    assert ["--domain", "air_quality"] != []  # sanity check for test readability
    assert "--domain" in calls[0]
    i = calls[0].index("--domain")
    assert calls[0][i + 1] == "air_quality"
    assert "--run-conformance" in calls[0]


def test_deployment_validate_command_construction(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        return _DummyProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cli.main(["deployment", "validate", "deployments/examples/flood_local_demo"])
    assert rc == 0
    assert "tools/deployment_runner/validate_deployment.py" in calls[0]
    assert "--deployment" in calls[0]


def test_deployment_run_command_construction(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, cwd=None, **_kwargs):
        calls.append(list(argv))
        return _DummyProc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    rc = cli.main(["deployment", "run", "deployments/examples/flood_local_demo"])
    assert rc == 0
    assert "tools/deployment_runner/run_deployment.py" in calls[0]
    assert "--deployment" in calls[0]


def test_parse_csv() -> None:
    assert cli._parse_csv("a,b, c,,") == ["a", "b", "c"]

