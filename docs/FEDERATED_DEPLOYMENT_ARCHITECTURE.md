# Federated deployment architecture (AirOS)

AirOS is **node-first** and **federation-ready**. It does **not** assume one monolithic “city instance” where every agency shares a single deployment, database, or mandate. Indian urban governance often runs **multiple systems, vendors, and jurisdictions in parallel**—the platform architecture should match that reality without turning the **coordination fabric** into a **domain brain**.

This document anchors **AirOS Core**, **AirOS Node**, and the **AirOS Network Layer**, and lists **deployment patterns** used in the field.

**Related deep dives**

- [`docs/AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md) — agency-owned node identity, contracts, policies, maturity.  
- [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md) — Network Layer: domain-agnostic, contract-aware, policy-enforcing coordination; includes **email as a Phase 1 transport adapter**.  
- [`docs/CITY_PROFILE_TEMPLATE.md`](CITY_PROFILE_TEMPLATE.md) — lightweight **city-scoped** deployment context (insufficient alone; see below).

---

## Core architecture principle

| Layer | Responsibility |
|--------|----------------|
| **AirOS Core** | Shared **specifications**, **canonical platform objects**, **conformance**, **connectors**, **processing**, **contract-shaped application payloads**, **decision/review packets**, **field tasks**, **dashboards**, and **SDK/API**—the reusable product surface. |
| **AirOS Node** | A **deployed instance** of AirOS Core operated by or for an **agency** (or consortium) with explicit **jurisdiction**, **data ownership**, **enabled domains**, and **policies**. |
| **AirOS Network Layer** | **Optional**, **separately deployable**, **native** to AirOS architecture (not a separate product line). Routes **contract-shaped** messages between nodes with **authorization, audit, and provenance hooks**—like a **protocol/transport policy plane**, not a reasoning engine. |

**Separation rule:** the Network Layer must **not** interpret domain meaning (thresholds, hazard levels, enforcement rules). It validates **envelopes**, **contract references**, **policy**, and **delivery**; domain semantics live in **domain specs**, **applications**, and **agency workflows**.

---

## Federated deployment patterns

These are **organizational topologies**, not product SKUs. Any pattern may use standalone nodes only, or add the Network Layer where **cross-node** coordination is required.

1. **Single-agency node**  
   One agency runs an AirOS Node for its mandate (e.g. state pollution board for regional air observability). Others are not on-platform yet.

2. **Multi-agency city deployment**  
   Several agencies each run a **logical or physical** node (ULB, traffic police, utility, health). They may share hosting, or be isolated; **coordination** optional via the Network Layer.

3. **Multi-city agency deployment**  
   A state board or regional utility operates **one node** spanning **multiple cities** (multi-city jurisdiction)—data and decisions remain **agency-owned**, not “merged” into a foreign ULB node.

4. **State-level coordination deployment**  
   A thin **coordination** posture: many child nodes (cities/districts) and a state hub for **observability**, **packet exchange**, or **task handoff**—still **policy- and contract-bound**, not centralized domain override.

5. **Regional / corridor deployment**  
   Cross-ULB or metro-regional coordination (transport corridor, basin management, shared industrial zone) where **jurisdiction_refs** routinely span municipalities.

6. **Public transparency deployment**  
   A node (or federation gateway) emits **public-safe**, **consumer-contract-shaped** transparency feeds **without** exposing restricted operational systems—policy and classification enforced at envelope level.

Patterns can combine (e.g. multi-agency city + state observability hub).

---

## AirOS Core (what every node instantiation shares)

Conceptually includes:

- **`specifications/`** — provider, platform object, domain, consumer artifacts and manifest  
- **Canonical platform objects** and normalization discipline  
- **Conformance** (`python main.py --step conformance`)  
- **Connectors** and **processing** (when authorized for that node’s data)  
- **Application-layer** payload builders (**decision/review packets**, **field tasks**, dashboards) aligned to consumer contracts  
- **SDK/API** surfaces for sanctioned consumers  

Operational **enablement** (which connectors fire, which domains are on) is **node configuration**, not ad-hoc drift from specs.

---

## AirOS Node (deployment unit)

An **AirOS Node** is an agency-scoped deployment of Core: one **operator**, one dominant **trust boundary**, explicit **jurisdiction**, and controlled **incoming/outgoing contract traffic**. Nodes **own data and decisions**; the platform never implies a single metropolitan “God mode.”  
See **`docs/AGENCY_NODE_MODEL.md`** for structured fields (`node_id`, `agency_type`, jurisdiction, domains, contracts, policies, maturity).

Deployment modes include **standalone**, **shared-hosted**, **managed service**, or **federated participant**—the **architecture** stays the same; **governance** differs.

---

## AirOS Network Layer (coordination, not cognition)

Detailed behavior, message envelope vocabulary, permitted operations, forbidden domain logic, coordination patterns, and **Phase 1 email transport adapter** framing are documented in **`docs/CROSS_AGENCY_COORDINATION_LAYER.md`**.

Summary:

- **Optional** component for **interop** among nodes  
- **Domain-agnostic**, **contract-aware**, **policy-enforcing**  
- Understands envelopes, routing, authorization, acknowledgement, retries/audit—not PM2.5 or flood semantics  
- **Separately deployable** but **first-class** in the AirOS reference architecture  

---

## Future specifications (not implemented in this task)

When network-federation work begins, expect provider/consumer-style JSON Schemas (names indicative):

- `message_envelope.v1.schema.json`  
- `agency_node.v1.schema.json`  
- `network_participant.v1.schema.json`  
- `jurisdiction_registry.v1.schema.json`  
- `endpoint_catalog.v1.schema.json`  
- `data_sharing_policy.v1.schema.json`  
- `delivery_receipt.v1.schema.json`  
- `cross_agency_event.v1.schema.json`  
- `task_handoff.v1.schema.json`  
- `decision_packet_exchange.v1.schema.json`  
- `agency_response_status.v1.schema.json`  

Until those exist, **do not** implement ad-hoc cross-agency APIs in application code without specs.

---

## Forward deployment implications

Before designing integration, forward deployment engineers should map:

- **Agencies involved** and **who decides what**  
- **Jurisdictions** (city, multi-city, district, regional, state)  
- **Existing systems** and export habits  
- **Data each agency holds** vs **what it may publish**  
- **Decisions each agency owns** (legal/SOP reality)  
- **Consumer contracts** each side can honor  
- **The coordination problem** being solved (one-off report vs ongoing packet exchange)  
- **Whether a single node suffices** or a **Network Layer** (with explicit policy) is warranted  

This mapping complements but does not replace **specs-first** delivery per `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`.

---

## Relationship to the city profile template

A **city profile** (`deployments/templates/city_profile/`, `docs/CITY_PROFILE_TEMPLATE.md`) captures **city-scoped** priorities, data availability, and maturity. It is **useful but insufficient** for federation design.

Also plan for (in private deployment artifacts, future templates, or specs):

- **Agency profiles**  
- **Jurisdiction profiles**  
- **Deployment profiles** (standalone vs federated participant)  
- **Network participant profiles** (who may send/receive which message types)  
- **Cross-agency coordination profiles** (which patterns: event bus, task handoff, transparency feed)  

The Network Layer consumes **policy and contract references** from these profiles—it does not replace them.

---

## Air quality illustration (routing vs meaning)

A **hotspot decision packet** is produced by the **air-quality domain application** under **domain specs** and **consumer contracts**. The **Network Layer** may **route** copies or task handoffs to multiple **agency nodes** (pollution control board, ULB/sanitation, traffic police, building authority, health/education, city administrator). It does **not** decide what each agency must do; **human review** and **safety gates** remain mandatory.  
Full walkthrough: **`docs/CROSS_AGENCY_COORDINATION_LAYER.md` § Air pollution example**.
