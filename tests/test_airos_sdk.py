from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from urban_platform.sdk import (
    assert_fixture_valid,
    compute_hash,
    contract_exists,
    get_app_descriptor,
    get_contract_schema,
    list_app_ids,
    list_contract_keys,
    validate_payload,
)


FIXTURE_PATH = Path("specifications/examples/program_reporting/city_program_submission.sample.json")
CONTRACT_KEY = "consumer_city_program_submission"


def test_contract_listing_and_schema_loading() -> None:
    keys = list_contract_keys()
    assert CONTRACT_KEY in keys

    schema = get_contract_schema(CONTRACT_KEY)
    assert isinstance(schema, dict)
    assert schema.get("$schema") or schema.get("$id") or schema.get("type")  # sanity


def test_contract_exists_known_and_unknown() -> None:
    assert contract_exists(CONTRACT_KEY) is True
    assert contract_exists("does_not_exist_contract_key") is False


def test_validate_payload_valid_fixture_has_no_errors() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    errs = validate_payload(CONTRACT_KEY, payload)
    assert errs == []


def test_validate_payload_invalid_payload_has_errors() -> None:
    errs = validate_payload(CONTRACT_KEY, {})
    assert len(errs) >= 1


def test_app_descriptor_listing_and_lookup() -> None:
    ids = list_app_ids()
    assert "program_reporting_review" in ids
    assert "flood_risk_review" in ids

    d = get_app_descriptor("program_reporting_review")
    assert isinstance(d, dict)
    assert d.get("app_id") == "program_reporting_review"
    assert isinstance(d.get("input_contracts") or [], list)


def test_compute_hash_is_deterministic() -> None:
    h1 = compute_hash({"b": 1, "a": 2})
    h2 = compute_hash({"a": 2, "b": 1})
    assert h1 == h2


def test_assert_fixture_valid_passes() -> None:
    assert_fixture_valid(CONTRACT_KEY, FIXTURE_PATH)


def test_sdk_apps_does_not_enable_dynamic_execution() -> None:
    import urban_platform.sdk.apps as sdk_apps

    src = inspect.getsource(sdk_apps)
    blocked = ["importlib", "exec(", "eval(", "builder_registry"]
    for b in blocked:
        assert b not in src

