# AirOS Data Source Catalog (specs-first)

This catalog tracks candidate data sources for AirOS use cases and the requirements for integrating them safely.

AirOS is **specs-first**. A data source is not “integrated” until it is backed by specifications and passes conformance.

For **workflow order** (read list, contracts, examples, tests, conformance), use **`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`**.

## What each data source must record

Each data source entry (even as a lightweight note) should capture:

- **Domain(s)**: air quality | flood | water | traffic | property | buildings | heat | crowd | sanitation | public assets | emergency response | urban planning
- **Geography**: city/region, boundary definitions
- **Coverage**: spatial and temporal coverage, missingness patterns
- **Update frequency**: realtime/near-realtime/batch, typical latency
- **Access method**: API, file export, scraping (discouraged), manual download
- **Format**: JSON/CSV/GeoJSON/Parquet, schemas, units
- **License & terms**: redistribution constraints, attribution, rate limits
- **Reliability risks**: staleness, outages, sensor drift, bias, known failure modes
- **Privacy & safety**: PII risk, aggregation requirements, retention constraints
- **Cost**: free/paid, quotas
- **Priority**: what use cases it unlocks and what decisions it can safely support

## Specs-first integration requirements (mandatory)

Before writing a connector or consuming a new source in pipelines/dashboards, ensure:

1. **Provider contract exists** (`specifications/provider_contracts/`)
2. **Canonical mapping exists** to platform objects (`specifications/platform_objects/`)
3. **Domain semantics exist** for domain-specific fields/interpretations (`specifications/domain_specs/`)
4. **Consumer contracts exist** for any payloads that will be produced/served (`specifications/consumer_contracts/`)
5. **Conformance passes** (`python main.py --step conformance`)

Hard rule: **do not implement a connector without a provider contract**.

## Open-source and open-data first (default preference)

Prefer (when fit-for-purpose and legally usable):

- OpenStreetMap
- Open-Meteo
- OpenAQ
- NASA FIRMS
- Copernicus datasets
- Sentinel satellite products
- Landsat
- SRTM / DEM sources
- GTFS feeds where available
- Public government open-data portals
- Open building footprints where license permits
- Public complaint datasets where available
- Community-mapped datasets

## Built-environment change (`property_buildings` domain — phased)

AirOS sequences **Phase 1 (open-data MVP)** before **later-stage authorized municipal** feeds. Provider contracts for registry/permit/tax may exist for future integration; they are **not** Phase 1 defaults. See `specifications/domain_specs/property_buildings.v1.yaml` (`open_data_inputs`, `authorized_municipal_inputs`, `integration_phasing`, `product_delivery_phases`), `docs/USE_CASE_ROADMAP.md`, and `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`.

### Property & Buildings — open-data-first (agent quick reference)

**Phase 1 defaults (low friction, no municipal assumption):**

- OSM building footprints  
- Open building footprint datasets where the **license** permits ingestion and agreed derivatives  
- Satellite-derived change signals and **Sentinel / Landsat-style** derived products (with seasonality / cloud QA)  
- Ward / administrative boundary layers  
- Roads and settlement context (e.g. `provider_road_network_feed`)  
- **Field verification results** (structured uploads under a dedicated provider contract)

**Later-stage authorized integrations (not Phase 1 requirements):**

- Municipal property registry, building permit systems, property tax assessment data, cadastral / parcel systems, and authority-only zoning when not published as open data.

### Phase 1 — open or externally obtainable (default)

| Source type | Examples | Notes |
| --- | --- | --- |
| Building geometry | OSM buildings; Microsoft/Google or other **openly licensed** footprint releases; satellite-derived building masks | License and derivative-use terms must be recorded per deployment. |
| Change signals | Sentinel-2, Landsat stacks (indices, change detection, bare-soil/build-up proxies) | Strong seasonality and cloud false positives; **not** permit detection. |
| Admin units | Ward boundaries (`ward_boundary_feed` or open government portals) | Aggregation unit for “high-change wards” and review queues. |
| Context | OSM roads (`provider_road_network_feed`), settlement outlines, **public** land-use/zoning polygons | Interpretation support; does not imply ownership. |
| Field verification uploads | Structured site-visit / ticket / photo metadata | Requires dedicated provider contract + privacy review; strengthens review loops only. |

**Consumer intent (Phase 1):** “Where does the built environment appear to have changed recently, and which areas may need field review?” — **not** tax, enforcement, or owner identification by default.

**Safety:** Treat all Phase 1 outputs as **change candidates** and **review prompts**; not legal records, permit violations, tax liabilities, ownership facts, or enforcement evidence.

### Later stage — authorized municipal (optional, post-value)

| Source type | Examples | Notes |
| --- | --- | --- |
| Registry & revenue | Property registry, tax assessment rolls | Partner agreements, access control, and stricter consumer profiles; see `authorized_municipal_inputs` in domain spec. |
| Permits & cadastre | Municipal permit system, cadastral parcels | Same safeguards: provenance, human review, blocked uses; no automated non-compliance from EO alone. |
| Authority zoning | Internal land-use layers not published as open data | Distinct from public zoning used in Phase 1. |

## Connector evaluation template (use before implementation)

Before implementing a connector, create a short research note containing:

1. Source name and owner
2. Documentation link(s)
3. License/terms summary (what we can/can’t do)
4. Access method (auth, rate limits, quotas)
5. Example payload(s) (sample responses/files)
6. Field inventory (including units and timestamps)
7. Expected update frequency and latency
8. Known reliability issues and failure modes
9. Privacy considerations and mitigations
10. Proposed **provider contract** (new vs reuse, location)
11. Mapping to **canonical platform objects** (which objects and fields)
12. Intended **consumer outputs** (which consumer contracts will be satisfied)
13. Conformance plan (how we will validate in `--step conformance`)

