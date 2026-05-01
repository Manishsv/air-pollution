## AirOS coding-agent rules (specs-first, mandatory conformance)

AirOS is a **specs-first** multi-domain urban intelligence platform.

**All development must start from specifications** under `specifications/`. Provider inputs, canonical platform objects, domain semantics, and consumer outputs **must conform** to those specifications.

If the relevant spec does not exist yet, **stop implementation and add/update the spec first**.

### Non-negotiable rules

- **Do not implement a connector without a provider contract.**
- **Do not implement a dashboard payload without a consumer contract.**
- **Do not add domain-specific fields without a domain specification.**
- **Do not bypass canonical platform objects.**
- **Do not weaken provenance, reliability, conformance, or human-review safeguards.**
- **Do not treat synthetic or low-confidence data as operational truth.**
- **Run conformance before considering the task complete.**

### Specs to check before writing code

AirOS uses four spec families. Every new capability must map to these:

- **Provider contracts** (`specifications/provider_contracts/`): what external providers are allowed to send.
- **Platform objects** (`specifications/platform_objects/`): canonical internal objects shared across domains (e.g., `Observation`, `Entity`, `Feature`, `Event`, `Asset`, `DecisionPacket`).
- **Domain specifications** (`specifications/domain_specs/`): domain semantics (variables, units, thresholds, categories, safety gates, review prompts).
- **Consumer contracts** (`specifications/consumer_contracts/`): what dashboards/APIs/SDKs/reports/decision packets are allowed to consume.

### Required development sequence (for any new use case)

1. **Define**: use case → actor → decision to support.
2. **Specify**: provider contract(s) → platform object mapping → domain spec/profile → consumer contract(s).
3. **Register**: add/update spec entries in the manifest.
4. **Conformance**: implement or update conformance checks for the new/changed specs.
5. **Implement**: connectors, normalization, processing, models, decision packets.
6. **Deliver**: dashboards based on consumer contracts (not ad-hoc payloads).
7. **Verify**: run the conformance step and attach evidence to the PR.

### PR acceptance criteria (minimum)

A PR that changes behavior is not acceptable unless it includes:

- **Spec changes first** (when introducing a new provider/platform/domain/consumer surface)
- **No bypass of canonical objects** (normalization remains mandatory)
- **No weakening of safeguards** (provenance/reliability/human-review/conformance)
- **Conformance evidence**: `python main.py --step conformance` passes

### Further reading

- **Specs-first development**: `docs/SPECS_FIRST_DEVELOPMENT.md`
- **Vision**: `docs/AIR_OS_VISION.md`
- **Actor model**: `docs/ACTOR_MODEL.md`
- **Use-case roadmap**: `docs/USE_CASE_ROADMAP.md`
- **Data-source discovery**: `docs/DATA_SOURCE_CATALOG.md`
- **Machine-readable policy**: `specifications/spec_policy.yaml` (and `specifications/specs_policy.yaml`)

