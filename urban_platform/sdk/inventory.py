from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from urban_platform.sdk.adapters import list_provider_adapter_ids
from urban_platform.sdk.apps import list_app_ids
from urban_platform.sdk.catalogs import list_reference_catalog_ids
from urban_platform.sdk.contracts import list_contract_keys
from urban_platform.sdk.deployments import list_deployment_ids


def _repo_root() -> Path:
    # SPEC_ROOT is specifications/; keep SDK inventory decoupled from API settings.
    from urban_platform.specifications.conformance import SPEC_ROOT  # noqa: WPS433

    return SPEC_ROOT.parent.resolve()


def _runtime_store_dir() -> Path:
    raw = os.environ.get("AIROS_STORE_DIR", "").strip()
    if not raw:
        return (_repo_root() / "data" / "store" / "api").resolve()
    p = Path(raw)
    return (p if p.is_absolute() else (_repo_root() / p)).resolve()


def _count_jsonl_objects(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                n += 1
    except Exception:
        return 0
    return n


def get_platform_inventory(*, include_runtime: bool = False) -> dict[str, Any]:
    contract_keys = list_contract_keys()
    app_ids = list_app_ids()
    adapter_ids = list_provider_adapter_ids()
    catalog_ids = list_reference_catalog_ids()
    deployment_ids = list_deployment_ids()

    inv: dict[str, Any] = {
        "contracts": {
            "contract_count": len(contract_keys),
            "contract_keys": contract_keys,
        },
        "apps": {
            "app_count": len(app_ids),
            "app_ids": app_ids,
        },
        "adapters": {
            "adapter_count": len(adapter_ids),
            "adapter_ids": adapter_ids,
        },
        "catalogs": {
            "catalog_count": len(catalog_ids),
            "catalog_ids": catalog_ids,
        },
        "deployments": {
            "deployment_count": len(deployment_ids),
            "deployment_ids": deployment_ids,
        },
        "safety": {
            "review_support_only": True,
            "note": "Inventory is read-only and does not execute apps, adapters, or deployments.",
        },
    }

    if not include_runtime:
        inv["runtime"] = {"included": False, "note": "Runtime store counts not included. Use include_runtime=true / --include-runtime."}
        return inv

    store_dir = _runtime_store_dir()
    if not store_dir.exists():
        inv["runtime"] = {
            "included": True,
            "runtime_available": False,
            "store_dir": str(store_dir.relative_to(_repo_root())).replace("\\", "/") if str(store_dir).startswith(str(_repo_root())) else "AIROS_STORE_DIR",
            "note": "Runtime store directory does not exist. Set AIROS_STORE_DIR or run a local pilot/runtime to create store files.",
        }
        return inv

    # Read-only counts (do not create directories).
    inv["runtime"] = {
        "included": True,
        "runtime_available": True,
        "record_count": _count_jsonl_objects(store_dir / "records.jsonl"),
        "run_count": _count_jsonl_objects(store_dir / "runs.jsonl"),
        "output_count": _count_jsonl_objects(store_dir / "outputs.jsonl"),
        "validation_receipt_count": _count_jsonl_objects(store_dir / "validation_receipts.jsonl"),
        "audit_event_count": _count_jsonl_objects(store_dir / "audit_events.jsonl"),
        "note": "Counts are derived from local FileAirOsStore JSONL files. Inventory is read-only.",
    }
    return inv

