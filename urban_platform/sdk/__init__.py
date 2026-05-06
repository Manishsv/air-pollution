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
from urban_platform.sdk.adapters import (
    get_provider_adapter_descriptor,
    list_provider_adapter_descriptors,
    list_provider_adapter_ids,
)
from urban_platform.sdk.catalogs import (
    get_reference_catalog,
    list_reference_catalog_ids,
    list_reference_catalogs,
)
from urban_platform.sdk.deployments import (
    get_deployment_profile,
    list_deployment_ids,
    list_deployment_profiles,
)
from urban_platform.sdk.inventory import get_platform_inventory
from urban_platform.sdk.evidence import (
    export_evidence_bundle,
    inspect_evidence_bundle,
    redact_evidence_bundle,
    verify_evidence_bundle,
)
from urban_platform.sdk.contracts import contract_exists, get_contract_schema, list_contract_keys, validate_payload
from urban_platform.sdk.hashing import compute_hash
from urban_platform.sdk.testing import assert_fixture_valid, assert_payload_valid, load_json_fixture
from urban_platform.sdk.store_backup import (
    backup_file_store,
    inspect_store_backup,
    restore_file_store_dry_run,
    verify_store_backup,
)

__all__ = [
    # apps
    "get_app_descriptor",
    "list_app_descriptors",
    "list_app_ids",
    # adapters
    "get_provider_adapter_descriptor",
    "list_provider_adapter_descriptors",
    "list_provider_adapter_ids",
    # reference catalogs
    "get_reference_catalog",
    "list_reference_catalog_ids",
    "list_reference_catalogs",
    # deployments
    "get_deployment_profile",
    "list_deployment_ids",
    "list_deployment_profiles",
    # inventory
    "get_platform_inventory",
    # evidence
    "export_evidence_bundle",
    "inspect_evidence_bundle",
    "redact_evidence_bundle",
    "verify_evidence_bundle",
    # store backup
    "backup_file_store",
    "inspect_store_backup",
    "verify_store_backup",
    "restore_file_store_dry_run",
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

