from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

CHECKLISTS_DIR = Path(__file__).resolve().parent / "domain_checklists"


def _unknown_domain_recommended(domain: str) -> str:
    return (
        "Create a domain checklist at "
        f"tools/ai_dev_supervisor/domain_checklists/{domain}.yaml."
    )


@dataclass(frozen=True)
class DomainMaturityResult:
    domain: str
    completed_items: list[str]
    missing_items: list[str]
    maturity_stage: str
    recommended_next_task: str
    errors: list[str]
    open_data_first_sequence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def load_domain_checklist(domain: str) -> Optional[dict[str, Any]]:
    """
    Load declarative checklist YAML for ``domain``, or None if no file exists.
    """
    path = CHECKLISTS_DIR / f"{domain}.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "__load_error__": True,
            "__error_message__": str(exc),
            "domain_id": domain,
        }
    if not isinstance(data, dict):
        return {
            "__load_error__": True,
            "__error_message__": "Checklist root must be a mapping",
            "domain_id": domain,
        }
    return data


def required_paths_from_checklist(checklist: dict[str, Any]) -> list[str]:
    """
    Ordered required relative paths from a loaded checklist (``required: true`` only).
    Supports ``checklist_groups`` and optional top-level ``items``.
    """
    paths: list[str] = []
    top_items = checklist.get("items")
    if isinstance(top_items, list):
        for item in top_items:
            if not isinstance(item, dict):
                continue
            if item.get("required", True) is not True:
                continue
            p = item.get("path")
            if isinstance(p, str) and p.strip():
                paths.append(p)

    groups = checklist.get("checklist_groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_items = group.get("items")
            if not isinstance(group_items, list):
                continue
            for item in group_items:
                if not isinstance(item, dict):
                    continue
                if item.get("required", True) is not True:
                    continue
                p = item.get("path")
                if isinstance(p, str) and p.strip():
                    paths.append(p)
    return paths


def _open_data_sequence_from_checklist(checklist: dict[str, Any]) -> tuple[str, ...]:
    raw = checklist.get("open_data_first_sequence")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for line in raw:
        if isinstance(line, str) and line.strip():
            out.append(line.strip())
    return tuple(out)


def _stage_for_missing(missing: list[str]) -> str:
    if not missing:
        return "complete_read_only_vertical_slice"

    has_specs_missing = any(
        p.startswith("specifications/domain_specs/") for p in missing
    )
    has_contracts_missing = any(
        p.startswith("specifications/provider_contracts/")
        or p.startswith("specifications/consumer_contracts/")
        for p in missing
    )
    has_examples_missing = any(p.startswith("specifications/examples/") for p in missing)

    if has_specs_missing or has_contracts_missing:
        return "incomplete_specs"
    if has_examples_missing:
        return "specs_present_missing_examples"

    has_impl_missing = any(
        p.startswith("urban_platform/") or p.startswith("review_dashboard/")
        for p in missing
    )
    if has_impl_missing:
        return "specs_ready_missing_implementation"

    has_tests_missing = any(p.startswith("tests/") for p in missing)
    if has_tests_missing:
        return "implementation_ready_missing_tests"

    return "partial"


def _recommended_next_task_from_checklist(
    checklist: dict[str, Any], missing: list[str], stage: str
) -> str:
    by_stage = checklist.get("recommended_next_by_stage")
    if isinstance(by_stage, dict) and stage in by_stage:
        val = by_stage[stage]
        if isinstance(val, str) and val.strip():
            return val.strip()

    rules = checklist.get("recommended_next_when_any_missing_matches")
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            msg = rule.get("message")
            if not isinstance(msg, str) or not msg.strip():
                continue
            prefix = rule.get("missing_path_prefix")
            suffix = rule.get("missing_path_suffix")
            for m in missing:
                if isinstance(prefix, str) and prefix and m.startswith(prefix):
                    return msg.strip()
                if isinstance(suffix, str) and suffix and m.endswith(suffix):
                    return msg.strip()

    if missing:
        return f"Add missing maturity item: `{missing[0]}`"

    return "Add domain improvements via specs-first sequence, then run conformance."


def probe_domain_maturity(repo_root: Path, domain: str) -> DomainMaturityResult:
    errors: list[str] = []

    checklist = load_domain_checklist(domain)
    if checklist is None:
        return DomainMaturityResult(
            domain=domain,
            completed_items=[],
            missing_items=[],
            maturity_stage="unknown_domain",
            recommended_next_task=_unknown_domain_recommended(domain),
            errors=errors,
            open_data_first_sequence=(),
        )

    if checklist.get("__load_error__"):
        err = str(checklist.get("__error_message__", "checklist load failed"))
        errors.append(err)
        return DomainMaturityResult(
            domain=domain,
            completed_items=[],
            missing_items=[],
            maturity_stage="checklist_error",
            recommended_next_task="Fix domain checklist YAML syntax or structure.",
            errors=errors,
            open_data_first_sequence=(),
        )

    required = required_paths_from_checklist(checklist)
    completed: list[str] = []
    missing: list[str] = []
    for rel in required:
        if (repo_root / rel).exists():
            completed.append(rel)
        else:
            missing.append(rel)

    stage = _stage_for_missing(missing)
    rec = _recommended_next_task_from_checklist(checklist, missing, stage)
    seq = _open_data_sequence_from_checklist(checklist)
    return DomainMaturityResult(
        domain=domain,
        completed_items=completed,
        missing_items=missing,
        maturity_stage=stage,
        recommended_next_task=rec,
        errors=errors,
        open_data_first_sequence=seq,
    )
