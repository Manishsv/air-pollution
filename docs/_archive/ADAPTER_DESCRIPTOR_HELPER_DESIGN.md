# Design Note: Shared Helper for Provider Adapter Descriptor Loading

**Status:** design / planning only — no runtime changes are proposed or implemented by this document.

## Context and Goal

AirOS app descriptors under `specifications/app_descriptors/` are discovered and validated through a **shared** module, `urban_platform/sdk/specs_helpers.py`: safe YAML parsing, optional JSON Schema validation via manifest-resolved schema paths, and small helpers such as “load all” and “get one by `app_id`.” The public SDK surface (`urban_platform/sdk/apps.py`) and API loading (`urban_platform/api/app_descriptors.py`) both delegate to that helper, which keeps metadata loading consistent and testable.

This note explores an **analogous shared helper** for **provider adapter descriptors** under `specifications/provider_adapters/`, so adapter metadata loading follows the same layering pattern as apps. Any future implementation would be incremental and behavior-preserving unless explicitly scoped otherwise.

## Current State (Adapters)

### Where descriptors live

Governed adapter descriptor YAML files live under:

- `specifications/provider_adapters/` (e.g. `openaq_air_quality_adapter.v1.yaml`, …).

Their shape is governed by:

- `specifications/platform_objects/provider_adapter_descriptor.v1.schema.json`

The manifest artifact key used for schema resolution today is `platform_provider_adapter_descriptor` (see `urban_platform/specifications/conformance` usage in code).

### How they are loaded today

Discovery, validation, and lookup are implemented **inside** `urban_platform/sdk/adapters.py`:

- Directory resolution via `SPEC_ROOT / "provider_adapters"`.
- Schema validator built from the manifest (same pattern as app descriptors, but duplicated in this module).
- `list_provider_adapter_descriptors()`, `list_provider_adapter_ids()`, `get_provider_adapter_descriptor(adapter_id)`.

There is **no** separate shared specs helper module comparable to `specs_helpers.py` for apps; the “helper” logic and the SDK’s public adapter-metadata API are **the same file**.

### Call sites today

| Surface | Module / location | Role |
|--------|-------------------|------|
| SDK | `urban_platform/sdk/adapters.py` | Implements loading + public functions |
| API | `urban_platform/api/core_adapters.py` | `/adapters` and `/adapters/{adapter_id}` call SDK list/get |
| CLI | `tools/airos_cli.py` (`adapters list`, `adapters show`) | Uses SDK (`air_sdk.list_provider_adapter_descriptors`, `get_provider_adapter_descriptor`) |

Contrast with apps: `specs_helpers.py` is shared; `sdk/apps.py` is a thin wrapper; API imports the helper (via `app_descriptors.py`). Adapters currently omit that middle “specs helper” layer.

## Proposed Shared Helper Shape

A future shared helper would **mirror** `specs_helpers` responsibilities for adapter descriptors:

1. **Discover** all `*.yaml` / `*.yml` files under `specifications/provider_adapters/`.
2. **Parse** with `yaml.safe_load` only (no execution).
3. **Optionally validate** each document against `provider_adapter_descriptor.v1.schema.json` using the same manifest-driven schema resolution as today.
4. **Expose** stable functions such as:
   - `load_all_provider_adapter_descriptors_from_specs(*, validate: bool = True) -> list[dict]`
   - `get_provider_adapter_descriptor_from_specs(adapter_id: str, *, validate: bool = True) -> dict | None`
5. Apply a small **sanitization** step for API safety if needed (analogous to `_sanitize_app_descriptor` — today adapter sanitization is effectively passthrough).

**Hard constraints (unchanged):**

- **Read-only metadata:** no dynamic plugin loading, no interpreting descriptors as executable code, no runtime connector invocation from descriptor loading.
- Connector execution remains wherever it already lives (e.g. reviewed builders / registry paths — **out of scope** for this helper).

## Intended Callers and Layering

If implemented, the helper would be the **single place** for governed YAML → dict loading + optional validation. Intended consumers:

1. **`urban_platform/sdk/adapters.py`** — thin public SDK functions delegating to the helper (parallel to `sdk/apps.py` ↔ `specs_helpers`).
2. **API** — e.g. `core_adapters.py` continues to call SDK list/get; alternatively API could import the helper only indirectly via SDK to preserve one outward pattern (either approach is fine as long as behavior stays aligned).
3. **CLI** — `tools/airos_cli.py` adapter commands keep using the SDK, which would delegate to the helper.

**Constraints for any refactor:**

- **No intentional observable behavior change** in the first iteration (same summaries on `/adapters`, same CLI output shape, same skip-on-error semantics unless explicitly revised).
- **No relocation** of governed specs — `specifications/provider_adapters/` stays put.
- **Backward-compatible imports** — existing `urban_platform.sdk.adapters` entry points should remain stable for callers.

## Non-Goals / Deferrals

This design explicitly **does not** cover:

- Implementing or refactoring code in this task / document.
- Changing how adapters are **executed** at runtime (still not descriptor-driven execution).
- Repository restructuring beyond optionally adding one helper module or a scoped extension to `specs_helpers.py`.
- New provider contracts, new adapter descriptors, or schema relaxations.
- Weakening provenance, safety fields, or conformance posture.

## Suggested Implementation Steps (Future Work)

If maintainers adopt this direction, a practical sequence:

1. Add a dedicated helper module (e.g. `urban_platform/sdk/specs_helpers_adapters.py`) **or** extend `specs_helpers.py` in a **narrowly scoped** way with adapter-specific functions and manifest keys clearly separated from app descriptor logic.
2. Refactor `urban_platform/sdk/adapters.py` to delegate list/get/IDs to the helper without changing public signatures or return shapes.
3. Confirm API (`core_adapters.py`) and CLI (`tools/airos_cli.py`) still route through the SDK only (or adjust minimally if a maintainers decide API should call the helper directly — keep one story for tests).
4. Add tests mirroring the apps split:
   - Helper loads expected fixture descriptors and validates.
   - SDK list/get matches helper output (same idea as `tests/test_sdk_app_descriptor_helper.py`).
   - Optional: `/adapters` responses consistent with SDK summaries (parallel to app descriptor API tests).

Any implementation must pass the project’s usual verification (`pytest`, `python main.py --step conformance`, supervisor review when applicable) and should preserve current behavior unless a change is explicitly specified and reviewed.

---

*This note is documentation only; it does not change runtime behavior.*
