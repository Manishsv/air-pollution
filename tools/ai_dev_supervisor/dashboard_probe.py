from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import requests


@dataclass(frozen=True)
class DashboardProbeResult:
    dashboard_url: str
    attempted: bool
    reachable: bool
    status_code: Optional[int]
    matched_labels: list[str]
    missing_labels: list[str]
    risks: list[str]
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def probe_dashboard(
    dashboard_url: str,
    *,
    expected_labels: Optional[list[str]] = None,
    timeout_s: float = 3.0,
) -> DashboardProbeResult:
    """
    Lightweight smoke probe for a running local dashboard.

    - No browser automation, just HTTP GET + substring checks
    - Never raises; returns errors/risks in result
    """
    labels = expected_labels or ["Air Quality Review Console", "Flood"]
    errors: list[str] = []
    risks: list[str] = []
    attempted = True

    try:
        resp = requests.get(dashboard_url, timeout=timeout_s)
        status_code = int(resp.status_code)
        text = resp.text or ""
        reachable = 200 <= status_code < 500  # treat 4xx as reachable (served)
    except Exception as e:  # noqa: BLE001
        return DashboardProbeResult(
            dashboard_url=dashboard_url,
            attempted=attempted,
            reachable=False,
            status_code=None,
            matched_labels=[],
            missing_labels=labels,
            risks=[
                "Dashboard not reachable; start it locally or omit --dashboard-url."
            ],
            errors=[str(e)],
        )

    matched = [lab for lab in labels if lab.lower() in text.lower()]
    missing = [lab for lab in labels if lab not in matched]

    if not reachable:
        risks.append(
            f"Dashboard URL responded with status {status_code}; expected HTML page."
        )
    if missing:
        risks.append("Dashboard page did not include expected labels (may be wrong tab or UI changed).")

    return DashboardProbeResult(
        dashboard_url=dashboard_url,
        attempted=attempted,
        reachable=reachable,
        status_code=status_code,
        matched_labels=matched,
        missing_labels=missing,
        risks=risks,
        errors=errors,
    )