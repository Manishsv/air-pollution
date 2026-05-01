# AirOS Data Source Catalog (specs-first)

This catalog tracks candidate data sources for AirOS use cases and the requirements for integrating them safely.

AirOS is **specs-first**. A data source is not “integrated” until it is backed by specifications and passes conformance.

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

