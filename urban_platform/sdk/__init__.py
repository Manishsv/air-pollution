"""
AirOS SDK namespace.

This namespace is reserved for developer-facing helpers and client surfaces.

The SDK is an internal Python module (not a separate package yet). It provides a
small, stable helper surface for app and adapter developers:

- inspect app descriptors (metadata only; not plugins)
- inspect contracts and validate payloads/fixtures by manifest contract_key
- compute deterministic payload hashes
"""

from urban_platform.sdk.apps import get_app_descriptor, list_app_descriptors, list_app_ids
from urban_platform.sdk.contracts import contract_exists, get_contract_schema, list_contract_keys, validate_payload
from urban_platform.sdk.hashing import compute_hash
from urban_platform.sdk.testing import assert_fixture_valid, assert_payload_valid, load_json_fixture

__all__ = [
    # apps
    "get_app_descriptor",
    "list_app_descriptors",
    "list_app_ids",
    # contracts
    "contract_exists",
    "get_contract_schema",
    "list_contract_keys",
    "validate_payload",
    # hashing
    "compute_hash",
    # testing
    "assert_fixture_valid",
    "assert_payload_valid",
    "load_json_fixture",
]

