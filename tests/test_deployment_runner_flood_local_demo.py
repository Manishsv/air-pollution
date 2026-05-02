from __future__ import annotations

import json
from pathlib import Path

from tools.deployment_runner.run_deployment import run_deployment
from urban_platform.specifications.conformance import assert_conforms


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_flood_local_demo_deployment_runner_produces_valid_outputs(tmp_path: Path) -> None:
    deployment_dir = REPO_ROOT / "deployments" / "examples" / "flood_local_demo"
    summary = run_deployment(deployment_dir=deployment_dir, repo_root=REPO_ROOT, output_root=tmp_path)

    out_dir = Path(summary.output_dir)
    dash_path = out_dir / "flood_risk_dashboard_payload.json"
    pkt_path = out_dir / "flood_decision_packets.json"
    task_path = out_dir / "flood_field_verification_tasks.json"
    sum_path = out_dir / "deployment_run_summary.json"

    assert dash_path.exists()
    assert pkt_path.exists()
    assert task_path.exists()
    assert sum_path.exists()

    dashboard = json.loads(dash_path.read_text(encoding="utf-8"))
    packets = json.loads(pkt_path.read_text(encoding="utf-8"))
    tasks = json.loads(task_path.read_text(encoding="utf-8"))

    assert_conforms(dashboard, schema_name="consumer_flood_risk_dashboard")
    for pkt in packets:
        assert_conforms(pkt, schema_name="consumer_flood_decision_packet")
    for t in tasks:
        assert_conforms(t, schema_name="consumer_field_verification_task")

