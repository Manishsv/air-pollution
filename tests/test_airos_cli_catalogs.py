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


def test_cli_catalogs_list_includes_known_catalogs() -> None:
    res = _run_cli("catalogs", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "administrative_units_demo_in" in out
    assert "program_catalog_demo_in" in out
    assert "reporting_periods_demo_in" in out


def test_cli_catalogs_show_known_exits_0() -> None:
    res = _run_cli("catalogs", "show", "administrative_units_demo_in")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert '"catalog_id": "administrative_units_demo_in"' in out
    assert "no pull/cache/ttl" in out.lower()


def test_cli_catalogs_show_unknown_exits_nonzero() -> None:
    res = _run_cli("catalogs", "show", "does_not_exist")
    assert res.returncode != 0

