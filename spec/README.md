# AirOS Specification

> **This folder (`spec/`) contains narrative, normative design documents** — prose specifications
> that define what AirOS must do, why, and what the contracts between components are.
> Written for humans. If you want to understand the architecture, read these.
>
> For machine-readable schemas (JSON Schema, YAML domain specs used by validators),
> see [`../specifications/`](../specifications/).

---

**Version:** 1.0.0-draft  
**Status:** Draft  
**Published:** 2026-05

---

AirOS is an open specification for urban intelligence platforms. It defines the contracts, interfaces, data shapes, and safety posture that a compliant AirOS deployment must honour. It does not prescribe implementation language, database engine, LLM provider, or deployment topology.

The reference implementation — built in Python, backed by SQLite, deployed on a single machine or Docker cluster — lives at the repository root. It is one correct implementation of this specification. Others are possible.

---

## What this specification covers

AirOS defines four components and the contracts between them:

| Component | Spec section | What it governs |
|-----------|-------------|-----------------|
| **Core** | [`core/`](core/) | Knowledge Store, Spatial Model, Rules Registry, Scheduler |
| **Drivers** | [`drivers/`](drivers/) | Driver interface, signal schema, conformance gate, domain catalogue |
| **Apps** | [`apps/`](apps/) | App read/write contract, insight schema, safety posture |
| **Network** | [`network/`](network/) | Node model, message envelope, federation |

Each section is self-contained. An implementer building only Drivers needs only the `drivers/` section and the parts of `core/` that define the Knowledge Store write interface. An implementer building an App needs `apps/` and the parts of `core/` that define the read interface.

---

## What this specification does not cover

- How to implement the Knowledge Store internally (file-based, SQL, columnar — any works if it satisfies the interface contract)
- Which LLM provider to use for agents
- Specific upstream data sources (those are covered by domain-level provider contracts in [`../specifications/provider_contracts/`](../specifications/provider_contracts/))
- Deployment topology (single-node, multi-container, cloud — see reference deployment docs)

---

## Relationship to domain-level specifications

This stack specification sits above the domain specifications in [`../specifications/`](../specifications/). The domain specifications (provider contracts, consumer contracts, domain YAML policies, platform object schemas) are normative within this specification — they define *what* each domain's data looks like. This specification defines *how* components exchange that data.

```
AirOS Stack Specification (this document)
        │
        ├── Core: Knowledge Store, Spatial Model, Scheduler, Rules Registry
        ├── Drivers: Driver Interface, Signal Schema, Conformance, Domain Catalogue
        ├── Apps: App Contract, Insight Schema, Safety Posture
        └── Network: Node Model, Message Envelope, Federation
                │
                └── Domain Specifications (../specifications/)
                        ├── Domain specs (air_quality.v1.yaml, flood_risk.v1.yaml, …)
                        ├── Provider contracts (JSON Schema)
                        ├── Consumer contracts (JSON Schema)
                        └── Platform objects (observation, entity, feature, …)
```

---

## Notation

This specification uses RFC 2119 terminology:

- **MUST** / **MUST NOT** — absolute requirement / prohibition
- **SHOULD** / **SHOULD NOT** — strong recommendation with legitimate exceptions
- **MAY** — optional

Normative sections are marked **[NORMATIVE]**. Explanatory sections are marked **[INFORMATIVE]**.

---

## Versioning

This specification is versioned using Semantic Versioning 2.0.0:

- **Patch** (1.0.x): editorial corrections, clarifications that do not change conformance
- **Minor** (1.x.0): additive changes (new optional fields, new SHOULD requirements)
- **Major** (x.0.0): breaking changes to MUST requirements or data shapes

A conformant implementation at version 1.2.3 satisfies all requirements of versions 1.0.0 through 1.2.3.

---

## Contributing

Specification changes should be proposed as a pull request against the `spec/` directory. Each change MUST:

1. Identify whether it is a patch (editorial), minor (additive), or major (breaking) change
2. Update the `**Version:**` header in every affected document
3. Not remove or weaken a MUST requirement without a major version bump and migration note

Implementation changes that expose a gap in the specification should open a spec issue before changing code.
