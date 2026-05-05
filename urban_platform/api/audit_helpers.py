from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from urban_platform.storage import AuditEvent, FileAirOsStore, now_utc_iso


def append_audit(
    store: FileAirOsStore,
    *,
    deployment_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    store.append_audit_event(
        AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex}",
            deployment_id=deployment_id,
            actor="airos_core_api",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            occurred_at=now_utc_iso(),
            metadata=metadata or {},
        )
    )
