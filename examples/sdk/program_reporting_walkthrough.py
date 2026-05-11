"""
Program Reporting SDK walkthrough — read-only example.

Uses only the documented public SDK surface (airos.os.sdk.__all__).
Does not require the Core API to be running and does not mutate any state.

Run from the repository root:
    python examples/sdk/program_reporting_walkthrough.py

See docs/PROGRAM_REPORTING_SDK_WALKTHROUGH.md for the full narrative guide.
"""

import sys
import os

# Ensure the repository root is on sys.path when running this file directly.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from airos.os.sdk import (
    get_platform_inventory,
    list_app_ids,
    list_app_descriptors,
    list_contract_keys,
    get_contract_schema,
    validate_payload,
    load_json_fixture,
    list_deployment_ids,
    get_deployment_profile,
    list_reference_catalog_ids,
    get_reference_catalog,
)


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def show_inventory() -> dict:
    _section("1. Platform inventory")
    inventory = get_platform_inventory()
    print(f"  Contracts  : {inventory['contracts']['contract_count']}")
    print(f"  Apps       : {inventory['apps']['app_count']}")
    print(f"  Adapters   : {inventory['adapters']['adapter_count']}")
    print(f"  Catalogs   : {inventory['catalogs']['catalog_count']}")
    print(f"  Deployments: {inventory['deployments']['deployment_count']}")
    return inventory


def show_app_descriptor() -> dict:
    _section("2. Program Reporting app descriptor")
    print(f"  Registered app IDs: {list_app_ids()}")

    descriptors = list_app_descriptors()
    pr = next(
        (d for d in descriptors if d["app_id"] == "program_reporting_review"), None
    )
    if pr is None:
        print("  [WARNING] program_reporting_review not found in descriptors")
        return {}

    print(f"  Name      : {pr['name']}")
    print(f"  Status    : {pr['status']}")
    print(f"  App type  : {pr['app_type']}")
    print(f"  Exec model: {pr['decision_logic']['execution_model']}")
    print(f"  Inputs    : {pr['input_contracts']}")
    print(f"  Outputs   : {pr['output_contracts']}")

    safety = pr.get("safety", {})
    print(f"\n  Safety gates:")
    print(f"    review_support_only   : {safety.get('review_support_only')}")
    print(f"    human_review_required : {safety.get('human_review_required')}")
    print(f"    blocked_uses:")
    for use in safety.get("blocked_uses", []):
        print(f"      - {use}")

    return pr


def show_contracts() -> dict:
    _section("3. Contracts")
    all_keys = list_contract_keys()
    pr_keys = [
        k for k in all_keys if "program" in k or "fund" in k or "submission" in k
    ]
    print(f"  Program Reporting contract keys: {pr_keys}")

    input_schema = get_contract_schema("consumer_city_program_submission")
    print(f"\n  Input contract  : {input_schema.get('title', 'n/a')}")
    print(f"  Required fields : {len(input_schema.get('required', []))}")
    print(f"  Notable fields  : blocked_uses, human_review_required, reference_data_versions")

    output_schema = get_contract_schema("consumer_fund_release_review_packet")
    print(f"\n  Output contract : {output_schema.get('title', 'n/a')}")
    print(f"  Required fields : {len(output_schema.get('required', []))}")

    fixture_path = (
        "specifications/examples/program_reporting/city_program_submission.sample.json"
    )
    payload = load_json_fixture(fixture_path)
    errors = validate_payload("consumer_city_program_submission", payload)
    valid = len(errors) == 0
    print(f"\n  Fixture validation ({fixture_path}):")
    print(f"    valid       : {valid}")
    print(f"    error_count : {len(errors)}")
    return {"valid": valid, "error_count": len(errors)}


def show_deployment() -> dict:
    _section("4. Deployment profile")
    print(f"  Registered deployment IDs: {list_deployment_ids()}")

    profile = get_deployment_profile("program_reporting_state_demo")
    raw = profile.get("deployment_profile", {})
    print(f"\n  Name        : {profile['deployment_name']}")
    print(f"  Type        : {raw.get('deployment_type', 'n/a')}")
    print(f"  Environment : {raw.get('environment', 'n/a')}")
    print(f"  Domains     : {profile['enabled_domains']}")
    print(f"  Apps        : {profile['application_count']}")
    print(f"  Notes       : {raw.get('notes', '').strip()}")
    return profile


def show_catalogs() -> None:
    _section("5. Reference catalogs")
    catalog_ids = list_reference_catalog_ids()
    print(f"  Available catalogs: {catalog_ids}")

    catalog = get_reference_catalog("program_catalog_demo_in")
    print(f"\n  program_catalog_demo_in:")
    print(f"    Type   : {catalog['catalog_type']}")
    print(f"    Status : {catalog['status']}")
    print(f"    Entries:")
    for entry in catalog.get("entries", []):
        print(f"      {entry['code']} — {entry['label']} ({entry['status']})")


def main() -> dict:
    print("AirOS SDK walkthrough — Program Reporting (read-only)")
    print("No Core API required. No state mutations.")

    inventory = show_inventory()
    app = show_app_descriptor()
    contracts = show_contracts()
    deployment = show_deployment()
    show_catalogs()

    print(f"\n{'=' * 60}")
    print("  Done. All calls used airos.os.sdk public surface only.")
    print("=" * 60)

    return {
        "inventory": inventory,
        "app": app,
        "contracts": contracts,
        "deployment": deployment,
    }


if __name__ == "__main__":
    main()
