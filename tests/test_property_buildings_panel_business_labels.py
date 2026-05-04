from __future__ import annotations

from pathlib import Path


def test_property_buildings_panel_includes_business_readable_labels_and_safety() -> None:
    panel = (
        Path(__file__).resolve().parents[1]
        / "review_dashboard"
        / "components"
        / "property_buildings_panel.py"
    )
    text = panel.read_text(encoding="utf-8")

    # Business-facing headings / labels we expect to keep stable.
    assert "This demo supports verification planning only." in text
    assert "Do not use this dashboard to issue tax demands, penalties, demolition notices, or enforcement actions." in text
    assert "Source records loaded" in text
    assert "Review candidates" in text
    assert "Field verification tasks" in text
    assert "Main review status" in text
    assert "Needs attention" in text
    assert "Do not use this dashboard for" in text
    assert "Source data coverage" in text
    assert "Source information" in text
    assert "Technical: raw review packet" in text
    assert "Technical: contract payload" in text
    assert "This task is for data verification only. It is not an enforcement task." in text

    # Ensure we don't accidentally introduce approval/enforcement language as an allowed action.
    # Guardrail: avoid language that implies *permission* or automation.
    forbidden = [
        "approved",
        "auto-enforce",
        "automatic penalty",
        "penalty required",
        "demolition order issued",
        "fund release approved",
    ]
    lowered = text.lower()
    for s in forbidden:
        assert s not in lowered

