from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "tools/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
        env=merged,
    )


def test_cli_inventory_static_sections() -> None:
    res = _run_cli("inventory")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "AirOS Platform Inventory" in out
    assert "Contracts:" in out
    assert "Apps:" in out
    assert "Provider adapters:" in out
    assert "Reference catalogs:" in out
    assert "Deployments:" in out


def test_cli_inventory_include_runtime_exits_0_even_if_missing_store(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist_store_dir"
    res = _run_cli("inventory", "--include-runtime", env={"AIROS_STORE_DIR": str(missing)})
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "Runtime store:" in out or "Runtime store: unavailable" in out

