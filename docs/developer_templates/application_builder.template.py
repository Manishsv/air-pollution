# Copy to: urban_platform/applications/<domain_name>/<module>.py
# Replace <domain_name>, <consumer_name>, and shape real dicts from your contracts.
#
# This file is a documentation template only — not imported by AirOS.

from __future__ import annotations

from typing import Any


def build_consumer_payload(
    normalized_inputs: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    # After copy: rename to build_<consumer_name>_payload (valid Python identifier).
    """
    Transform validated / normalized inputs into a consumer-contract-shaped dict.

    Rules:
    - Keep domain rules here (or in processing modules), not in Streamlit.
    - Return only JSON-serializable primitives and collections.
    - Include warnings + blocked_uses appropriate to the domain spec.
    """
    _ = normalized_inputs  # remove when you use real shaping logic
    return {
        # After copy: rename function and use stable IDs from your runner/tests.
        "payload_id": "demo_<consumer_name>_001",
        "generated_at": generated_at,
        "warnings": [
            "fixture_demo_only",
            "human_review_required",
        ],
        "blocked_uses": [
            "automatic_enforcement",
            "automatic_disbursement",
        ],
        "summary": {
            "headline": "<domain_name> demo output",
            "inputs_echo": normalized_inputs.get("payload", {}),
        },
    }
