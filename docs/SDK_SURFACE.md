# Supported AirOS Python SDK surface (design reference)

**Label:** Design and documentation of the supported SDK surface for external and in-repo callers. **Implementation guardrails** are applied in code (see `urban_platform/sdk/__init__.py` `__all__`, module docstrings, and `urban_platform/sdk/README.md`) and recorded in `docs/EXECUTION_TRACKER.md`.

## Context

- The AirOS SDK is implemented as the Python package **`urban_platform.sdk`** (not a separately published wheel yet).
- A **2026-05-06** import audit (recorded in `docs/EXECUTION_TRACKER.md`) classified modules and symbols into **public**, **advanced**, and **internal** usage. This document consolidates that classification for contributors and integrators.
- **`urban_platform/sdk/__init__.py`**, **`__all__`**, **`urban_platform/sdk/README.md`**, and **this doc** are aligned: the package root **re-exports** the public helpers listed in `__all__`.

---

## Supported public entrypoints

### 1. Package root (`urban_platform.sdk.__all__`)

Prefer **`from urban_platform.sdk import <name>`** when `<name>` is listed in `__all__`. That set is the **canonical declared public surface** for discovery, contracts, validation, hashing, evidence, store backup, and test helpers.

**Apps**

- `get_app_descriptor`, `list_app_descriptors`, `list_app_ids`

**Provider adapters**

- `get_provider_adapter_descriptor`, `list_provider_adapter_descriptors`, `list_provider_adapter_ids`

**Reference catalogs**

- `get_reference_catalog`, `list_reference_catalog_ids`, `list_reference_catalogs`

**Deployments**

- `get_deployment_profile`, `list_deployment_ids`, `list_deployment_profiles`

**Inventory**

- `get_platform_inventory`

**Evidence**

- `export_evidence_bundle`, `inspect_evidence_bundle`, `redact_evidence_bundle`, `verify_evidence_bundle`

**Store backup / restore (governance)**

- `backup_file_store`, `inspect_store_backup`, `verify_store_backup`, `restore_file_store_dry_run`

**Contracts**

- `contract_exists`, `get_contract_schema`, `list_contract_keys`, `validate_payload`

**Hashing**

- `compute_hash`

**Testing helpers**

- `assert_fixture_valid`, `assert_payload_valid`, `load_json_fixture`

### 2. Submodule imports (equivalent symbols)

The same functions live on submodules (for example `urban_platform.sdk.apps`, `urban_platform.sdk.contracts`, `urban_platform.sdk.store_backup`). **CLI, API, and tests** often import from submodules for locality. For **new** code, either style is acceptable **in-repo**; prefer the **package root** when you want a single obvious public list aligned with `__all__`.

Submodules backing the public API today include:

| Submodule | Role |
| --- | --- |
| `urban_platform.sdk.apps` | App descriptors (metadata) |
| `urban_platform.sdk.adapters` | Provider adapter descriptors |
| `urban_platform.sdk.catalogs` | Reference catalogs |
| `urban_platform.sdk.deployments` | Deployment profiles |
| `urban_platform.sdk.inventory` | Platform inventory |
| `urban_platform.sdk.contracts` | Contract schemas and validation |
| `urban_platform.sdk.hashing` | Deterministic payload hashing |
| `urban_platform.sdk.testing` | Fixture/payload test helpers |
| `urban_platform.sdk.evidence` | Evidence bundle export/inspect/verify/redact |
| `urban_platform.sdk.store_backup` | File-store backup/inspect/verify/dry-run restore |

---

## Advanced / secondary public surface

These are **used by first-party code** (for example dashboard or conformance flows) but are **not** included in `urban_platform.sdk.__all__` today. Treat them as **stabilizing**—prefer root imports for pure descriptor/contract workflows; use these when the use case matches.

- **`UrbanPlatformClient`** — `from urban_platform.sdk.client import UrbanPlatformClient`  
  Minimal client for local platform data access (for example dashboard). Not an alias in `__all__`; intended consumers should import from `urban_platform.sdk.client` explicitly until the package root chooses to re-export it.

---

## Internal and non-guaranteed surfaces

**Do not** treat these as supported external API unless a future spec/task explicitly promotes them.

- **`urban_platform.sdk.specs_helpers`** — Shared YAML/spec load and sanitize helpers used by **`urban_platform.sdk.apps`** and **Core API** descriptor paths. Coupling here bypasses the descriptor-oriented entrypoints; keep new callers on **`get_app_descriptor` / list helpers** (or API routes), not `specs_helpers` directly.
- **`urban_platform.sdk.builders` / `BuilderSpec`** — Metadata-only type for documentation/tests; **no** established import contract and **no** repo-wide usage pattern yet. **Pilot / thin** until promoted.

---

## Implemented guardrails (code + docs)

1. **`__all__`** in `urban_platform/sdk/__init__.py` defines the **root-level public** names. Adding a name there is a **deliberate** change paired with **this doc** and `docs/EXECUTION_TRACKER.md`.
2. **Naming:** Prefer a leading underscore for **module-private** symbols inside SDK modules; avoid growing “convenience” exports without review.
3. **Import style:** External-style integrations should prefer **`from urban_platform.sdk import ...`** for symbols in `__all__`; submodule imports remain valid for internal consistency (CLI/API layering).
4. **`UrbanPlatformClient`:** Remains **advanced** — import from `urban_platform.sdk.client` only (not in `__all__`). If the root package later re-exports the client, update **`__all__`** and this document in the **same** task, then run the **full verification trio** (pytest, conformance, supervisor).
5. **No dynamic plugin loading** and **no execution of untrusted code from descriptors** remain global AirOS rules; the SDK only surfaces **metadata** and **validation** helpers consistent with those policies.

---

## Related

- Execution history and audit: `docs/EXECUTION_TRACKER.md` (Recent Sessions — SDK public surface audit).
- Product/status context: `docs/PROJECT_STATUS.md` (SDK row and stabilization notes).
