# AirOS Drivers — Specification Index

The Drivers component is the data acquisition and mapping layer. A Driver fetches raw data from one upstream source and writes H3-mapped signals to the Knowledge Store.

| Document | What it specifies |
|----------|------------------|
| [DRIVER_INTERFACE.md](DRIVER_INTERFACE.md) | Language-agnostic driver contract: identity fields, `fetch()`, `conformance_check()`, discovery, registry format, stability guarantee |
| [SIGNAL_SCHEMA.md](SIGNAL_SCHEMA.md) | Signal row structure, DATA_CONFIDENCE requirement, data quality tiers, signal naming convention, `signals.yaml` format |
| [CONFORMANCE.md](CONFORMANCE.md) | Gate rules (blocking vs non-blocking), load-time conformance check, result recording, bypass prohibition |
| [DOMAIN_CATALOGUE.md](DOMAIN_CATALOGUE.md) | The 14 canonical domains: risk vs structural classification, cadences, signal tables, cross-domain relationships |

**Reading order for a new Driver author:**
1. DRIVER_INTERFACE.md — understand what you must implement
2. SIGNAL_SCHEMA.md — understand what your output must look like
3. DOMAIN_CATALOGUE.md — find your domain's canonical signals (or define a new domain)
4. CONFORMANCE.md — understand how your output will be validated
