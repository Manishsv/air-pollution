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

## How to add a new use case

When adding a new hazard/modality (traffic, flood, heat, crowd, …):

- **Define provider contracts** if you need new incoming data sources or a new feed shape.
- **Reuse platform objects** wherever possible so ingestion/normalization stays consistent across domains.
- **Define a consumer profile** (strict consumer schema) only when the output shape stabilizes.
  - Early on, prefer domain-neutral cores and keep domain-specific blocks flexible until naming settles.

