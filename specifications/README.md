# Specifications (v1)

Machine-readable contracts are grouped into **provider ingestion**, **platform objects**, **consumer outputs/APIs**, **network coordination envelopes**, and **OpenAPI stubs**. The goal is to keep ingestion, normalization surfaces, dashboards/APIs, and cross-node interoperability contracts stable via conformance testing *without renaming runtime pipeline fields casually*.

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

- **Network contracts** (`network_contracts/`)
  - **`message_envelope.v1`** — domain-agnostic **routing envelopes** connecting **AirOS nodes** (`schema_ref` + `payload_ref` / hash; no embedded domain payloads). Separate **transports** (email/API/queues) attach around this shape per `docs/CROSS_AGENCY_COORDINATION_LAYER.md`.
  - The Network Layer is **protocol-like**: **contract-aware** and **policy-oriented**, never a substitute for **domain specs** or **agency decisions**.

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
- **Network envelopes validate interoperability metadata only—not domain semantics.** Payload validity is enforced against the **`schema_ref`** contract outside the envelope.

## Domain specifications (`domain_specs/`)

YAML domain specs describe actors, variables, safety gates, and **integration phasing**. For example, `property_buildings.v1.yaml` separates **`open_data_inputs`** (Phase 1 MVP) from **`authorized_municipal_inputs`** (later-stage partner integrations). Existing provider JSON Schemas for registry or permit feeds **remain valid** for authorized integrations; they are not removed when a domain is open-data-first.

## Conformance audit (recommended)

From the **repo root**:

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

From the **repo root**:

```bash
python -m pytest -q
```
