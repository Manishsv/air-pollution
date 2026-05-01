# Specifications (v1)

Machine-readable contracts are grouped into **three contract families** (plus OpenAPI stubs). The goal is to keep **provider ingestion**, **internal platform objects**, and **consumer outputs/APIs** stable via conformance testing *without renaming runtime pipeline fields*.

See also: [`ARCHITECTURE_NOTE.md`](ARCHITECTURE_NOTE.md) and [`../GETTING_STARTED.md`](../GETTING_STARTED.md).

## Contract families

- **Provider contracts** (`provider_contracts/`)
  - Validate **raw incoming** feeds from upstream systems.
  - Shape: provider metadata + records/events/features with timestamp + geometry (or lat/lon), observed_property/feature_type, value/unit, quality_flag, provenance, and license/source_metadata.

- **Platform object schemas** (`platform_objects/`)
  - Validate **normalized internal records**.
  - These align to `urban_platform.standards.schemas.py` canonical objects:
    - Observation, Entity, Feature, Event
    - Source reliability (per-entity reliability table)

- **Consumer contracts** (`consumer_contracts/`)
  - Validate what **applications/dashboards/workflows** consume.
  - Includes:
    - `urban_decision_packet_core` (domain-neutral shell)
    - strict profiles like air-quality decision packets
    - response wrappers for API-style payloads (`*_response.v1.schema.json`)

- **OpenAPI stubs** (`openapi/`)
  - Machine-readable API descriptions (not JSON Schema). These are versioned contracts for endpoint shapes and will be refined over time.

## Backward compatibility

The legacy schemas under `json_schema/v1/` remain the **canonical** files used by the runtime pipeline conformance validation today, and the manifest keeps the existing aliases working:

- `decision_packet`
- `decision_packet_air_quality`
- `decision_packets`
- `source_reliability`

## Rules

- **Provider contracts validate ingestion.**
- **Platform object schemas validate normalized data.**
- **Consumer contracts validate what applications see.**

## Conformance audit (recommended)

From `air_quality_mvp/`:

```bash
python main.py --step conformance
```

This writes a single report to:

- `data/outputs/conformance_report.json`

The report includes:

- schema validity (all contract-family JSON Schemas parse and are Draft 2020-12 valid)
- manifest hygiene (paths exist; `contract_type` is present)
- artifact validation (`data/outputs/*.json`)
- local API/SDK response validation (wrapped into consumer response envelopes where applicable)

## Running tests

From `air_quality_mvp/`:

```bash
python -m pytest -q
```
