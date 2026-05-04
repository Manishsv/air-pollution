from __future__ import annotations

import json
from pathlib import Path

from tools.deployment_runner.run_deployment import run_deployment
from urban_platform.specifications.conformance import assert_conforms


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_program_reporting_state_demo_runner_produces_multi_city_outputs(tmp_path: Path) -> None:
    deployment_dir = REPO_ROOT / "deployments" / "examples" / "program_reporting_state_demo"
    summary = run_deployment(deployment_dir=deployment_dir, repo_root=REPO_ROOT, output_root=tmp_path)

    out_dir = Path(summary.output_dir)
    plural_packets_path = out_dir / "fund_release_review_packets.json"
    state_summary_path = out_dir / "state_program_summary.json"
    run_summary_path = out_dir / "deployment_run_summary.json"

    assert plural_packets_path.exists()
    assert state_summary_path.exists()
    assert run_summary_path.exists()

    packets = json.loads(plural_packets_path.read_text(encoding="utf-8"))
    assert isinstance(packets, list)
    assert len(packets) == 2
    for pkt in packets:
        assert_conforms(pkt, schema_name="consumer_fund_release_review_packet")

    state_summary = json.loads(state_summary_path.read_text(encoding="utf-8"))
    assert state_summary["city_count"] == 2
    assert "blocked_uses" in state_summary
    assert "warnings" in state_summary

    run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    assert run_summary["submissions_processed"] == 2
    assert run_summary["review_packets_generated"] == 2
