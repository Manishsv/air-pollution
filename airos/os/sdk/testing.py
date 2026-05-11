from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from airos.os.sdk.contracts import validate_payload


def load_json_fixture(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    with open(p, encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("Fixture JSON must be an object/dict.")
    return obj


def assert_payload_valid(contract_key: str, payload: dict[str, Any]) -> None:
    errs = validate_payload(contract_key, payload)
    if errs:
        msg = "; ".join([f"{e.get('path')}: {e.get('message')}" for e in errs[:10]])
        raise AssertionError(f"payload invalid for {contract_key!r}: {msg}")


def assert_fixture_valid(contract_key: str, path: str | Path) -> None:
    payload = load_json_fixture(path)
    assert_payload_valid(contract_key, payload)

