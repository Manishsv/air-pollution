# Containerized deployment architecture (AirOS)

This document describes the **target multi-container deployment architecture** for AirOS: how responsibilities split across services, how they communicate, and how deployment configuration stays **registry-driven** and **specs-first**. It is **design and documentation only**—no new Compose stacks, no code splits, and no change to current runtime behavior in this repository.

**Related:** single-image quickstart and Docker usage are in [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md). That path is intentionally **Level 1** (one image, one process model). This document explains **why** that is a stepping stone and **what** comes next.

---

## 1) Deployment maturity levels

### Level 0: Developer / local single-process

- Engineers run tools directly on the host (or in a personal venv): e.g. `python tools/airos_cli.py …`, `python main.py --step conformance`, tests via `pytest`.
- **Use:** day-to-day development, debugging, and CI-style checks.
- **Characteristics:** fastest feedback loop; no container boundaries; everything shares one Python process space.

### Level 1: Single AirOS image (monolith-in-a-container)

- One Docker image bundles **AirOS Core** together with **reference providers**, **reference applications**, and optionally the **dashboard**—matching the current repo’s practical “get it running” story (see [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)).
- **Use:** demos, training, CI images, early forward deployment when operational risk is low and simplicity wins.
- **Characteristics:** one lifecycle, one network namespace, shared filesystem for artifacts; easy to ship but **not** the long-term agency topology.

### Level 2: Multi-container AirOS node (target for real deployments)

- **AirOS Core** runs as a **dedicated service** (contracts, conformance, canonical object APIs, stores, audit hooks, domain-neutral coordination).
- **Provider services** run separately (data acquisition + contract validation + normalization to canonical objects).
- **Application / data-consumer services** run separately (domain logic, contract-shaped payloads, packets, field tasks, optional HTTP APIs).
- **Dashboard** may run as its own service (presentation only; consumes contract-shaped APIs).
- **Network adapter services** (optional) carry **message envelopes** and **delivery receipts** over transports (email, webhook, SFTP, bus)—without domain semantics.
- **Use:** agency/city deployments where isolation, scaling, patching, and blast-radius control matter.

### Level 3: Federated multi-node deployment

- Multiple **AirOS Nodes** (often agency-owned) each run Level 2-style stacks.
- An **AirOS Network Layer** plus **transport adapters** coordinates **cross-node** exchange using **network contracts** (envelopes, receipts)—still **domain-agnostic** at the protocol plane.
- **Use:** multi-agency city, state, or corridor programs where nodes retain local authority but need coordinated handoffs.

### Level 4: Production orchestration

- **Kubernetes / Helm** (or equivalent): declarative rollouts, health checks, autoscaling, secrets, config maps, persistent volumes, object stores, queues, observability.
- **Use:** hardened production after contracts, governance, and SLOs are established per deployment.

**Current repository posture:** implementation and packaging today sit closest to **Level 0** and **Level 1**. The `flood_local_demo` path proves **registry-driven** execution and contract validation **inside one runtime**; **service boundaries** (Level 2+) are a **deliberate future evolution**, not a requirement to use the platform today.

---

## 2) Target service roles

### AirOS Core service

- **Registry validation** and deployment config hygiene (conceptually aligned with tools like `validate_deployment.py`; in Level 2 this becomes a gate or API on the Core plane).
- **Conformance** against `specifications/` and `manifest.json`.
- **Canonical object APIs** (Observation, Entity, Feature, Event, etc.) and **stores** backing them.
- **Audit / provenance** surfaces and retention hooks (what happened, from which provider, under which policy).
- **Domain-neutral coordination** (orchestration hooks that do **not** embed PM2.5 thresholds, flood levels, enforcement rules, etc.—those stay in **domain specs** and **applications**).
- **Message envelope** and **delivery receipt** handling at the boundary (validate, route metadata, correlate IDs)—**not** “what the packet means” for operations.

### Provider services

- Own one or more **data source integrations** (API, file, stream, partner feed).
- **Validate** inputs against **provider contracts**; refuse or quarantine non-conforming payloads.
- **Normalize** to **platform objects** and submit to Core via the canonical ingestion path (no bypass).
- Preserve **provenance** and **quality flags** end-to-end.

### Application / data-consumer services

- **Read** canonical records and authorized features from Core (or subscribe via agreed patterns).
- Apply **domain / application logic** and emit **consumer-contract** payloads (dashboard JSON, decision packets, field tasks, API response envelopes).
- **Do not bypass** safety gates, blocked uses, or human-review requirements declared in **domain specs** and referenced from registries.

### Network adapter services

- **Send and receive** `network_message_envelope` (and related) artifacts over a chosen **transport**.
- Produce **delivery receipts** (`network_delivery_receipt`) and audit references.
- **Do not interpret** domain payloads beyond schema_ref routing metadata required by policy.

### Dashboard service

- **Presentation only:** renders contract-shaped data from Core or application APIs.
- **Must not** host domain risk logic, enforcement automation, or “hidden” thresholds not governed by specs and review workflows.

---

## 3) Communication patterns (target)

| Flow | Direction | Contract / shape |
|------|-----------|------------------|
| **Provider → Core** | Provider pushes or Core pulls | **Provider contract** input → validated **canonical object** API or ingestion message |
| **Application ↔ Core** | Application reads canonical world; writes outputs | Reads observations / features / events / entities → writes **consumer** payloads, packets, tasks |
| **Network adapter ↔ Core** | Adapter is a transport edge | **message_envelope** in/out → transport bytes → **delivery_receipt** back to Core / peers |
| **Dashboard → Core** (or app API) | Read-mostly UI | **Consumer-shaped** API responses only |

All cross-agency **meaning** stays in **domain specs** and **applications**; the Network Layer and adapters move **envelopes and receipts**, not operational authority.

---

## 4) Deployment configuration (same registries, more processes)

The **same deployment-scoped YAML** used today continues to describe *what* is enabled; in Level 2+, each registry row maps to **which service image/process** to run and how to wire it—not new ad-hoc config silos.

- **`deployment_profile.yaml`:** `deployment_id`, `enabled_domains`, environment, references to enabled registry files, deployment mode.
- **`provider_registry.yaml`:** selects **provider services** (and their contracts, input methods, fixture or endpoint refs via `configuration_ref`—never inline secrets).
- **`application_registry.yaml`:** selects **application services** and consumer contracts they emit.
- **`network_adapter_registry.yaml`:** selects **adapter services** and supported network contracts.
- **`agency_node_profile.yaml` / `network_participant_profile.yaml` / `jurisdiction_profile.yaml`:** node identity, jurisdiction context, and policy references for federation-aware deployments.

**Principle:** registries remain the **declarative overlay** on top of Core; orchestration (Compose, K8s) is a **runtime projection** of that overlay—implemented later, without changing the contract model.

---

## 5) Security and governance

- **Never bake secrets** into images; use environment variables, secret managers, or mounted secret volumes scoped per deployment.
- **Providers** may run inside agency networks or DMZs; Core only accepts **contract-valid** canonical submissions.
- **Applications** should call **authorized** Core/API surfaces and respect consumer contract scopes.
- **Audit logs** for ingestion, packet generation, envelope send/receive, and human review actions are **mandatory** for operational deployments.
- **Cross-agency** traffic uses **message envelopes + delivery receipts** under governance policy—not ad-hoc file drops of unrestricted operational data.
- **Agencies retain decision authority;** AirOS supplies decision support and review discipline, not autonomous enforcement.

---

## 6) Current repository status (honest)

- The codebase and **Level 1** Docker image are optimized for **learning, conformance, and controlled demos** (e.g. `flood_local_demo` with fixture data and an explicit allowlist in the runner—not arbitrary plugin loading).
- **Provider vs application vs Core** separation is **architecturally clear** in specs and docs but **not yet** enforced as separate long-running services in this repo.
- **Network adapters** exist as **contracts** and registry templates; transport services are **not** implemented here as production daemons.
- The **dashboard** is a Streamlit shell that must remain **presentation-oriented**; further hardening comes from contract-shaped APIs and review workflows, not UI logic.

---

## 7) Suggested future implementation path (incremental)

This sequence keeps risk low and preserves **specs-first** discipline:

1. **Keep** the single image for quickstart, CI, and training (**Level 1**).
2. **Add** a `docker-compose` **POC** (when ready) with at least **`airos-core`** + **`flood-demo-app`** as separate services sharing specs + deployment volume—*still no change to domain semantics in the network plane*.
3. **Extract** a **provider service POC** for one **fixture/file** provider (mirror existing ingest + contract validation; push canonical rows to Core).
4. **Extract** an **application service POC** for one consumer output (e.g. flood dashboard payload builder reading from Core).
5. **Add** a **network adapter service POC** (e.g. email) that only handles envelopes/receipts and delegates meaning to nodes.
6. **Defer** full **Kubernetes/Helm** production until SLOs, key management, data residency, and multi-tenant governance are defined per deployment.

**Explicit non-goals for this document:** no new Compose files, no service mesh mandates, no splitting of `urban_platform/` or `src/` as part of this task—those belong to future implementation PRs with their own conformance evidence.

---

## Cross-links

- Docker quickstart (single image): [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md)
- Plugin and registry model: [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md)
- Layered architecture diagrams: [`docs/AIR_OS_ARCHITECTURE_OVERVIEW.md`](AIR_OS_ARCHITECTURE_OVERVIEW.md)
- Federation: [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md), [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md)
