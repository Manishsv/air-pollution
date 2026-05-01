## Specs-first rule

AirOS follows a specs-first architecture.

All development must start from specifications. Code must conform to platform specs and domain specs.

Before implementing any connector, pipeline, model output, dashboard, API, SDK method, or decision-support workflow, the agent must check whether the required specification exists under `specifications/`.

If the required specification does not exist, the agent must first propose or add the specification before writing application code.

## Mandatory conformance

Conformance is mandatory for both:

1. Data providers
   - external feeds
   - file uploads
   - sensors
   - edge devices
   - government systems
   - public/open data sources

2. Data consumers
   - dashboards
   - SDK responses
   - APIs
   - decision packets
   - analytics outputs
   - downstream applications

No provider or consumer should be considered complete unless it passes conformance validation.

## Specification families

Every use case should consider four specification families:

1. Provider contracts
   Define the raw or source-specific payloads accepted from external providers.

2. Platform object contracts
   Define normalized internal objects used across domains, such as Entity, Observation, Feature, Event, Asset, SourceReliability, DecisionPacket, and Action.

3. Domain specifications
   Define domain-specific extensions, profiles, variables, thresholds, interpretation rules, and decision semantics.

4. Consumer contracts
   Define what dashboards, APIs, SDKs, reports, decision packets, and downstream apps are allowed to consume.

## Required development sequence

When adding or changing a capability, follow this order:

1. Identify the use case, actor, and decision.
2. Identify required provider, platform, domain, and consumer specs.
3. Add or update specs under `specifications/`.
4. Register specs in the specification manifest.
5. Add or update conformance checks.
6. Implement connector or processing code.
7. Normalize data to platform objects.
8. Validate provider inputs and consumer outputs.
9. Update dashboard/API/SDK only after specs exist.
10. Run conformance audit.
11. Attach conformance evidence to the PR.

## Non-negotiable rules

- Do not implement a new data source without a provider contract.
- Do not create a new dashboard payload without a consumer contract.
- Do not add a domain-specific field without defining it in a domain spec or profile.
- Do not bypass platform object normalization.
- Do not treat synthetic or low-confidence data as operational truth.
- Do not merge a change if conformance fails.