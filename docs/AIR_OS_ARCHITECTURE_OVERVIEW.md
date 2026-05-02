# AirOS Architecture Overview

AirOS is **node-first**, **specs-first**, and **federation-ready**. It supports standalone agency/city deployments (**AirOS Nodes**) and optional cross-agency coordination through a **domain-agnostic, contract-aware, policy-enforcing** **AirOS Network Layer**.

This document provides **text diagrams** for contributors, forward deployment engineers, and coding agents.

## How to read this diagram

- **Specs are the source of truth**: contracts live under `specifications/` and are registered in `specifications/manifest.json`.
- **UI is presentation**: `review_dashboard/` must not contain domain risk logic or matching logic.
- **Domain applications emit contract-shaped outputs**: application payloads, decision/review packets, and field tasks are shaped by **consumer contracts**.
- **Network Layer routes envelopes, not meaning**: it handles envelope validation, routing, authorization context, delivery/ack metadata, and audit trails—**not** PM2.5 thresholds, flood levels, permit mismatch logic, enforcement rules, or other domain semantics.
- **Email is a transport adapter**: a practical Phase 1 carrier for low-frequency coordination; **not** the Network Layer itself.
- **Agencies retain decision authority**: AirOS outputs are decision support + review candidates; agencies and humans decide actions.

## 1) Full architecture (layers and components)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Users / actors                                                             │
│  - city admin, duty officer, planner, reviewer, field ops lead, analyst    │
│  - agency owners: ULB, PCB, traffic police, utilities, DA, health/edu      │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Role-specific application layer                                            │
│  - dashboards / consoles / reports (read-only, review-first where needed)  │
│  - agency workflows (review queues, triage, assignment, acknowledgements)  │
└────────────────────────────────────────────────────────────────────────────┘
                │           (consumer contracts shape outputs)
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Domain application layer                                                   │
│  - contract-shaped payload builders (`urban_platform/applications/<domain>`)│
│  - decision/review packets + field tasks (consumer contract governed)      │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Decision support / workflow layer                                          │
│  - provenance + reliability gating, human review prompts, safety flags     │
│  - explainability artifacts (review-safe; no enforcement automation)       │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Processing / feature layer                                                 │
│  - feature builders, aggregations, model-ready tables                       │
│  - reusable processing patterns (`urban_platform/processing/...`)           │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Canonical platform objects                                                 │
│  - Observation / Entity / Feature / Event + reliability/provenance forms   │
│  - normalization discipline (no bypass of canonical objects)               │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Provider connector layer                                                   │
│  - connectors ingest raw feeds that conform to provider contracts          │
│  - open-data-first where possible; authorized municipal feeds later-stage  │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Data fabric layer                                                          │
│  - local artifacts / stores / caches / fixtures (deployment-scoped)        │
│  - provenance references + audit trails                                    │
└────────────────────────────────────────────────────────────────────────────┘
                │
                ├────────────────────────────────────────────────────────────┐
                │                                                            │
                ▼                                                            ▼
┌───────────────────────────────────────────────────┐     ┌───────────────────────────────────────────┐
│ API / SDK access layer                             │     │ Specification + conformance layer        │
│  - SDK/API returns contract-shaped responses        │     │  - `specifications/` = source of truth   │
│  - consumers validated to schemas where applicable  │     │  - `manifest.json` registers artifacts   │
└───────────────────────────────────────────────────┘     │  - `python main.py --step conformance`    │
                                                          └───────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ AI supervisor / development guardrails                                     │
│  - `tools/ai_dev_supervisor/` local review: specs-first, conformance, etc. │
│  - domain maturity via `domain_checklists/*.yaml`                          │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ CI / quality gates                                                         │
│  - `pytest` + conformance + supervisor review on changes                    │
└────────────────────────────────────────────────────────────────────────────┘
```

## 2) Federated / multi-agency architecture (nodes + network layer)

```
                           ┌───────────────────────────────────────────────┐
                           │ AirOS Network Layer (optional)                │
                           │  - domain-agnostic                             │
                           │  - contract-aware (schema_ref)                 │
                           │  - policy-enforcing (auth context, classification)│
                           │  - delivery + receipts + audit/provenance refs │
                           └───────────────────────────────────────────────┘
                                          ▲
                                          │ envelopes + receipts (no domain meaning)
                                          │
┌───────────────────────────────┐         │         ┌───────────────────────────────┐
│ AirOS Node: Agency A          │─────────┼────────▶│ AirOS Node: Agency B          │
│  - owns data + decisions      │         │         │  - owns data + decisions      │
│  - enabled domains            │         │         │  - enabled domains            │
│  - emits/consumes contracts   │         │         │  - emits/consumes contracts   │
└───────────────────────────────┘         │         └───────────────────────────────┘
                                          │
                                          ▼
                           ┌───────────────────────────────────────────────┐
                           │ Transport adapters (carriers)                 │
                           │  - Email adapter (Phase 1; low-frequency)     │
                           │  - API/Webhook adapter                        │
                           │  - File / SFTP adapter                        │
                           │  - Event bus / queue adapter                  │
                           │  - Future: IUDX / Beckn-like adapters         │
                           │                                               │
                           │ Same envelope contract across transports.      │
                           └───────────────────────────────────────────────┘
```

**Email constraints (Phase 1 transport adapter):** suitable for low-frequency coordination, task handoffs, packet sharing, acknowledgements/status updates; not suitable for high-frequency sensor streams, real-time events, large geospatial payloads, or sensitive personal data without stronger controls.

## 3) Air pollution federated flow example (routing vs meaning)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ PCB Node (Pollution Control Board)                                         │
│  - runs Air Quality domain application                                     │
│  - produces decision packet (consumer contract)                            │
│  - optionally requests field tasks                                         │
└────────────────────────────────────────────────────────────────────────────┘
                │
                │  (1) decision_packet_shared / advisory_candidate_shared
                │      envelope: schema_ref -> decision packet consumer contract
                ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ AirOS Network Layer (optional)                                             │
│  - validates envelope + schema_ref presence                                │
│  - enforces authorization + classification policies                        │
│  - routes to entitled agency nodes                                         │
│  - records delivery receipts + audit metadata                              │
│  - DOES NOT evaluate PM2.5 thresholds or prescribe enforcement             │
└────────────────────────────────────────────────────────────────────────────┘
        │                │                 │                  │
        │                │                 │                  │
        ▼                ▼                 ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌────────────────┐  ┌──────────────────────┐
│ Traffic Police│  │ ULB/Sanitation │  │ Dev/Building   │  │ Health/Education     │
│ Node          │  │ Node           │  │ Authority Node │  │ Node                 │
└───────────────┘  └───────────────┘  └────────────────┘  └──────────────────────┘
        │                │                 │                  │
        │ (2) creates     │ (2) creates      │ (2) creates      │ (2) creates
        │ agency-specific │ agency-specific  │ agency-specific  │ agency-specific
        │ review tasks    │ review tasks     │ review tasks     │ review tasks
        │ (local SOP +    │ (local SOP +     │ (local SOP +     │ (local SOP +
        │ human review)   │ human review)    │ human review)    │ human review)
        │                │                 │                  │
        └──────────────┬─┴───────────────┬─┴──────────────────┴───────────────┘
                       │
                       ▼
          ┌───────────────────────────────────────────────────────────┐
          │ City/state coordination view (read-only observability)     │
          │  - aggregated status updates (contract-shaped)             │
          │  - no cross-agency authority override                      │
          └───────────────────────────────────────────────────────────┘
```

## 4) README-friendly condensed diagram

```
Actors → Apps/UI (presentation) → Domain applications (contract-shaped outputs)
      → Processing/features → Canonical objects → Connectors → Data fabric
      ↘ Specs+Conformance (source of truth) ↘ CI+Supervisor (quality gates)

Federation: AirOS Nodes ↔ (optional) Network Layer ↔ transports (email/api/bus/file)
```

## Cross-links

- Federation and Network Layer: `docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`, `docs/AGENCY_NODE_MODEL.md`, `docs/CROSS_AGENCY_COORDINATION_LAYER.md`
- Specs-first + layers: `specifications/ARCHITECTURE_NOTE.md`, `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`
- City profile template (deployment context, not behavior): `docs/CITY_PROFILE_TEMPLATE.md`
