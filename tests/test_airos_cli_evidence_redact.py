from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from airos.os.storage.file_store import FileAirOsStore
from airos.os.storage.models import AuditEvent, StoredRun


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "airos/network/cli/airos_cli.py", *args],
        cwd=str(_REPO_ROOT),
        text=True,
        capture_output=True,
    )


def test_cli_evidence_redact_public_demo(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FileAirOsStore(store_dir)
    store.put_run(
        StoredRun(
            run_id="run_r1",
            deployment_id="dep_r",
            application_id="app_r",
            status="completed",
            started_at="2026-05-06T00:00:00Z",
        )
    )
    store.append_audit_event(
        AuditEvent(
            event_id="ae_r1",
            deployment_id="dep_r",
            actor="someone@example.com",
            action="run",
            resource_type="run",
            resource_id="run_r1",
            occurred_at="2026-05-06T00:00:10Z",
        )
    )
    out_dir = tmp_path / "out"
    res_exp = _run_cli(
        "evidence",
        "export",
        "--run-id",
        "run_r1",
        "--store-dir",
        str(store_dir),
        "--output-dir",
        str(out_dir),
    )
    assert res_exp.returncode == 0, res_exp.stderr
    bundle = next(iter(out_dir.glob("*.zip")))

    red_dir = tmp_path / "red"
    res = _run_cli("evidence", "redact", str(bundle), "--profile", "public_demo", "--output-dir", str(red_dir))
    assert res.returncode == 0, res.stderr
    red_bundle = next(iter(red_dir.glob("*.redacted.zip")))
    with zipfile.ZipFile(red_bundle, "r") as zz:
        assert "hash_manifest.json" in zz.namelist()
        audits = json.loads(zz.read("audit_events.json").decode("utf-8"))
        assert audits[0]["actor"] == "redacted_actor"


def test_cli_evidence_redact_invalid_profile_fails(tmp_path: Path) -> None:
    z = tmp_path / "b.zip"
    z.write_bytes(b"not a zip")
    res = _run_cli("evidence", "redact", str(z), "--profile", "nope", "--output-dir", str(tmp_path / "out"))
    assert res.returncode != 0

