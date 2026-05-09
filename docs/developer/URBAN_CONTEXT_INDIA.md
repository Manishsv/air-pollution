# Urban governance context — India (why AirOS is shaped this way)

AirOS is designed for **Indian urban governance**, where “the city” is rarely a single IT system or a single accountable owner. Understanding this context explains **specs-first**, **open-data-first**, and **forward-deployment-friendly** platform choices.

## Fragmentation across institutions

Urban outcomes depend on many actors that often **do not share a common data spine**:

- Urban local bodies (ULBs) and multiple wards
- Parastatals (water, transport, development corporations)
- Utilities (power, water, waste)
- State departments and pollution control boards
- Development authorities and planning bodies
- Traffic police and mobility agencies
- Disaster management cells and emergency responders

Responsibilities **overlap**; budgets and mandates **diverge**; and **data ownership** is distributed. AirOS assumes **coordination is hard by default**—integration is an achievement, not a precondition.

**Multi-node reality:** agencies may run **separate AirOS deployments** (logical or physical **nodes**)—city-level, multi-city, regional, or state-scoped. AirOS is **node-first and federation-ready**; it does **not** assume one monolithic municipal instance. Where agencies must exchange **contract-shaped** artifacts, an optional **AirOS Network Layer** provides **domain-agnostic**, **contract-aware**, **policy-enforcing** routing—not domain reasoning. See [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md) and [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md).

## Large, medium, and small cities differ materially

- **Large metros** may have GIS cells, open-data portals, and vendor relationships—but still face **siloed** operational systems and uneven quality.
- **Medium cities** may have partial digitalization, **ad hoc** exports, and **limited** API maturity.
- **Smaller ULBs** may rely on spreadsheets, paper workflows, and **infrequent** updates.

A single product rollout template will not fit. AirOS therefore favors a **reusable core** plus **local configuration** (domains enabled, connectors prioritized, review workflows tuned).

## Uneven data availability and limited integration capacity

- **Open and national/global** layers (OSM, weather, EO where licensed) are often the **fastest** path to a credible demo.
- **Authoritative municipal** systems (registry, permits, tax, cadastre) may be **politically sensitive**, **legally constrained**, or **technically inaccessible** early on.
- Agencies may lack staff to **sustain** integrations even when APIs exist.

**Open-data-first** value demonstration is not ideology alone—it is a **pragmatic** response to access and capacity reality. **Progressive adoption** means shipping observability and review-safe outputs **before** assuming deep enterprise pipes.

## Short tenures and institutional memory

Public officials and consultants **rotate**. Vendor contracts **churn**. Without durable artifacts, cities lose the “why” behind dashboards and models.

**Specifications** act as **coordination instruments**: they persist intent, safety boundaries, and consumer shapes across people and vendors. **Conformance** is the institutional memory that answers “does this still match what we agreed?”

## City-specific priorities

Two neighboring cities may rank **flood**, **air**, **heat**, or **mobility** differently. AirOS avoids a single forced domain order in code; the **roadmap** and **domain specs** express **local prioritization** while the **platform core** stays shared.

## Field verification and human review

Where signals are uncertain, interpolated, or socially sensitive, **field verification** and **human review** are first-class—not optional polish. Outputs are framed as **decision support** and **review candidates**, not as automatic government action.

## Implications for AirOS platform design

1. **Specs-first**: contracts and domain semantics are the stable interface across rotations and vendors.  
2. **Open-data-first phases**: demonstrate public value without assuming privileged municipal APIs on day one.  
3. **Progressive integration**: later-stage connectors require explicit contracts, governance, and consumer profiles.  
4. **Forward-deployment-friendly**: configuration, bounded slices, and agent-assisted iteration must be safe and repeatable.  
5. **Provenance and blocked uses by default**: trust is earned with transparency, not assumed from a logo on a slide.

For how the AI Centre of Excellence operationalizes this in the field, see [`docs/AI_COE_OPERATING_STRATEGY.md`](AI_COE_OPERATING_STRATEGY.md). For sequencing domains in product work, see [`docs/USE_CASE_ROADMAP.md`](USE_CASE_ROADMAP.md). For day-to-day engineering practice (layers, conformance, vertical slices), see [`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`](DOMAIN_DEVELOPMENT_PLAYBOOK.md) and the consolidated review [`docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`](reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md). For **agency nodes** and **cross-agency coordination** (including future network specs), see [`docs/AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md).
