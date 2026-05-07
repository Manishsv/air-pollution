# AIR Platform Architecture

## 1. Overview

The AIR platform is a three-layer system for urban climate intelligence and
governance. Each layer has a distinct identity, responsibility boundary, and
deployment surface.

```
┌─────────────────────────────────────────────────────────────────┐
│                    AIR Climate Suite                            │
│                                                                 │
│   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────┐   │
│   │  AIR AQ   │   │AIR Flood  │   │ AIR Heat  │   │  ...  │   │
│   │(Air Qual.)│   │           │   │           │   │       │   │
│   └───────────┘   └───────────┘   └───────────┘   └───────┘   │
│                                                                 │
│   Domain-specific sensing, risk scoring, decision support       │
│   and officer-facing dashboards per climate hazard              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ runs on
┌──────────────────────────────▼──────────────────────────────────┐
│                          AIROS                                  │
│                  Urban Climate Platform                         │
│                                                                 │
│   Ward engine · QoL scoring · Decision Inbox · Feature Store    │
│   Role model · Multi-tenancy · Workflow · Notifications         │
│   Registry · Boundary · IDGen · Governance receipts            │
│                                                                 │
│   Built on DIGIT3 (infrastructure layer, embedded within AIROS) │
└──────────────────────────────┬──────────────────────────────────┘
                               │ coordinated by
┌──────────────────────────────▼──────────────────────────────────┐
│                          AIRNet                                 │
│               Coordination & Accountability Layer               │
│                                                                 │
│   Entity graph · Domain events · Execution traces              │
│   GCP reconstruction · Cross-system audit trail                │
│   Platform-agnostic (works with or without DIGIT3)             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer definitions

### 2.1 AIROS — Urban Climate Platform

**Analogy:** the operating system. The platform that climate apps run on.

AIROS is the complete urban climate decision platform. It bundles DIGIT3 as
its infrastructure layer — DIGIT3 is not AIROS's host; DIGIT3 is AIROS's
foundation. A city deploys AIROS; they get DIGIT3 as part of it.

**What AIROS provides:**

| Capability | Detail |
|-----------|--------|
| Ward engine | H3-cell-to-ward aggregation, QoL index, composite risk scoring |
| Decision engine | Trigger → attribution → action → escalation packet generation |
| Decision Inbox | Push delivery (email, SMS, WhatsApp) to ward engineers and zonal officers |
| Feature store | DuckDB per-domain risk scores, time-bucketed observations |
| Multi-tenancy | City = tenant; all data partitioned by city code |
| Role model | `WARD_ENGINEER`, `ZONAL_OFFICER`, `CITY_ADMIN`, `VIEWER`, `SYSTEM` |
| Workflow | Decision packet lifecycle: OPEN → ACKNOWLEDGED → ACTIONED → RESOLVED |
| Governance | Versioned rulesets, decision receipts, appeals — GCP-aligned |
| Boundary | Authoritative ward geometry from DIGIT3 Boundary service |
| Identity | Keycloak-based SSO; officers log in once, all apps inherit the session |
| API surface | `/airos/v1/` — ward snapshots, decisions, city summary, webhooks |

**What AIROS does not do:**
- Sense raw data (that is each climate app's concern)
- Store raw observations long-term (each app owns its observation store)
- Coordinate across systems (that is AIRNet's concern)

**Repos:** `airos` (platform core, includes DIGIT3 configuration and
provisioning scripts)

**DIGIT3 as infrastructure:** AIROS ships with a `provision_city.py` script
that configures DIGIT3 services (Account, Registry, IDGen, Workflow,
Notification, Governance, Studio, Boundary) for a new city tenant. From a
city's perspective, they deploy AIROS and get a fully working platform —
DIGIT3 is an implementation detail.

---

### 2.2 AIRNet — Coordination and Accountability Layer

**Analogy:** the network protocol. Connects entities across systems and
provides a tamper-evident audit trail.

AIRNet is a standalone service, separate from AIROS. It is platform-agnostic:
it works with AIROS, with other DIGIT3 modules, and with non-DIGIT3 city
platforms. Its only requirement is that entities have stable canonical IDs.

**What AIRNet provides:**

| Capability | Detail |
|-----------|--------|
| Entity graph | Typed, directed links between wards, sensors, decisions, officers |
| Domain events | Immutable append-only event log per entity |
| Execution traces | Ordered steps within a case — the decision timeline |
| GCP reconstruction | Single query returns full case: entities + events + traces |
| Cross-system audit | Links governance receipts (from AIROS) to entity events |

**Repos:** `airnet` (separate repository)

See [`AIRNET_COORDINATION_SPEC.md`](AIRNET_COORDINATION_SPEC.md) for the full
API reference and integration pattern.

---

### 2.3 AIR Climate Suite — Domain Applications

**Analogy:** Microsoft Office on Windows. Applications that run on the AIROS
platform and use AIRNet for coordination.

Each app in the suite is a self-contained domain system. It owns its sensors,
observation ingestion, risk models, and domain-specific UI. It publishes
decision packets to AIROS and emits events to AIRNet.

#### App catalogue

| App | Full name | Domain | Decision type | Urgency driver |
|-----|-----------|--------|--------------|----------------|
| **AIR AQ** | AIR Air Quality | Air | Pollution source attribution, traffic/industrial/burning | AQI score |
| **AIR Flood** | AIR Flood Risk | Flood | Drain desilting, sandbag deployment, road closure | Flood risk score |
| **AIR Heat** | AIR Heat Risk | Heat | Cooling centre activation, rest advisory, tree planting | Heat risk score |
| **AIR Cross** | AIR Cross-Domain | Multi | Compounding climate stress, escalation to zonal officer | Composite risk score |

Future apps follow the same pattern and register on AIROS as additional
domain modules:

| Planned app | Domain |
|------------|--------|
| AIR Water | Water quality and supply |
| AIR Traffic | Congestion and emissions |
| AIR Assets | Public infrastructure condition |
| AIR Econ | Economic vulnerability and opportunity |

#### What each app owns

- **Observation store** — raw sensor readings, API pulls, citizen reports
  (Parquet files per domain)
- **Feature builder** — H3-cell risk scores from observations
- **Domain signals** — inputs to the AIROS ward engine
- **Domain dashboard panel** — Streamlit panel registered in `review_dashboard/app.py`
- **Domain rulesets** — published to AIROS Governance service; define the
  attribution and triage logic

#### What each app delegates to AIROS

- Ward-level aggregation (QoL index, composite risk)
- Decision packet generation, workflow, and notifications
- Role-based access control and multi-tenancy
- Governance receipts and GCP accountability

#### App–platform interface

```python
# Each app publishes domain signals to the AIROS feature store
airos.feature_store.write(
    domain="air",
    city_id="bangalore",
    timestamp_bucket="2026-05-07T06:00",
    h3_scores=[
        {"h3_cell": "8a3e4a9b7ffffff", "aqi_score": 0.72, "pm25": 84.3},
        ...
    ]
)

# AIROS reads domain signals, aggregates to wards, and generates decision packets
# Apps receive outcomes via webhook or by polling /airos/v1/ward/{code}/decisions
```

---

## 3. How the layers interact

```
AIR AQ senses PM2.5
        ↓
writes H3 cell scores to AIROS feature store
        ↓
AIROS aggregates to ward → ward QoL score
        ↓
AIROS decision engine: aqi=0.72, hour=6 → AQ-D1 (waste burning, within_4h)
        ↓
AIROS calls (in parallel):
  ├─→ DIGIT3 Governance: decisionReceipt (hash-chained accountability proof)
  ├─→ DIGIT3 Registry:   persist airos.decision record
  ├─→ DIGIT3 Workflow:   open AIROS_DECISION instance, assign to ward engineer
  └─→ DIGIT3 Notification: email + SMS to officer
        ↓
AIRNet (async, non-blocking):
  ├─→ event: DECISION_GENERATED (with rulesetId + receiptHash)
  ├─→ link:  ward → decision, decision → sensor
  └─→ trace: generate step (actor: airos-system)
        ↓
Officer receives email → acknowledges via one-click link
        ↓
DIGIT3 Workflow transitions OPEN → ACKNOWLEDGED
        ↓
AIROS webhook: update packet status
        ↓
AIRNet: event DECISION_ACKNOWLEDGED (actor: officer-uuid)
```

---

## 4. Deployment topology

```
┌─────────────────────────────────────────────────────────────────┐
│  City deployment                                                │
│                                                                 │
│  Kong API Gateway (:443)                                        │
│    /airos/*   → AIROS platform (:8200)                         │
│    /airnet/*  → AIRNet service (:8300)                         │
│    /boundary, /workflow, /registry, ...  (DIGIT3 internal)     │
│                                                                 │
│  AIROS platform                                                 │
│    airos-api       (:8200)  REST API + webhook handler          │
│    airos-pipeline           domain aggregation (cron)           │
│    airos-dispatcher         notification routing                │
│    airos-dashboard          Streamlit review console            │
│                                                                 │
│  AIRNet                                                         │
│    airnet          (:8300)  coordination + event graph          │
│                                                                 │
│  DIGIT3 (embedded infrastructure)                              │
│    boundary / workflow / registry / notification               │
│    governance / idgen / account / studio                       │
│                                                                 │
│  AIR Climate Suite apps (domain pipelines, co-deployed)        │
│    air-aq-pipeline          PM2.5 ingestion + H3 scoring       │
│    air-flood-pipeline       rainfall + drain risk scoring       │
│    air-heat-pipeline        LST + canopy cover scoring         │
│                                                                 │
│  Shared infrastructure                                         │
│    Keycloak (:8080)         identity, SSO                      │
│    PostgreSQL               all services, schema-isolated       │
│    Redis                    caching + pub/sub                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Brand relationships

| Layer | Brand | Tagline |
|-------|-------|---------|
| Platform | **AIROS** | Urban climate platform |
| Coordination | **AIRNet** | Coordination and accountability network |
| Apps | **AIR Climate Suite** | Climate intelligence for city officers |
| App: air quality | **AIR AQ** | Know your air |
| App: flood | **AIR Flood** | See the risk before the rain |
| App: heat | **AIR Heat** | Protect every ward from heat stress |

The AIR prefix unifies all three layers into a recognisable product family
while keeping the platform (AIROS), network (AIRNet), and apps (AIR ___) as
distinct, independently understandable products.

---

## 6. Canonical document map

| Topic | Document |
|-------|---------|
| Platform layer detail (DIGIT3 infrastructure) | [`AIROS_DIGIT3_INFRASTRUCTURE_SPEC.md`](AIROS_DIGIT3_INFRASTRUCTURE_SPEC.md) |
| Coordination layer detail | [`AIRNET_COORDINATION_SPEC.md`](AIRNET_COORDINATION_SPEC.md) |
| Urban system model (all domains) | [`URBAN_SYSTEM_MODEL.md`](URBAN_SYSTEM_MODEL.md) |
| Ward decision catalogue (trigger → action) | [`WARD_DECISION_CATALOGUE.md`](WARD_DECISION_CATALOGUE.md) |
| App development guide | `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md` |
