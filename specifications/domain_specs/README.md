# Domain Specifications (stubs, v1)

Domain specifications define **domain-specific semantics** on top of AirOS canonical platform objects.

They are intentionally separate from:

- **Provider contracts** (`specifications/provider_contracts/`): what upstream systems send
- **Platform objects** (`specifications/platform_objects/`): canonical internal objects
- **Consumer contracts** (`specifications/consumer_contracts/`): what dashboards/APIs/SDKs consume

Domain specs answer questions like:

- What variables exist in this domain, and in what units?
- What thresholds/categories define risk or priority?
- What safety gates must pass before outputs are used operationally?
- What provenance and source reliability requirements are mandatory?
- What decision packet profile and review prompts are required?
- What dashboard consumer requirements must be met by consumer contracts?

## File structure

- `domain_spec_template.v1.yaml`: authoring template
- `air_quality.v1.yaml`: PM2.5 reference application (H3, stations, weather, optional fire, OSM; CPCB_PM25_ONLY; decision packets; documented)
- `flood_risk.v1.yaml`: flood risk + waterlogging + drainage assets (stub)
- `property_buildings.v1.yaml`: phased built-environment change + field review; Phase 1 open-data MVP before optional municipal integrations; see `product_delivery_phases` and `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md` (documented)
- `water_operations.v1.yaml`: water supply/network operations (stub)

## Non-negotiable principle

**Do not add domain-specific variables, thresholds, categories, or decision packet extensions in code** unless they exist in a domain spec under this folder.

## Conformance (lightweight)

The conformance step should validate that every `*.v1.yaml` domain spec contains the required top-level keys:

- `domain_id`, `version`, `status`, `purpose`
- `target_actors`, `supported_decisions`
- `canonical_entities`, `observations`, `features`
- `allowed_variables`, `units`, `thresholds_or_categories`
- `safety_gates`, `provenance_requirements`, `source_reliability_requirements`
- `decision_packet_profile`, `dashboard_consumer_requirements`
- `human_review_prompts`, `field_verification_requirements`
- `blocked_uses`, `open_questions`

If conformance does not enforce this yet, treat it as a required TODO before expanding beyond stubs.

