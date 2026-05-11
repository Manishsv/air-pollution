from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from airos.os.specifications.conformance import load_manifest


def schema_ref_for_contract(contract_key: str) -> Optional[str]:
    """
    Return a safe, relative schema reference for a manifest artifact key.

    This is used for developer receipts/debugging only. Never return absolute paths.
    """
    ck = str(contract_key or "").strip()
    m = load_manifest()
    artifacts = m.get("artifacts") or {}
    rel = (artifacts.get(ck) or {}).get("schema_path")
    if not rel:
        return None
    s = str(rel)
    if s.startswith("/") or ".." in s:
        return None
    return s


def make_receipt_id_for_record(record_id: str) -> str:
    rid = str(record_id or "").strip() or uuid.uuid4().hex[:16]
    return f"receipt_rec_{rid}"[:240]


def make_receipt_id_for_output(output_id: str) -> str:
    oid = str(output_id or "").strip() or uuid.uuid4().hex[:16]
    return f"receipt_out_{oid}"[:240]


def make_receipt_id(prefix: str = "receipt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def safe_errors(errors: List[Dict[str, Any]], *, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Defensive: keep only JSON-serializable, stack-trace-free error summaries.
    """
    out: List[Dict[str, Any]] = []
    for e in (errors or [])[:limit]:
        if not isinstance(e, dict):
            continue
        msg = e.get("message")
        if isinstance(msg, str) and "traceback" in msg.lower():
            msg = "Validation error."
        path = e.get("path")
        out.append(
            {
                "message": str(msg) if msg is not None else "Validation error.",
                "path": path if isinstance(path, list) else [],
            }
        )
    return out

