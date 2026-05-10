# AIRNet — Urban Coordination and Accountability Layer

## 1. Purpose

AIRNet is a standalone open-source service that provides entity resolution,
typed links between urban entities, domain event emission, execution traces, and
a governance accountability bridge for AirOS and other urban platform modules.

It is **not part of DIGIT3**. It runs alongside DIGIT3 as an independent
service in the AirOS deployment and can interoperate with any urban platform
that exposes canonical entity IDs.

**Repo:** `airnet` (separate repository under the AirOS organisation)

**Why a separate service:**
- Entity graph and event trail requirements span systems (DIGIT3, AirOS,
  future modules); no single platform owns this layer
- The Government Coordination Protocol (GCP) reconstruction requirement needs
  a queryable event store that is independent of any single service's audit log
- AIRNet must work in non-DIGIT3 deployments (city platforms, custom stacks)

---

## 2. Core concepts

| Concept | Description |
|---------|-------------|
| **Entity** | Any urban object with a stable canonical ID — ward, sensor, drain asset, decision packet, officer |
| **Link** | A typed, directed relationship between two entities — `SERVES_WARD`, `HAS_DECISION`, `OWNED_BY` |
| **Event** | An immutable domain fact emitted when something happens — `DECISION_GENERATED`, `SENSOR_READING_INGESTED` |
| **Trace** | A step in an execution sequence — ordered steps within a case (e.g. all steps for one decision packet) |
| **Case** | A logical grouping of entities, events, and traces under a shared root ID |
| **Receipt** | A hash-linked proof record attached to a case step — enables GCP-level reconstruction |

---

## 3. Architecture

```
┌────────────────────────────────────────────────┐
│  AIRNet service  (:8300)                     │
│                                                │
│  REST API (FastAPI)                            │
│    /airnet/v1/entities                       │
│    /airnet/v1/links                          │
│    /airnet/v1/events                         │
│    /airnet/v1/traces                         │
│    /airnet/v1/cases/{id}                     │
│                                                │
│  SQLite local index   (fast graph queries)     │
│  PostgreSQL           (durable event log)      │
│  Optional: Kafka out  (event streaming)        │
└────────────────────────────────────────────────┘
         ↕                      ↕
   AirOS (8200)           DIGIT3 services
   (primary producer)     (entity ID source)
```

AIRNet is stateful but not authoritative for entity data — it stores
canonical IDs and pointers, not full entity records. Those live in Registry
or AirOS's own stores.

---

## 4. API reference

### 4.1 Create or update an entity

```json
POST /airnet/v1/entities
X-Tenant-ID: {city_code}

{
  "entityType": "airos.ward",
  "entityId":   "BBMP_WARD_007",
  "tenantId":   "{city_code}",
  "data": {
    "wardName": "Ward 7 — Shivajinagar",
    "cityId":   "bangalore"
  }
}
```

Idempotent — re-registering an existing entity updates its `data` payload.

### 4.2 Create a typed link between entities

```json
POST /airnet/v1/links
X-Tenant-ID: {city_code}

{
  "fromEntityType": "airos.sensor",
  "fromEntityId":   "SEN-AIR-BLR-0019",
  "toEntityType":   "airos.ward",
  "toEntityId":     "BBMP_WARD_007",
  "linkType":       "SERVES_WARD",
  "tenantId":       "{city_code}"
}
```

**Standard link types for AirOS:**

| Link type | From → To | Meaning |
|-----------|-----------|---------|
| `SERVES_WARD` | sensor → ward | Sensor covers this ward |
| `HAS_DECISION` | ward → decision | Ward has an open decision packet |
| `TRIGGERED_BY` | decision → sensor | Decision triggered by this sensor reading |
| `ESCALATED_TO` | decision → officer | Decision escalated to this officer |
| `RESOLVED_BY` | decision → officer | Decision resolved by this officer |

### 4.3 Emit a domain event

```json
POST /airnet/v1/events
X-Tenant-ID: {city_code}

{
  "entityType": "airos.decision",
  "entityId":   "AIROS-BLR-2026-000042",
  "eventType":  "DECISION_GENERATED",
  "tenantId":   "{city_code}",
  "payload": {
    "domain":         "air",
    "urgency":        "within_4h",
    "wardCode":       "BBMP_WARD_007",
    "rulesetId":      "airos_air_decisions_v1",
    "rulesetVersion": 1
  }
}
```

Events are immutable. They cannot be deleted or updated — only new events
can supersede them. This is the append-only audit log.

**Standard AirOS events:**

| Event type | Emitted when |
|------------|-------------|
| `DECISION_GENERATED` | New decision packet created |
| `DECISION_ACKNOWLEDGED` | Officer acknowledges decision |
| `DECISION_ACTIONED` | Officer marks action taken |
| `DECISION_ESCALATED` | Decision escalated to zonal officer |
| `DECISION_RESOLVED` | Decision resolved |
| `DECISION_APPEALED` | Officer raises attribution appeal |
| `GOVERNANCE_RECEIPT_ISSUED` | Governance service issues decisionReceipt |
| `SENSOR_READING_INGESTED` | New observation for a sensor station |
| `WARD_SCORE_COMPUTED` | Ward aggregation run completed |

### 4.4 Record an execution trace step

```json
POST /airnet/v1/traces
X-Tenant-ID: {city_code}

{
  "caseId":   "AIROS-BLR-2026-000042",
  "stepId":   "governance-receipt",
  "actor":    "airos-system",
  "action":   "GOVERNANCE_RECEIPT_ISSUED",
  "payload": {
    "receiptHash":    "{sha256_of_receipt}",
    "rulesetId":      "airos_air_decisions_v1",
    "rulesetVersion": 1,
    "chainHash":      "{sha256_chain}"
  },
  "tenantId": "{city_code}"
}
```

Traces within a case are ordered by `createdAt`. Together they form the
execution timeline for a decision packet — from generation through resolution.

### 4.5 Query a case (full entity graph + event timeline)

```
GET /airnet/v1/cases/AIROS-BLR-2026-000042
X-Tenant-ID: {city_code}

Response:
{
  "caseId": "AIROS-BLR-2026-000042",
  "entities": [
    {"entityType": "airos.decision", "entityId": "AIROS-BLR-2026-000042", ...},
    {"entityType": "airos.ward",     "entityId": "BBMP_WARD_007", ...},
    {"entityType": "airos.sensor",   "entityId": "SEN-AIR-BLR-0019", ...}
  ],
  "links": [
    {"fromType": "airos.ward", "fromId": "BBMP_WARD_007", "toType": "airos.decision", "toId": "AIROS-BLR-2026-000042", "linkType": "HAS_DECISION"},
    {"fromType": "airos.decision", "fromId": "AIROS-BLR-2026-000042", "toType": "airos.sensor", "toId": "SEN-AIR-BLR-0019", "linkType": "TRIGGERED_BY"}
  ],
  "events": [
    {"eventType": "DECISION_GENERATED", "emittedAt": "2026-05-07T06:12:00Z", "payload": {...}},
    {"eventType": "GOVERNANCE_RECEIPT_ISSUED", "emittedAt": "2026-05-07T06:12:05Z", "payload": {...}},
    {"eventType": "DECISION_ACKNOWLEDGED", "emittedAt": "2026-05-07T07:01:00Z", "payload": {...}}
  ],
  "traces": [
    {"stepId": "generate",           "actor": "airos-system", "action": "DECISION_GENERATED", ...},
    {"stepId": "governance-receipt", "actor": "airos-system", "action": "GOVERNANCE_RECEIPT_ISSUED", ...},
    {"stepId": "acknowledge",        "actor": "officer-uuid", "action": "DECISION_ACKNOWLEDGED", ...}
  ]
}
```

This response is the GCP reconstruction payload — it contains everything
needed to replay and verify the decision from raw facts through resolution.

### 4.6 Query all decisions for a ward

```
GET /airnet/v1/cases?rootEntityType=airos.ward&rootEntityId=BBMP_WARD_007
X-Tenant-ID: {city_code}

Response: list of case summaries for all decisions linked to this ward
```

---

## 5. AirOS integration pattern

AIRNet calls are made **in parallel** with DIGIT3 calls — they are
non-blocking from the perspective of the decision packet pipeline. If AIRNet
is unavailable, decision generation continues; traces are queued and replayed
when AIRNet recovers.

**On decision packet generation:**
```
airos-pipeline emits packet
  │
  ├─→ DIGIT3 Governance: POST /governance/v1/decisions  [blocking — need receipt]
  │         ↓ receiptHash returned
  ├─→ DIGIT3 Registry:   POST /registry/v1/data/airos.decision
  ├─→ DIGIT3 Workflow:   POST /workflow/v1/transition
  ├─→ DIGIT3 Notification: POST /notification/v1/notification/email
  │
  └─→ AIRNet [async, non-blocking]:
        POST /airnet/v1/events   (DECISION_GENERATED)
        POST /airnet/v1/links    (ward → decision, decision → sensor)
        POST /airnet/v1/traces   (step: generate, receiptHash from Governance)
```

**On officer action (webhook from DIGIT3 Workflow):**
```
AirOS webhook handler receives /airos/v1/webhooks/decision-updated
  │
  ├─→ Update packet status in feature store
  │
  └─→ AIRNet [async]:
        POST /airnet/v1/events  (DECISION_ACTIONED / DECISION_RESOLVED)
        POST /airnet/v1/traces  (step: action, actor: officer-uuid)
```

---

## 6. GCP reconstruction flow

When a decision is contested or audited, AIRNet provides the reconstruction
payload in a single query. The Reconstruction Engine (GCP component) calls:

```
GET /airnet/v1/cases/{packetId}
```

And receives the full entity graph, event timeline, and trace sequence. Combined
with the Governance `decisionReceipt` (retrieved via `receiptHash` in the trace),
this satisfies GCP's requirement to reconstruct any decision from its raw inputs.

**Reconstruction checklist:**

| GCP requirement | Source in AIRNet response |
|----------------|-----------------------------|
| What facts were used? | `DECISION_GENERATED` event payload → `facts` |
| Which ruleset version applied? | Trace step `governance-receipt` → `rulesetId`, `rulesetVersion` |
| What was the outcome? | Governance `decisionReceipt` retrieved via `receiptHash` |
| Who acted and when? | Events `DECISION_ACKNOWLEDGED`, `DECISION_ACTIONED` with actor UUID + timestamp |
| Was it appealed? | Event `DECISION_APPEALED` with reason + evidence |
| What sensor state was active? | `RegistryResolver.resolve_as_of()` called with sensor ID + `emittedAt` from `DECISION_GENERATED` event |

---

## 7. Deployment

AIRNet runs as a standalone container alongside AirOS services.

```
┌─────────────────────────────────────────────────────┐
│  AirOS services                                     │
│                                                     │
│  airos-api (:8200)                                  │
│  airos-pipeline                                     │
│  airos-dispatcher                                   │
│  airos-dashboard                                    │
│  airnet (:8300)   ← new service                  │
│    PostgreSQL (airnet schema, shared PG instance) │
│    SQLite index (mounted volume, fast graph queries)│
└─────────────────────────────────────────────────────┘
```

**docker-compose addition:**
```yaml
airnet:
  image: airnet:latest
  ports: ["8300:8300"]
  environment:
    DATABASE_URL: postgresql://pg/airnet
    SQLITE_PATH: /data/airnet.db
    KAFKA_BROKER: ""          # leave empty to disable event streaming
    AUTH_MODE: internal       # trusts X-Tenant-ID header; production: keycloak
  volumes:
    - airnet-data:/data
```

In production, AIRNet validates DIGIT3 Keycloak JWTs on the `X-Tenant-ID`
header using the same shared Keycloak realm.

---

## 8. Multi-system interoperability

AIRNet is designed to work with any system that uses canonical string IDs.
It makes no assumptions about DIGIT3 — entity IDs are just strings.

A non-DIGIT3 deployment (e.g. city with a custom platform) can use AIRNet
by registering its own entity types and calling the same API. The coordination
graph and event trail work identically.

This is the **coordination hourglass**: diverse systems above (DIGIT3, custom
platforms, future modules), shared event + graph layer in the middle (AIRNet),
diverse consumers below (audit tools, dashboards, GCP reconstruction).

---

## 9. Roadmap

| Phase | Scope |
|-------|-------|
| v0.1 | Entity, link, event, trace APIs; PostgreSQL + SQLite backend; Docker image |
| v0.2 | Case query API; AirOS integration (non-blocking async calls); queue + replay on failure |
| v0.3 | Kafka event streaming out (optional); GCP reconstruction endpoint |
| v0.4 | Keycloak JWT validation; multi-tenant isolation; production hardening |
| v1.0 | Stable API; versioned releases; integration tests with AirOS test suite |
