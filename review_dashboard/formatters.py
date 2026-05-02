from __future__ import annotations

from typing import Any

# Internal scaffolding / warning tokens → reviewer-facing labels
_INTERNAL_FLAG_LABELS: dict[str, str] = {
    "ENFORCEMENT_AND_TAX_ACTIONS_BLOCKED_BY_POLICY": "Enforcement and tax actions blocked by policy",
    "MATCHING_NOT_IMPLEMENTED": "Matching not implemented",
    "SYNTHETIC_INPUT_PRESENT": "Synthetic or demo input present",
    "NO_INPUTS_PROVIDED": "No inputs provided",
    "NO_FEATURE_ROWS": "No feature rows",
}

_GATE_ID_LABELS: dict[str, str] = {
    "require_field_verification_before_enforcement_or_tax_action": "Field verification required before enforcement or tax action",
    "matching_not_implemented": "Matching not implemented",
    "synthetic_inputs_present": "Synthetic or demo inputs present",
    "decision_support_only": "Decision support only",
    "low_lying_proxy_unavailable": "Low-lying risk proxy unavailable",
    "low_data_quality": "Low data quality",
    "privacy_and_sensitivity_guardrail": "Privacy and sensitivity guardrail",
    "block_if_low_provenance_or_low_reliability": "Low provenance or reliability",
}


def humanize_internal_flag(flag: str) -> str:
    """Turn internal UPPER_SNAKE flags into short reviewer-facing labels."""
    s = str(flag or "").strip()
    if not s:
        return ""
    if s in _INTERNAL_FLAG_LABELS:
        return _INTERNAL_FLAG_LABELS[s]
    if s.isupper() and "_" in s:
        return s.replace("_", " ").title()
    return s


def humanize_gate_id(gate_id: str) -> str:
    gid = str(gate_id or "").strip()
    if not gid:
        return ""
    if gid in _GATE_ID_LABELS:
        return _GATE_ID_LABELS[gid]
    return gid.replace("_", " ").title()


def humanize_warning_id(warning_id: str) -> str:
    wid = str(warning_id or "").strip()
    if not wid:
        return ""
    return wid.replace("_", " ").strip().title()


def provenance_sources_rows(
    provenance_summary: dict[str, Any] | None,
    *,
    default_source_type: str = "—",
) -> list[dict[str, Any]]:
    """
    Build rows for a provenance table from dashboard `provenance_summary`.

    Contract only carries `sources` (strings) and `synthetic_used` (bool).
    """
    ps = provenance_summary or {}
    sources = ps.get("sources") or []
    synthetic_used = bool(ps.get("synthetic_used"))
    demo_label = "Yes" if synthetic_used else "No"
    rows: list[dict[str, Any]] = []
    for src in sources:
        if not src:
            continue
        rows.append(
            {
                "Source": str(src),
                "Type": default_source_type,
                "Synthetic or demo": demo_label,
            }
        )
    return rows


def evidence_inputs_to_rows(evidence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten review-packet `evidence.inputs` into a readable table."""
    ev = evidence or {}
    inputs = ev.get("inputs") or []
    if not isinstance(inputs, list):
        return []
    out: list[dict[str, Any]] = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "Type": str(item.get("type") or "—"),
                "Name": str(item.get("name") or "—"),
                "Value": item.get("value"),
                "Unit": str(item.get("unit") or "—"),
            }
        )
    return out


def safety_gates_to_rows(gates: list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for g in gates or []:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("gate_id") or "")
        rows.append(
            {
                "Gate": humanize_gate_id(gid),
                "Gate ID": gid,
                "Status": str(g.get("status") or "—"),
                "Message": str(g.get("message") or ""),
            }
        )
    return rows


def humanize_snake_sentence(token: str) -> str:
    """Turn snake_case policy tokens into short Title Case sentences."""
    s = str(token or "").strip()
    if not s:
        return ""
    return s.replace("_", " ").strip().title()
