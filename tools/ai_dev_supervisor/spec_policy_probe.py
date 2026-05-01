from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


@dataclass(frozen=True)
class SpecPolicyProbeResult:
    policy_path: Optional[str]
    loaded: bool
    specs_first: Optional[bool]
    keys_present: list[str]
    errors: list[str]
    raw_policy: Optional[dict]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _read_yaml(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return None, f"Failed to read YAML at {path}: {e}"

    try:
        data = yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        return None, f"Failed to parse YAML at {path}: {e}"

    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"YAML root at {path} is not a mapping/object"
    return data, None


def probe_spec_policy(repo_root: Path) -> SpecPolicyProbeResult:
    """
    Probe for a machine-readable specs-first policy.

    Preference order:
    - specifications/spec_policy.yaml
    - specifications/specs_policy.yaml
    """
    errors: list[str] = []
    candidates = [
        repo_root / "specifications" / "spec_policy.yaml",
        repo_root / "specifications" / "specs_policy.yaml",
    ]
    chosen: Optional[Path] = next((p for p in candidates if p.exists()), None)

    if chosen is None:
        return SpecPolicyProbeResult(
            policy_path=None,
            loaded=False,
            specs_first=None,
            keys_present=[],
            errors=["No spec policy YAML found under specifications/"],
            raw_policy=None,
        )

    policy, err = _read_yaml(chosen)
    if err:
        errors.append(err)
        return SpecPolicyProbeResult(
            policy_path=str(chosen.relative_to(repo_root)),
            loaded=False,
            specs_first=None,
            keys_present=[],
            errors=errors,
            raw_policy=None,
        )

    assert policy is not None
    keys_present = sorted(policy.keys())

    specs_first_val: Optional[bool] = None
    if "specs_first" in policy and isinstance(policy.get("specs_first"), bool):
        specs_first_val = bool(policy["specs_first"])

    return SpecPolicyProbeResult(
        policy_path=str(chosen.relative_to(repo_root)),
        loaded=True,
        specs_first=specs_first_val,
        keys_present=keys_present,
        errors=errors,
        raw_policy=policy,
    )

