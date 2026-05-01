# Specs-First Development (AirOS)

AirOS is a **specs-first urban intelligence platform**.

Specifications are not “documentation after the fact”. They are the **contracts** that govern:

- provider inputs (connectors, edge publishers, file ingestions)
- canonical platform objects (shared across domains)
- domain semantics (interpretation, thresholds, safety gates)
- consumer outputs (dashboards, APIs, SDKs, reports, decision packets)

## Why specs-first?

AirOS is intended to support many city-management use cases across domains:

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

Specs-first keeps multi-domain development interoperable and safe:

- consistent data shapes across connectors and dashboards
- explicit provenance and reliability semantics
- clear interpretation rules (units, thresholds, categories)
- predictable consumer payloads and warnings
- mandatory conformance gates before merge

## Specification families (contracts)

### 1) Provider contracts

**Provider contracts** define what external systems are allowed to send into AirOS.

Examples:

- air-quality station observations
- rainfall/river/pressure sensor feeds
- traffic speed feeds
- property registry extracts
- building permits/footprints
- camera people-count feeds (privacy-preserving)

Provider contracts must define (at minimum):

- provider identity + source system
- timestamps + timezone expectations
- spatial reference (coordinates and/or entity reference)
- variable names + units
- value types and valid ranges (when applicable)
- quality flags and missingness semantics
- provenance (source, method, license, transformations)

Location: `specifications/provider_contracts/`

### 2) Platform object specifications (canonical objects)

**Platform object specs** define canonical internal objects shared across domains.

Examples:

- `Observation`
- `Entity`
- `Feature`
- `Event`
- `Asset`
- `Boundary`
- `SourceReliability`
- `DecisionPacket`
- `ReviewerAction`

Canonical objects should be domain-neutral wherever possible.

Location: `specifications/platform_objects/`

### 3) Domain specifications (semantics and safety)

**Domain specs** define domain-specific semantics and constraints.

Examples:

- PM2.5 breakpoint categories
- flood-risk levels
- water-pressure thresholds
- traffic congestion levels
- building/property classifications
- heat-risk thresholds
- sanitation service levels
- decision packet prompts for specific domains

Domain specs may define:

- allowed variables and units
- thresholds, categories, severity scales
- domain feature profiles
- domain safety gates (what must be true before a recommendation is allowed)
- review questions and verification guidance

Location: `specifications/domain_specs/`

### 4) Consumer contracts (dashboards, APIs, SDKs, reports)

**Consumer contracts** define what downstream consumers can rely on.

Examples:

- dashboard summary payload
- map layer payload
- API response
- SDK response
- decision packet format
- field verification task payload
- public report payload

Consumer contracts must define:

- required vs optional fields
- allowed values and enums
- provenance + reliability fields required
- confidence/uncertainty fields required
- user-facing warning requirements (especially for synthetic/low-confidence cases)
- consumer safety constraints

Location: `specifications/consumer_contracts/`

## Mandatory conformance (non-negotiable)

Conformance is mandatory for:

- provider inputs
- platform objects
- domain profiles/specs
- consumer outputs

No provider or consumer is “done” unless conformance passes.

Run:

```bash
python main.py --step conformance
```

## Development sequence for a new use case (required)

When adding a new use case, AirOS requires the following order:

1. **Define** the use case (actor → decision → operational question)
2. **Identify** data sources and the provider contracts required
3. **Define/reuse** canonical platform objects and mapping rules
4. **Define/reuse** domain specifications for any domain-specific semantics
5. **Define/reuse** consumer contracts for all outputs (dashboards/APIs/SDKs/reports/decision packets)
6. **Register** the specs in the specifications manifest
7. **Add/extend conformance checks**
8. **Implement** connectors/pipeline/model/decision packets
9. **Develop dashboards** strictly from consumer contracts
10. **Run conformance** and attach evidence to the PR

## Dashboards are built from consumer contracts

Dashboards must not consume ad-hoc, undocumented payloads.

Hard rule: **do not implement a dashboard payload without a consumer contract**.

## Human review and decision packets

AirOS outputs are decision support, not automatic operational truth.

For decisions that can cause real-world action, AirOS should produce **decision packets** that bundle:

- evidence (observations/features/events/assets used)
- provenance (sources, transformations, synthetic flags)
- reliability status and issues (source health signals)
- confidence/uncertainty
- recommended next actions and explicit “do not act” conditions
- verification checklist (what must be confirmed in the field)

Hard rule: **do not treat synthetic or low-confidence data as operational truth**.

## PR acceptance criteria (minimum)

A PR is not acceptable unless it demonstrates:

- **Specs-first**: required specs exist (provider/platform/domain/consumer as applicable)
- **No bypass of canonical objects**
- **No weakening of safeguards** (provenance/reliability/human-review/conformance)
- **Conformance evidence**: `python main.py --step conformance` passes

## Policy source of truth

The machine-readable policy lives in:

- `specifications/spec_policy.yaml` (canonical policy name)
- `specifications/specs_policy.yaml` (legacy filename, kept aligned)

