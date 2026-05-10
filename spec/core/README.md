# AirOS Core — Specification Index

The Core component is the operating layer of the AirOS stack. It owns the only persistent state in the system and defines the contracts that Drivers and Apps must honour.

| Document | What it specifies |
|----------|------------------|
| [KNOWLEDGE_STORE.md](KNOWLEDGE_STORE.md) | Required tables, deduplication semantics, write interface, read interface, temporal semantics |
| [SPATIAL_MODEL.md](SPATIAL_MODEL.md) | H3 grid, resolution requirements, four raw-to-H3 assignment methods, coordinate reference system |

| [RULES_REGISTRY.md](RULES_REGISTRY.md) | Threshold configuration contract, city-level override format, hot-reload requirement, built-in defaults |
| [SCHEDULER.md](SCHEDULER.md) | Cadence orchestration contract, watermark semantics, two-pool sweep algorithm, sweep status |
