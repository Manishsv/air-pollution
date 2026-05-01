# Output specifications (v1)

Machine-readable contracts for **urban sensing** pipelines (air quality, traffic, flood, heat, noise, …). **Conformance tests** load JSON Schema files and fail CI when a **declared profile** drifts without a version bump.

## Domain-neutral vs profile schemas

- **`urban_decision_packet_core`** — Portable **decision packet** shell: identifiers, H3 location, human review fields, and **opaque** `prediction` / `provenance` / `evidence` objects. Use this when adding a new hazard so dashboards and APIs can share structure before field names stabilize.
- **`decision_packet_air_quality`** (alias **`decision_packet`**) — **Strict profile** for the current PM2.5 MVP (India category bands, AQ-specific evidence keys, weather/fire hooks). Breaking changes here should bump `v2` or add a new profile file, not silently edit v1.
- **`data_audit` / `provenance_summary` (v1)** — Still **named for the AQ rollout** (`pm25`, stations, cells). Reuse the *ideas* (coverage, interpolation, gates); for other domains, add parallel schemas (e.g. `data_audit.profile.flood.v1.schema.json`) and register them in `manifest.json` when those pipelines exist.

## Layout

- `json_schema/v1/` — JSON Schema (draft 2020-12): `*.schema.json` and `*.profile.*.v1.schema.json` for strict domains.
- `manifest.json` — maps artifact id → schema path + stability tier.

## Stability tiers

- **Stable** — required keys enforced for that artifact; optional fields via `additionalProperties` where noted.
- **Documented** — minimal required subset at the root; extensions allowed.

## Running conformance tests

From `air_quality_mvp/`:

```bash
python -m pytest tests/test_conformance_schemas.py -q
```

## Evolving the spec

1. Prefer **additive** optional properties under the same profile version.
2. New domain with different shapes: add **`decision_packet.profile.<domain>.v1.schema.json`**, register in `manifest.json`, and add fixtures + `assert_conforms(..., schema_name="decision_packet_profile_<domain>")` tests.
3. Breaking renames: new directory **`json_schema/v2/`** and manifest `spec_version` / paths.

## Relationship to `urban_platform.standards`

Tabular **observation** tables are validated in code (`validate_observations`, …). JSON Schemas here cover **serialized JSON artifacts** under `data/outputs/` and decision packet files.
