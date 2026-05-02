from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.ai_dev_supervisor.domain_maturity_probe import (
    load_domain_checklist,
    probe_domain_maturity,
    required_paths_from_checklist,
    _recommended_next_task_from_checklist,
    _stage_for_missing,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_flood_risk_checklist_loads() -> None:
    data = load_domain_checklist("flood_risk")
    assert data is not None
    assert data.get("__load_error__") is not True
    assert data.get("domain_id") == "flood_risk"
    paths = required_paths_from_checklist(data)
    assert len(paths) == 24
    assert paths[0] == "specifications/domain_specs/flood_risk.v1.yaml"
    assert paths[-1] == "tests/test_flood_dashboard_panel_demo.py"


def test_property_buildings_checklist_loads() -> None:
    data = load_domain_checklist("property_buildings")
    assert data is not None
    assert data.get("__load_error__") is not True
    assert data.get("domain_id") == "property_buildings"
    paths = required_paths_from_checklist(data)
    assert len(paths) == 30
    assert paths[0] == "specifications/domain_specs/property_buildings.v1.yaml"
    assert "urban_platform/processing/property_buildings/open_data_features.py" in paths


def test_air_quality_checklist_loads() -> None:
    data = load_domain_checklist("air_quality")
    assert data is not None
    assert data.get("__load_error__") is not True
    assert data.get("domain_id") == "air_quality"
    paths = required_paths_from_checklist(data)
    assert "specifications/domain_specs/air_quality.v1.yaml" in paths
    assert "urban_platform/applications/air_pollution/pipeline.py" in paths
    # Runtime outputs are optional, so the probe should complete even on clean clone.
    assert "data/outputs/decision_packets.json" not in paths


def test_unknown_domain_handled_gracefully() -> None:
    r = probe_domain_maturity(REPO_ROOT, "no_such_domain_for_maturity_xyz")
    assert r.maturity_stage == "unknown_domain"
    assert r.completed_items == []
    assert r.missing_items == []
    assert r.errors == []
    assert "Create a domain checklist" in r.recommended_next_task
    assert "no_such_domain_for_maturity_xyz.yaml" in r.recommended_next_task
    assert r.open_data_first_sequence == ()


@pytest.mark.parametrize(
    ("missing", "expected_stage"),
    [
        ([], "complete_read_only_vertical_slice"),
        (["specifications/domain_specs/x.yaml"], "incomplete_specs"),
        (
            ["specifications/provider_contracts/x.schema.json"],
            "incomplete_specs",
        ),
        (
            ["specifications/consumer_contracts/x.schema.json"],
            "incomplete_specs",
        ),
        (
            ["specifications/examples/flood/x.json"],
            "specs_present_missing_examples",
        ),
        (
            ["urban_platform/foo.py"],
            "specs_ready_missing_implementation",
        ),
        (
            ["review_dashboard/components/x.py"],
            "specs_ready_missing_implementation",
        ),
        (["tests/test_x.py"], "implementation_ready_missing_tests"),
    ],
)
def test_stage_for_missing_equivalent(missing: list[str], expected_stage: str) -> None:
    assert _stage_for_missing(missing) == expected_stage


def test_recommended_next_respects_checklist_stage_and_rules() -> None:
    flood = load_domain_checklist("flood_risk")
    assert flood is not None
    complete_rec = _recommended_next_task_from_checklist(flood, [], "complete_read_only_vertical_slice")
    assert "dashboard smoke" in complete_rec.lower()

    pb = load_domain_checklist("property_buildings")
    assert pb is not None
    panel_missing = [
        "review_dashboard/components/property_buildings_panel.py",
    ]
    rec = _recommended_next_task_from_checklist(pb, panel_missing, "specs_ready_missing_implementation")
    assert "property_buildings" in rec.lower()
    assert "panel" in rec.lower()


def test_probe_flood_risk_matches_prior_vertical_slice_contract() -> None:
    """Same path list and staging as pre–YAML refactor when repo is complete."""
    r = probe_domain_maturity(REPO_ROOT, "flood_risk")
    data = load_domain_checklist("flood_risk")
    assert data is not None
    expected_paths = required_paths_from_checklist(data)
    assert sorted(r.completed_items) == sorted(expected_paths)
    assert r.missing_items == []
    assert r.maturity_stage == "complete_read_only_vertical_slice"
    assert r.open_data_first_sequence == ()
    want = _recommended_next_task_from_checklist(data, [], r.maturity_stage)
    assert r.recommended_next_task == want


def test_probe_property_buildings_matches_prior_vertical_slice_contract() -> None:
    r = probe_domain_maturity(REPO_ROOT, "property_buildings")
    data = load_domain_checklist("property_buildings")
    assert data is not None
    expected_paths = required_paths_from_checklist(data)
    assert sorted(r.completed_items) == sorted(expected_paths)
    assert r.missing_items == []
    assert r.maturity_stage == "complete_read_only_vertical_slice"
    assert len(r.open_data_first_sequence) == 8
    assert r.open_data_first_sequence[0].startswith("1. Domain spec")
    want = _recommended_next_task_from_checklist(data, [], r.maturity_stage)
    assert r.recommended_next_task == want


def test_invalid_checklist_yaml_non_crashing() -> None:
    from tempfile import TemporaryDirectory

    import tools.ai_dev_supervisor.domain_maturity_probe as dmp

    with TemporaryDirectory() as td:
        tdir = Path(td)
        (tdir / "broken_domain.yaml").write_text(":\n  [\n", encoding="utf-8")
        with patch.object(dmp, "CHECKLISTS_DIR", tdir):
            r = probe_domain_maturity(REPO_ROOT, "broken_domain")
    assert r.maturity_stage == "checklist_error"
    assert r.errors
    assert "Fix domain checklist YAML" in r.recommended_next_task
