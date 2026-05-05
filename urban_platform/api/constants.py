from __future__ import annotations

from typing import Tuple

# Exact pilot warning line requested for conformance with safety posture.
API_PILOT_SAFE_WARNINGS: Tuple[str, ...] = (
    "Pilot-runtime API: review support only. No disbursement, treasury, or enforcement automation is performed by this service.",
    "Fund release and finance authorization remain outside AirOS and require appropriately authorized human processes.",
)
