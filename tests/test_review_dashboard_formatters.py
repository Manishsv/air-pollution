from __future__ import annotations

from review_dashboard.formatters import (
    evidence_inputs_to_rows,
    humanize_internal_flag,
    humanize_snake_sentence,
    provenance_sources_rows,
    safety_gates_to_rows,
)


def test_humanize_internal_flag_known() -> None:
    assert "Enforcement" in humanize_internal_flag("ENFORCEMENT_AND_TAX_ACTIONS_BLOCKED_BY_POLICY")


def test_humanize_snake_sentence_blocked_use() -> None:
    s = humanize_snake_sentence("automated_enforcement_or_tax_reassessment_without_human_review")
    assert "_" not in s
    assert "Automated" in s


def test_provenance_sources_rows() -> None:
    rows = provenance_sources_rows({"sources": ["a", "b"], "synthetic_used": True})
    assert len(rows) == 2
    assert rows[0]["Synthetic or demo"] == "Yes"


def test_evidence_inputs_to_rows() -> None:
    rows = evidence_inputs_to_rows({"inputs": [{"type": "x", "name": "n", "value": 1, "unit": "u"}]})
    assert rows[0]["Name"] == "n"


def test_safety_gates_to_rows() -> None:
    rows = safety_gates_to_rows([{"gate_id": "matching_not_implemented", "status": "blocked", "message": "m"}])
    assert rows[0]["Status"] == "blocked"
    assert "Matching" in rows[0]["Gate"]
