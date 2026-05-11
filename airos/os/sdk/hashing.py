from __future__ import annotations

from typing import Any

from airos.os.storage.file_store import compute_payload_hash


def compute_hash(payload: dict[str, Any]) -> str:
    return compute_payload_hash(payload)

