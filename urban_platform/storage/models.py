from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StoredRecord:
    record_id: str
    deployment_id: str
    contract_key: str
    payload: dict[str, Any]
    received_at: str
    source_ref: str | None = None
    payload_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredOutput:
    output_id: str
    deployment_id: str
    contract_key: str
    payload: dict[str, Any]
    generated_at: str
    generated_by: str
    input_refs: list[str] = field(default_factory=list)
    payload_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    deployment_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    occurred_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

