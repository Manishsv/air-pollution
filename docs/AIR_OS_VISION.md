# AirOS Vision

AirOS is a **specs-first, multi-domain urban intelligence platform** for helping city actors understand, manage, and improve urban systems.

The long-term goal is to support multiple city-management use cases across domains including:

- air quality
- flood
- water
- traffic
- property
- buildings
- heat
- crowd
- sanitation
- public assets
- emergency response
- urban planning

AirOS is not a monolithic application for one department. It is a shared city intelligence layer that:

- connects data sources via connectors
- standardizes data into canonical platform objects
- enforces provenance, reliability, and conformance
- supports feature generation, models/rules, and decision-support
- produces actor-specific consumer outputs (dashboards, APIs, SDK responses, decision packets)

## Core objective

Help different city actors make better decisions by giving them **reliable, explainable, and actionable intelligence** about the state of the city — with explicit uncertainty and safeguards.

## Specs-first is a platform guarantee

AirOS development is **specification-driven**:

- Provider inputs must conform to **provider contracts**
- Internal representations must conform to **canonical platform objects**
- Domain semantics must conform to **domain specifications**
- Dashboards/APIs/SDKs/reports must conform to **consumer contracts**

Conformance is **mandatory**. A capability is incomplete unless conformance passes.

See `docs/SPECS_FIRST_DEVELOPMENT.md` and `specifications/spec_policy.yaml`.

## Closed-loop decision support (human-in-the-loop)

AirOS is designed as a **closed loop**:

1. ingest + standardize city signals
2. assess provenance + source reliability
3. build reusable features
4. produce model/rule outputs with uncertainty
5. generate **decision packets** (evidence + caveats + recommended checks)
6. humans review and decide
7. outcomes are measured and fed back into models/playbooks

**Operational action requires human review** and often field verification.

## Actors (decision-driven)

AirOS should support multiple actor groups:

- City administrators / commissioners
- Ward officers
- Department engineers (water, stormwater, roads, buildings, sanitation, assets)
- Emergency response teams
- Urban planners
- Environmental officers
- Traffic police
- Water utility operators
- Building and property departments
- Field inspectors
- Elected representatives
- Citizens and civil society organizations
- Researchers and data scientists
- Private ecosystem participants

## Platform principles

1. Multi-domain by design (shared platform, multiple applications)
2. Specs-first and contract-based integration
3. Open-source and open-standard first (when feasible)
4. Provenance, reliability, and auditability are first-class
5. Human-in-the-loop decision support with decision packets
6. Field verification before operational action when confidence is low
7. Separation of data infrastructure from use-case applications
8. Reuse canonical objects: `Entity`, `Observation`, `Feature`, `Event`, `Asset`, `Boundary`, `DecisionPacket`, `Action`
9. Connector-driven integration with public, open, government, sensor, and community sources
10. Dashboards must support **specific actors and decisions**, not generic visualization

## What every use case must define (spec-driven)

Each use case must specify:

1. actor and decision
2. operational questions and risk posture (what is safe to recommend vs only verify)
3. provider contracts and data sources
4. mapping to canonical platform objects
5. domain semantics (variables, units, thresholds, categories, safety gates)
6. consumer contracts (dashboard payloads, APIs/SDK outputs, decision packets, reports)
7. human review workflow and decision packet contents
8. acceptance criteria including **conformance passing**
