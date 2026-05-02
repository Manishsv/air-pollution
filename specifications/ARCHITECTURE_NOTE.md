# Contract-family architecture (worked examples: air pollution + crowd)

This repository keeps data contracts split into **four families** so we can evolve the platform without breaking integrations. Each family validates a different boundary.

## 1) Provider contracts

**Provider contracts validate how external data enters the platform.**

They describe the *raw* payloads we expect from upstream sources (before normalization):

- source identity (`provider_id`, `source_name`, `source_type`)
- time (`timestamp`)
- location (`geometry` or `latitude`/`longitude`) where applicable
- what was measured (`observed_property` or `feature_type`)
- measurement values (`value`, `unit`)
- quality + provenance (`quality_flag`, `provenance`)
- license + metadata (`license`, `source_metadata`)

Examples in this repo:

- Air quality observations (CPCB/OpenAQ-derived)
- Weather observations
- Fire events
- Building footprints
- Road network
- Video camera people-count feed (privacy-first; **counts only**, no media persisted)

## 2) Platform object contracts

**Platform object contracts validate normalized internal data.**

Once data passes through connectors/normalizers, we convert it into a small set of canonical objects that the platform can reuse across domains (air quality, traffic, flood, heat, crowd, …).

Examples:

- **Observation**: a normalized measurement row (who/where, when, value/unit, source, quality flag)
- **Entity**: a thing in the world (grid cell, sensor, camera, building, road segment, …)
- **Feature**: a derived attribute tied to a spatial unit (static or time-varying)
- **Event**: a spatiotemporal occurrence (e.g., a fire)
- **Source reliability**: per-entity reliability signals used for quality gates, audit summaries, and downstream weighting

## 3) Consumer contracts

**Consumer contracts validate what apps and dashboards consume.**

These contracts define the “product surface area”: what downstream users can rely on. They are usually:

- pipeline outputs written to `data/outputs/`
- payloads returned by APIs/SDKs
- artifacts shown in dashboards/review workflows

Examples:

- Decision packets (core + air-quality profile)
- Recommendations response wrapper
- Observation/Feature/Source-reliability response wrappers

## 4) OpenAPI contracts

**OpenAPI contracts describe provider ingestion APIs and platform consumer APIs.**

- Not JSON Schema validation of instances
- Machine-readable API definitions for docs/client generation/future HTTP services

## End-to-end flow (air quality / PM2.5)

**CPCB/OpenAQ** → **provider AQ feed contract**  
→ **connector** (fetch/parse)  
→ **Observation platform object** (normalized rows)  
→ **source reliability** (per-entity signals/summary)  
→ **observation store** (`data/processed/observation_store.parquet`)  
→ **feature store** (`data/processed/feature_store.parquet`)  
→ **forecast model** (training/inference)  
→ **air-quality decision packet consumer contract** (`data/outputs/decision_packets.json`)  
→ **review dashboard** (Air Pollution tab, via SDK)

## End-to-end flow (crowd / people_count, edge inference)

This repo supports a privacy-first crowd signal: **people_count**.

**Laptop camera + YOLO (edge)**  
→ compute a count for the **last 5 seconds** and publish every **5 minutes** (Option A)  
→ write provider payloads as JSONL: `data/edge/video_camera_people_count.jsonl`  
→ validate against provider contract: `specifications/provider_contracts/video_camera_people_count_feed.v1.schema.json`  
→ ingest JSONL → **Observation** rows and persist into `data/processed/observation_store.parquet`  
→ SDK/API: `get_observations(variable="people_count")`  
→ review dashboard (Crowd tab)

## Conformance as a safety rail

- `python main.py --step conformance` runs a conformance audit and writes:
  - `data/outputs/conformance_report.json`
- The dashboard reads conformance output via the SDK in “Technical: Data Contracts”.

## Repository code layout: `src/` vs `urban_platform/` (current state and migration)

This section clarifies **where code lives today** and **where new work should go**, so contributors and agents do not split logic across the wrong layers.

### Current state

- **`main.py`** loads config from `src.config` and, for the air-quality reference path, calls **`urban_platform.applications.air_pollution.pipeline.run_air_pollution_pipeline`**.
- That pipeline module **delegates orchestration to the legacy** **`src.pipeline.run_pipeline`** implementation (documented in code as incremental migration).
- **`src/`** holds the **original MVP air-quality reference**: orchestration, boundary/grid/OSM helpers, AQ and weather ingestion (where not yet moved), feature engineering, baseline models, recommendations, visualization helpers, sensor siting, and related utilities. It remains **in use** and **backward compatible** until deliberately migrated.
- **`urban_platform/`** is the **target platform package** for reusable **connectors**, **fabric** (stores), **processing** (features), **models**, **decision_support** (quality gates, packets), **applications** (contract-shaped payloads per domain), **SDK/API**, and **conformance runtime** under `urban_platform/specifications/*.py`. New vertical slices (e.g. flood, property/buildings) already follow this layout.

### Ownership map

| Location | Role |
|----------|------|
| **`src/`** | **Legacy AQ reference pipeline** — historical MVP modules still invoked via `urban_platform.applications.air_pollution.pipeline` delegation. Maintain for compatibility during migration. **Do not** add new cross-domain stacks or new domains here. |
| **`urban_platform/connectors/`** | **Canonical** provider fetch/ingest; must align with `specifications/provider_contracts/`. |
| **`urban_platform/processing/`** | **Canonical** reusable and domain-specific transforms / feature builders. |
| **`urban_platform/applications/`** | **Canonical** contract-shaped application outputs (dashboard payloads, decision/review packets, field tasks) and thin domain entrypoints. |
| **`urban_platform/specifications/`** | **Conformance implementation** (audit, engine, validators). It **loads** schemas and manifest from **root** `specifications/` only — no second copy of contract files. |
| **Root `specifications/`** | **Source of truth** for provider contracts, platform objects, domain YAML, consumer contracts, examples, and manifest. |
| **`review_dashboard/`** | **Presentation only** — consume via `urban_platform/sdk`; do not add domain risk logic or new payload shapes here. |
| **`tools/ai_dev_supervisor/`** | Local governance and agentic guardrails (conformance probe, maturity, optional dashboard checks). |
| **`data/`** | **Generated local runtime artifacts** (parquets, GeoJSON, HTML, JSON outputs). Not the contractual or semantic source of truth. |

### Migration principle

- **New domains and shared platform behavior** belong under **`urban_platform/`**, following the vertical-slice pattern in `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`. **Do not** grow new domain logic under `src/`.
- **Existing AQ code** may stay in `src/` until a **deliberate, incremental** move; each step should remain **test- and conformance-protected**.
- **Dashboards** must consume **contract-shaped** payloads from **`urban_platform/applications/`** (and SDK/API), not re-encode domain rules in Streamlit.

### Suggested air-quality migration sequence (documentation only — not a commitment to schedule)

1. **Inventory** `src/` modules and map each to a target home under `urban_platform/` (connector vs processing vs application vs decision_support).
2. **Identify** canonical platform equivalents (Observation paths, feature stores, decision packets) already provided by `urban_platform/` vs gaps to extend.
3. **Migrate provider-facing pieces first** (connectors + normalization + tests) so ingest matches existing contracts.
4. **Migrate processing / features** next (pure functions or fabric-backed pipelines with tests).
5. **Migrate application-level** payload and decision-packet generation next (consumer schema parity, dashboard unchanged in contract terms).
6. After **each** bounded change: run **`python main.py --step conformance`** and **`python -m pytest -q`** (and CI when enabled).
7. **Remove or freeze** legacy `src/` paths only when **parity** is demonstrated and callers no longer need delegation.

## How to add a new use case

When adding a new hazard/modality (traffic, flood, heat, crowd, …):

- **Define provider contracts** if you need new incoming data sources or a new feed shape.
- **Reuse platform objects** wherever possible so ingestion/normalization stays consistent across domains.
- **Define a consumer profile** (strict consumer schema) only when the output shape stabilizes.
  - Early on, prefer domain-neutral cores and keep domain-specific blocks flexible until naming settles.

