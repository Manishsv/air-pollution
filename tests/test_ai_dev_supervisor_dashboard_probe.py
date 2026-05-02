from __future__ import annotations

from unittest.mock import Mock, patch

from tools.ai_dev_supervisor.dashboard_probe import probe_dashboard


def test_dashboard_probe_matches_expected_labels() -> None:
    html = "<html><body>Air Quality Review Console ... Flood</body></html>"
    resp = Mock()
    resp.status_code = 200
    resp.text = html

    with patch("tools.ai_dev_supervisor.dashboard_probe.requests.get", return_value=resp):
        result = probe_dashboard("http://localhost:8501")

    assert result.reachable is True
    assert "Air Quality Review Console" in result.matched_labels
    assert "Flood" in result.matched_labels
    assert result.missing_labels == []
    assert result.errors == []


def test_dashboard_probe_unreachable_is_non_blocking() -> None:
    with patch(
        "tools.ai_dev_supervisor.dashboard_probe.requests.get",
        side_effect=Exception("connection refused"),
    ):
        result = probe_dashboard("http://localhost:8501")

    assert result.reachable is False
    assert result.attempted is True
    assert result.risks  # should contain non-blocking risk
    assert result.errors

