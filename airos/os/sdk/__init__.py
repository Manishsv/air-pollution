"""
AirOS SDK — public namespace.

Three interaction modes
-----------------------
DISCOVER   airos.os.sdk.*              Metadata & contracts (reads specifications/)
QUERY      airos.os.sdk.store.*        Live store queries   (reads SQLite store)
INGEST     HTTP POST /records          Push data in via the REST API

Quick start
-----------
# Discover what the platform supports
from airos.os.sdk import list_app_ids, list_builders, get_contract_schema

# Query what the platform has produced (requires pipeline to have run)
from airos.os.sdk import AirOSClient
client = AirOSClient()
packets = client.get_decision_packets()

# Or use the store query helpers directly
from airos.os.sdk import store
signals = store.get_signals(city_id="bangalore")

See ARCHITECTURE.md for the full three-mode interaction model.

**Public surface:** names listed in ``__all__`` below. Expanding it is a
deliberate API change — update ARCHITECTURE.md in the same commit.
"""

from airos.os.sdk.apps import get_app_descriptor, list_app_descriptors, list_app_ids
from airos.os.sdk.adapters import (
    get_provider_adapter_descriptor,
    list_provider_adapter_descriptors,
    list_provider_adapter_ids,
)
from airos.os.sdk.catalogs import (
    get_reference_catalog,
    list_reference_catalog_ids,
    list_reference_catalogs,
)
from airos.os.sdk.deployments import (
    get_deployment_profile,
    list_deployment_ids,
    list_deployment_profiles,
)
from airos.os.sdk.inventory import get_platform_inventory
from airos.os.sdk.evidence import (
    export_evidence_bundle,
    inspect_evidence_bundle,
    redact_evidence_bundle,
    verify_evidence_bundle,
)
from airos.os.sdk.contracts import contract_exists, get_contract_schema, list_contract_keys, validate_payload
from airos.os.sdk.hashing import compute_hash
from airos.os.sdk.testing import assert_fixture_valid, assert_payload_valid, load_json_fixture
from airos.os.sdk.store_backup import (
    backup_file_store,
    inspect_store_backup,
    restore_file_store_dry_run,
    verify_store_backup,
)
from airos.os.sdk.builders import list_builders, get_builder_spec
from airos.os.sdk.client import AirOSClient
from airos.os.sdk import store

__all__ = [
    # ── DISCOVER: apps ────────────────────────────────────────────────────────
    "get_app_descriptor",
    "list_app_descriptors",
    "list_app_ids",
    # ── DISCOVER: adapters ────────────────────────────────────────────────────
    "get_provider_adapter_descriptor",
    "list_provider_adapter_descriptors",
    "list_provider_adapter_ids",
    # ── DISCOVER: builders / agents ───────────────────────────────────────────
    "list_builders",
    "get_builder_spec",
    # ── DISCOVER: reference catalogs ──────────────────────────────────────────
    "get_reference_catalog",
    "list_reference_catalog_ids",
    "list_reference_catalogs",
    # ── DISCOVER: deployments ─────────────────────────────────────────────────
    "get_deployment_profile",
    "list_deployment_ids",
    "list_deployment_profiles",
    # ── DISCOVER: inventory ───────────────────────────────────────────────────
    "get_platform_inventory",
    # ── DISCOVER: contracts & validation ─────────────────────────────────────
    "contract_exists",
    "get_contract_schema",
    "list_contract_keys",
    "validate_payload",
    # ── DISCOVER: evidence & governance ──────────────────────────────────────
    "export_evidence_bundle",
    "inspect_evidence_bundle",
    "redact_evidence_bundle",
    "verify_evidence_bundle",
    "backup_file_store",
    "inspect_store_backup",
    "verify_store_backup",
    "restore_file_store_dry_run",
    # ── DISCOVER: hashing & testing ───────────────────────────────────────────
    "compute_hash",
    "assert_fixture_valid",
    "assert_payload_valid",
    "load_json_fixture",
    # ── QUERY: runtime client & store helpers ─────────────────────────────────
    "AirOSClient",
    "store",
]

