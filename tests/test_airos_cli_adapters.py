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


def test_cli_adapters_list_includes_all() -> None:
    res = _run_cli("adapters", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "openaq_air_quality_adapter" in out
    assert "open_meteo_weather_adapter" in out
    assert "osm_geospatial_adapter" in out


def test_cli_adapters_show_known() -> None:
    res = _run_cli("adapters", "show", "openaq_air_quality_adapter")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "adapter_id: openaq_air_quality_adapter" in out
    assert "source_system_type: air_quality_feed" in out
    assert "output_contracts:" in out
    assert "metadata only" in out.lower()
    assert "dynamic" not in out.lower()


def test_cli_adapters_show_unknown_exits_nonzero() -> None:
    res = _run_cli("adapters", "show", "does_not_exist")
    assert res.returncode != 0


def test_cli_adapters_output_has_no_secret_values() -> None:
    res = _run_cli("adapters", "show", "openaq_air_quality_adapter")
    out = (res.stdout or "") + (res.stderr or "")
    lowered = out.lower()
    assert "-----begin" not in lowered
    assert "ghp_" not in lowered
    assert "bearer " not in lowered

