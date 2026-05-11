from __future__ import annotations

import json
from pathlib import Path

from airos.network.cli.deployment_runner.run_deployment import run_deployment
from airos.os.storage import FileAirOsStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_program_reporting_with_store_dir_writes_jsonl_and_counts(tmp_path: Path) -> None:
    deployment_dir = REPO_ROOT / "deployments" / "examples" / "program_reporting_state_demo"
    out_root = tmp_path / "outputs"
    store_root = tmp_path / "store"
    summary = run_deployment(
        deployment_dir=deployment_dir,
        repo_root=REPO_ROOT,
        output_root=out_root,
        store_dir=store_root,
    )

    store = FileAirOsStore(store_root)
    assert store.records_path.is_file()
    assert store.outputs_path.is_file()
    assert store.audit_events_path.is_file()

    recs = store.list_records(deployment_id="program_reporting_state_demo", contract_key="consumer_city_program_submission")
    assert len(recs) == 2

    packets_out = store.list_outputs(
        deployment_id="program_reporting_state_demo", contract_key="consumer_fund_release_review_packet"
    )
    assert len(packets_out) == 2

    summaries = store.list_outputs(
        deployment_id="program_reporting_state_demo", contract_key="consumer_program_reporting_state_summary"
    )
    assert len(summaries) == 1

    audits = store.list_audit_events(deployment_id="program_reporting_state_demo")
    actions = {e.action for e in audits}
    assert "deployment_run_started" in actions
    assert "deployment_run_completed" in actions

    run_summary_disk = json.loads((Path(summary.output_dir) / "deployment_run_summary.json").read_text(encoding="utf-8"))
    assert run_summary_disk.get("store_dir") == str(store_root.resolve())


def test_flood_local_demo_with_store_dir_writes_outputs_and_audit(tmp_path: Path) -> None:
    deployment_dir = REPO_ROOT / "deployments" / "examples" / "flood_local_demo"
    store_root = tmp_path / "store_flood"
    run_deployment(
        deployment_dir=deployment_dir,
        repo_root=REPO_ROOT,
        output_root=tmp_path / "out",
        store_dir=store_root,
    )
    store = FileAirOsStore(store_root)
    assert store.outputs_path.is_file()
    assert store.audit_events_path.is_file()
    dash = store.list_outputs(deployment_id="flood_local_demo", contract_key="consumer_flood_risk_dashboard")
    assert len(dash) == 1
    audits = store.list_audit_events(deployment_id="flood_local_demo")
    assert any(e.action == "deployment_run_completed" for e in audits)
