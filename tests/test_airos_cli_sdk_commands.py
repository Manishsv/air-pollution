from __future__ import annotations

import json
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


def test_contracts_list_includes_known_key() -> None:
    res = _run_cli("contracts", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "consumer_city_program_submission" in out


def test_contracts_show_known_exits_0_and_prints_schema() -> None:
    res = _run_cli("contracts", "show", "consumer_city_program_submission")
    assert res.returncode == 0
    # Should be JSON
    obj = json.loads(res.stdout or "{}")
    assert isinstance(obj, dict)


def test_contracts_show_unknown_exits_nonzero() -> None:
    res = _run_cli("contracts", "show", "does_not_exist_contract_key")
    assert res.returncode != 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "Unknown contract_key" in out or "Unknown contract_key or schema not available" in out


def test_fixtures_validate_valid_sample_exits_0() -> None:
    res = _run_cli(
        "fixtures",
        "validate",
        "consumer_city_program_submission",
        "specifications/examples/program_reporting/city_program_submission.sample.json",
    )
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "valid:" in out
    assert "conforms to consumer_city_program_submission" in out


def test_fixtures_validate_invalid_payload_exits_nonzero(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{}", encoding="utf-8")
    res = _run_cli("fixtures", "validate", "consumer_city_program_submission", str(p))
    assert res.returncode != 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "invalid:" in out


def test_apps_list_includes_known_apps() -> None:
    res = _run_cli("apps", "list")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "program_reporting_review" in out
    assert "flood_risk_review" in out


def test_apps_show_known_exits_0_includes_contracts() -> None:
    res = _run_cli("apps", "show", "program_reporting_review")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "input_contracts" in out
    assert "output_contracts" in out


def test_apps_show_unknown_exits_nonzero() -> None:
    res = _run_cli("apps", "show", "does_not_exist_app")
    assert res.returncode != 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "Unknown app_id" in out


def test_apps_explain_program_reporting_exits_0_and_includes_key_sections() -> None:
    res = _run_cli("apps", "explain", "program_reporting_review")
    assert res.returncode == 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "app_id: program_reporting_review" in out
    assert "## Input contracts" in out
    assert "## Output contracts" in out
    assert "## Decision logic" in out
    assert "program_reporting_review_packet" in out
    assert "blocked_uses" in out or "## Safety" in out
    assert "safe builder registry" in out.lower()
    assert "do not dynamically load code" in out.lower()


def test_apps_explain_flood_exits_0() -> None:
    res = _run_cli("apps", "explain", "flood_risk_review")
    assert res.returncode == 0


def test_apps_explain_unknown_exits_nonzero() -> None:
    res = _run_cli("apps", "explain", "does_not_exist_app")
    assert res.returncode != 0
    out = (res.stdout or "") + (res.stderr or "")
    assert "Unknown app_id" in out


def test_commands_do_not_imply_dynamic_plugins_or_final_automation() -> None:
    # Ensure these inspection commands don't advertise plugin execution or automation.
    res = _run_cli("contracts", "list")
    out = (res.stdout or "") + (res.stderr or "")
    assert "dynamic plugin" not in out.lower()
    assert "final decision" not in out.lower()

    res2 = _run_cli("apps", "explain", "program_reporting_review")
    out2 = (res2.stdout or "") + (res2.stderr or "")
    assert "final decision" not in out2.lower()

