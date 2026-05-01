# Specs-First Development in AirOS

AirOS is a specs-first urban intelligence platform.

The purpose of the specifications layer is to ensure that multiple city domains, data providers, models, dashboards, and applications can interoperate safely.

Specifications are not documentation after the fact. They are the contract that development must follow.

## Why specs first?

AirOS is intended to support many use cases across domains such as air quality, flood, water, traffic, property, buildings, heat, crowd, sanitation, assets, and emergency response.

Each domain may have different data sources and operational needs, but the platform must preserve common guarantees:

- consistent data structures
- known provenance
- reliability scoring
- validated provider inputs
- validated consumer outputs
- reusable platform objects
- safe decision-support semantics
- human review where required

## Specification layers

### 1. Provider specifications

Provider specs define what external systems are allowed to send into AirOS.

Examples:
- air-quality station observation feed
- weather feed
- camera people-count feed
- rainfall sensor feed
- property registry extract
- building footprint feed
- traffic speed feed
- water pressure sensor feed

Provider specs must define:
- provider identity
- source system
- timestamp
- location or entity reference
- observed property
- value and unit
- quality flag
- provenance
- license and metadata

### 2. Platform specifications

Platform specs define canonical internal objects.

Examples:
- Observation
- Entity
- Feature
- Event
- Asset
- Boundary
- SourceReliability
- DecisionPacket
- ReviewerAction

These specs should be domain-neutral wherever possible.

### 3. Domain specifications

Domain specs define domain-specific semantics.

Examples:
- PM2.5 breakpoint categories
- flood-risk levels
- water-pressure thresholds
- traffic congestion levels
- building/property classification
- heat-risk thresholds
- sanitation service levels

Domain specs may define:
- allowed variables
- units
- thresholds
- categories
- domain-specific feature profiles
- decision packet extensions
- recommended review questions
- safety gates

### 4. Consumer specifications

Consumer specs define what downstream consumers can rely on.

Examples:
- dashboard summary payload
- map layer payload
- decision packet
- field verification task
- API response
- SDK response
- public report

Consumer specs must define:
- required fields
- optional fields
- allowed values
- provenance requirements
- confidence fields
- user-facing warning requirements
- consumer safety constraints

## Mandatory conformance

Every provider input and consumer output must be validated.

A feature is incomplete until:

1. Specs exist.
2. Specs are registered in the manifest.
3. Conformance checks exist.
4. Tests or audit commands run successfully.
5. Evidence is attached to the PR.

## Development workflow

Every change should follow this flow:

```text
Use case → actor → decision → provider spec → platform object mapping → domain spec → consumer spec → conformance → implementation → dashboard/API → verification