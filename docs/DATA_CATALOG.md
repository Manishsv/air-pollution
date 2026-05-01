# AirOS Data Source Catalog

Note: the canonical, specs-first version of this document is `docs/DATA_SOURCE_CATALOG.md`. This file is kept for backward compatibility and may be removed later.

This catalog tracks candidate data sources for AirOS use cases.

Each data source must be evaluated for:
- Domain
- Geography
- Coverage
- Update frequency
- License
- Access method
- API availability
- Data format
- Reliability
- Cost
- Privacy risk
- Connector priority
- Use cases enabled

## Open-source and open-data first

Prefer:
- OpenStreetMap
- Open-Meteo
- OpenAQ
- NASA FIRMS
- Copernicus datasets
- Sentinel satellite products
- Landsat
- SRTM / other DEM sources
- GTFS feeds where available
- Public government open-data portals
- Open building footprints where license permits
- Public complaint datasets where available
- Community-mapped datasets

## Connector evaluation

Before implementing a connector, create a connector research note with:

1. Source name
2. URL / documentation
3. License
4. API details
5. Example payload
6. Update frequency
7. Fields available
8. Mapping to AirOS canonical objects
9. Risks
10. Implementation plan