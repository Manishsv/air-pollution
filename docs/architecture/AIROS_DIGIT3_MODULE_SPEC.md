# AirOS — DIGIT3 Module Specification

## 1. Purpose

This document specifies how AirOS integrates with DIGIT3 as a domain module.
It defines: which DIGIT3 services AirOS consumes, which APIs AirOS exposes back
to the platform, the data contracts at each boundary, and the integration
roadmap.

The target audience is AirOS engineers, DIGIT3/eGov collaborators, and NIUA
programme teams evaluating AirOS for deployment on UPYOG.

---

## 2. Module identity

| Field | Value |
|-------|-------|
| **Module code** | `airos` |
| **Module name** | AirOS — Urban Climate Decision Support |
| **Module type** | `GOVERNANCE` |
| **Version** | `1.0.0` |
| **API base path** | `/airos/v1` |
| **Dependencies** | `boundary`, `workflow`, `notification`, `registry`, `idgen`, `account` |
| **Publisher** | AirOS / NIUA partner |

**Studio service registration** (called once per city deployment):

```json
POST /studio/v1/services
X-Tenant-ID: {city_code}
X-Client-ID: airos-admin

{
  "serviceCode": "airos",
  "name": "AirOS — Urban Climate Decision Support",
  "moduleType": "GOVERNANCE",
  "status": "ACTIVE",
  "metadata": {
    "version": "1.0.0",
    "description": "Climate risk monitoring, ward-level quality-of-life scoring, and decision support for ward engineers and city administrators.",
    "apiBaseUrl": "http://airos:8200",
    "domains": ["air", "flood", "heat"],
    "dependencies": ["boundary", "workflow", "notification", "registry", "idgen", "account"]
  }
}
```

---

## 3. Multi-tenancy model

Each city is a DIGIT3 tenant. AirOS inherits the tenant model without changes.

| Concept | DIGIT3 mapping | Example |
|---------|---------------|---------|
| City | Keycloak realm + tenant code | `bangalore`, `delhi`, `pune` |
| Ward | Boundary entity, type `WARD` | code `BBMP_WARD_007` |
| Zone | Boundary entity, type `ZONE` | code `BBMP_ZONE_EAST` |
| City corporation | Boundary entity, type `CITY` | code `BBMP` |

Every AirOS API call to DIGIT3 services carries:
```
X-Tenant-ID: {city_code}       # e.g. bangalore
X-Client-ID: {user_uuid}       # from Keycloak JWT sub claim
Authorization: Bearer {jwt}    # validated by Kong; not re-checked by services
```

AirOS pipelines run per-tenant. A single AirOS deployment serves multiple
cities; all data is partitioned by `tenantId`.

---

## 4. DIGIT3 services consumed by AirOS

### 4.1 Boundary service — ward geometry and hierarchy

AirOS replaces its synthetic ward grid with authoritative boundaries from the
Boundary service. This is the highest-priority integration.

**Consumed at:** startup and on ward registry refresh.

**Fetch all wards for a city:**
```
GET /boundary/v1/boundary-relationships
    ?hierarchyType=ADMIN&boundaryType=WARD&tenantId={city_code}
X-Tenant-ID: {city_code}
```

**Fetch ward polygon:**
```
GET /boundary/v1/boundary?codes={ward_code}
X-Tenant-ID: {city_code}

Response:
{
  "boundary": [{
    "code": "BBMP_WARD_007",
    "geometry": {"type": "Polygon", "coordinates": [[[77.49,12.87],...]]},
    "additionalDetails": {"name": "Ward 7 — Shivajinagar"}
  }]
}
```

**AirOS mapping:** `Boundary.code` → `ward_id`, `Boundary.geometry` →
`Ward.coordinates`, `additionalDetails.name` → `Ward.name`.

**Hierarchy traversal** (zone → wards):
```
GET /boundary/v1/boundary-relationships
    ?parent={zone_code}&hierarchyType=ADMIN&boundaryType=WARD
```

---

### 4.2 Workflow service — decision packet lifecycle

Every AirOS decision packet is registered as a workflow process instance.
This gives the system: state tracking, SLA enforcement, escalation, audit
trail, and role-gated transitions — all without AirOS building any of it.

#### 4.2.1 Process definition (created once per city tenant)

```json
POST /workflow/v1/process
X-Tenant-ID: {city_code}

{
  "name": "AirOS Climate Decision Review",
  "code": "AIROS_DECISION",
  "description": "Lifecycle for ward-level climate decision packets",
  "version": "1.0",
  "sla": 1440
}
```

#### 4.2.2 State definitions

| State code | Name | Initial | SLA (min) |
|-----------|------|---------|----------|
| `OPEN` | Decision Raised | yes | — |
| `ACKNOWLEDGED` | Acknowledged by Officer | no | 240 |
| `ACTIONED` | Action Taken | no | 480 |
| `ESCALATED` | Escalated to Zonal Officer | no | 240 |
| `RESOLVED` | Resolved | no | — |
| `DISMISSED` | Dismissed with Reason | no | — |

```json
POST /workflow/v1/process/{processId}/state
{
  "code": "OPEN",
  "name": "Decision Raised",
  "isInitial": true,
  "sla": null
}
// Repeat for each state above
```

#### 4.2.3 Action definitions (transitions)

| Action | From state | To state | Allowed roles |
|--------|-----------|---------|--------------|
| `ACKNOWLEDGE` | `OPEN` | `ACKNOWLEDGED` | `WARD_ENGINEER` |
| `ACTION_TAKEN` | `ACKNOWLEDGED` | `ACTIONED` | `WARD_ENGINEER` |
| `ESCALATE` | `OPEN`, `ACKNOWLEDGED` | `ESCALATED` | `WARD_ENGINEER` |
| `RESOLVE` | `ACTIONED`, `ESCALATED` | `RESOLVED` | `WARD_ENGINEER`, `ZONAL_OFFICER` |
| `DISMISS` | `OPEN` | `DISMISSED` | `WARD_ENGINEER`, `ZONAL_OFFICER` |
| `REASSIGN` | `ESCALATED` | `ACKNOWLEDGED` | `ZONAL_OFFICER` |

```json
POST /workflow/v1/state/{stateId}/action
{
  "name": "ACKNOWLEDGE",
  "label": "Acknowledge",
  "currentState": "{open_state_uuid}",
  "nextState": "{acknowledged_state_uuid}",
  "attributeValidation": {
    "attributes": {"role": ["WARD_ENGINEER"]}
  }
}
```

#### 4.2.4 Creating a process instance (when AirOS emits a decision packet)

```json
POST /workflow/v1/transition
X-Tenant-ID: {city_code}

{
  "processId": "{airos_decision_process_uuid}",
  "entityId": "{packet_id}",
  "action": "OPEN",
  "comment": "AQ-D1: Waste burning likely in Ward 7 — dispatch sanitation supervisor",
  "assigner": "airos-system",
  "assignees": ["{ward_engineer_user_id}"],
  "attributes": {
    "role": ["WARD_ENGINEER"],
    "ward": ["{ward_code}"],
    "domain": ["air"],
    "urgency": ["within_4h"]
  }
}
```

#### 4.2.5 Officer acknowledges or actions (from Decision Inbox)

```json
POST /workflow/v1/transition
X-Tenant-ID: {city_code}
Authorization: Bearer {officer_jwt}

{
  "processId": "{airos_decision_process_uuid}",
  "entityId": "{packet_id}",
  "action": "ACTION_TAKEN",
  "comment": "Dispatched sanitation crew; burning stopped by 07:45.",
  "assigner": "{officer_user_id}",
  "attributes": {
    "role": ["WARD_ENGINEER"],
    "ward": ["{ward_code}"]
  }
}
```

#### 4.2.6 SLA escalation (scheduled job, run every 15 min)

```
POST /workflow/v1/auto/AIROS_DECISION/_escalate
X-Tenant-ID: {city_code}
```

DIGIT3 automatically transitions all instances that have exceeded their
state-level SLA to `ESCALATED` and triggers a notification.

---

### 4.3 Notification service — Decision Inbox delivery

AirOS publishes to DIGIT3 Notification for all decision packet delivery.

#### 4.3.1 Templates (created once per city tenant)

**Email template — decision alert:**
```json
POST /notification/v1/template
X-Tenant-ID: {city_code}

{
  "templateId": "AIROS_DECISION_EMAIL",
  "type": "EMAIL",
  "subject": "[{{urgency}}] Climate Decision — {{ward_name}} ({{decision_id}})",
  "isHTML": true,
  "content": "
    <h2 style='color:{{urgency_color}}'>{{urgency_label}}: {{domain}} Alert — {{ward_name}}</h2>
    <p><strong>Likely cause:</strong> {{likely_cause}}</p>
    <p><strong>Recommended action:</strong> {{recommended_action}}</p>
    <table>
      <tr><td>AQI Score</td><td>{{aqi_score}}</td></tr>
      <tr><td>Flood Risk</td><td>{{flood_risk}}</td></tr>
      <tr><td>Heat Risk</td><td>{{heat_risk}}</td></tr>
    </table>
    <p>
      <a href='{{inbox_url}}/decisions/{{packet_id}}'>View full evidence</a> &nbsp;|&nbsp;
      <a href='{{ack_url}}/{{packet_id}}/acknowledge'>Acknowledge</a> &nbsp;|&nbsp;
      <a href='{{ack_url}}/{{packet_id}}/escalate'>Escalate</a>
    </p>
    <p style='color:#999;font-size:11px'>Decision support only. Field verification required before action.</p>
  "
}
```

**SMS template — decision alert:**
```json
POST /notification/v1/template
X-Tenant-ID: {city_code}

{
  "templateId": "AIROS_DECISION_SMS",
  "type": "SMS",
  "category": "NOTIFICATION",
  "content": "[AirOS {{urgency}}] {{domain}} alert - {{ward_name}}. {{recommended_action_short}} View: {{short_url}}"
}
```

**Email template — daily digest:**
```json
{
  "templateId": "AIROS_DIGEST_EMAIL",
  "type": "EMAIL",
  "subject": "AirOS Daily Digest — {{city_name}} — {{date}}",
  "isHTML": true,
  "content": "
    <h2>{{city_name}} — Climate Decision Summary</h2>
    <p>{{total_open}} open decisions | {{immediate_count}} immediate | {{escalations}} escalations</p>
    {{digest_table_html}}
    <a href='{{inbox_url}}'>Open Decision Inbox</a>
  "
}
```

#### 4.3.2 Sending a decision notification

```json
POST /notification/v1/notification/email
X-Tenant-ID: {city_code}
X-Client-ID: airos-system

{
  "templateId": "AIROS_DECISION_EMAIL",
  "tenantId": "{city_code}",
  "emailIds": ["{officer_email}"],
  "enrich": false,
  "payload": {
    "urgency": "within_4h",
    "urgency_label": "Within 4h",
    "urgency_color": "#fd7e14",
    "domain": "Air Quality",
    "ward_name": "Ward 7 — Shivajinagar",
    "decision_id": "AQ-D1",
    "likely_cause": "Likely open waste burning — early morning spike in residential area",
    "recommended_action": "Dispatch sanitation supervisor — locate and stop burning; issue no-burning notice.",
    "aqi_score": "0.72",
    "flood_risk": "—",
    "heat_risk": "—",
    "packet_id": "pkt_ward_abc123",
    "inbox_url": "https://airos.city/inbox",
    "ack_url": "https://airos.city/api/v1/decisions",
    "short_url": "https://airos.city/d/abc123"
  }
}
```

**Delivery cadence rules (enforced by AirOS dispatcher, not DIGIT3):**

| Urgency | Channel | Timing |
|---------|---------|--------|
| `immediate` | Email + SMS | Within 5 minutes of packet generation |
| `within_4h` | Email + SMS | Within 30 minutes |
| `within_24h` | Email only | Morning digest at 07:00 local |
| `plan` | Email only | Weekly summary, Monday 08:00 |

---

### 4.4 Registry service — AirOS entity schemas

AirOS registers four schemas in DIGIT3 Registry for entities that benefit
from versioning, cross-service discovery, and webhook callbacks.

#### Schema 1 — Sensor station

```json
POST /registry/v1/schema
X-Tenant-ID: {city_code}

{
  "schemaCode": "airos.sensor",
  "definition": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["stationId", "domain", "wardCode", "lat", "lon", "status"],
    "properties": {
      "stationId":   {"type": "string"},
      "domain":      {"type": "string", "enum": ["air", "flood", "heat"]},
      "wardCode":    {"type": "string"},
      "lat":         {"type": "number"},
      "lon":         {"type": "number"},
      "source":      {"type": "string"},
      "status":      {"type": "string", "enum": ["active", "inactive", "synthetic"]},
      "lastSeenAt":  {"type": "string", "format": "date-time"}
    }
  },
  "x-indexes": [
    {"fieldPath": "domain",   "method": "btree"},
    {"fieldPath": "wardCode", "method": "btree"}
  ]
}
```

#### Schema 2 — Drain asset

```json
{
  "schemaCode": "airos.drain",
  "definition": {
    "type": "object",
    "required": ["drainId", "wardCode", "lengthM", "capacityM3PerS"],
    "properties": {
      "drainId":          {"type": "string"},
      "wardCode":         {"type": "string"},
      "lengthM":          {"type": "number"},
      "capacityM3PerS":   {"type": "number"},
      "lastDesiltDate":   {"type": "string", "format": "date"},
      "condition":        {"type": "string", "enum": ["good", "silted", "blocked", "unknown"]},
      "geometry":         {"type": "object"}
    }
  }
}
```

#### Schema 3 — Decision packet (summary record)

```json
{
  "schemaCode": "airos.decision",
  "definition": {
    "type": "object",
    "required": ["packetId", "domain", "decisionId", "wardCode", "urgency", "status"],
    "properties": {
      "packetId":            {"type": "string"},
      "domain":              {"type": "string", "enum": ["air", "flood", "heat", "cross_domain"]},
      "decisionId":          {"type": "string"},
      "wardCode":            {"type": "string"},
      "urgency":             {"type": "string", "enum": ["immediate", "within_4h", "within_24h", "plan"]},
      "sourceAttribution":   {"type": "string"},
      "recommendedAction":   {"type": "string"},
      "escalationRequired":  {"type": "boolean"},
      "status":              {"type": "string", "enum": ["open", "acknowledged", "actioned", "escalated", "resolved", "dismissed"]},
      "timestampBucket":     {"type": "string", "format": "date-time"},
      "workflowInstanceId":  {"type": "string"}
    }
  },
  "x-indexes": [
    {"fieldPath": "wardCode", "method": "btree"},
    {"fieldPath": "status",   "method": "btree"},
    {"fieldPath": "urgency",  "method": "btree"}
  ],
  "webhook": {
    "url": "http://airos:8200/airos/v1/webhooks/decision-updated",
    "events": ["UPDATE"]
  }
}
```

#### Schema 4 — Officer subscription preferences

```json
{
  "schemaCode": "airos.subscription",
  "definition": {
    "type": "object",
    "required": ["officerId", "tenantId", "wardCodes"],
    "properties": {
      "officerId":         {"type": "string"},
      "tenantId":          {"type": "string"},
      "wardCodes":         {"type": "array", "items": {"type": "string"}},
      "domains":           {"type": "array", "items": {"type": "string"}},
      "urgencyThreshold":  {"type": "string", "enum": ["immediate", "within_4h", "within_24h", "plan"]},
      "channels":          {"type": "array", "items": {"type": "string", "enum": ["email", "sms", "whatsapp", "inbox"]}},
      "email":             {"type": "string", "format": "email"},
      "mobile":            {"type": "string"},
      "digestTime":        {"type": "string", "description": "HH:MM local time for daily digest"}
    }
  }
}
```

---

### 4.5 IDGen service — stable entity IDs

AirOS uses IDGen for all business-visible IDs to ensure city-specific
formatting and sequence management.

```json
POST /idgen/v1/generate
X-Tenant-ID: {city_code}

{
  "idRequests": [
    {
      "tenantId": "{city_code}",
      "idName": "airos.decision",
      "count": 1
    }
  ]
}

Response:
{
  "responseInfo": {...},
  "idResponses": [{"id": "AIROS-BLR-2026-000042"}]
}
```

**ID formats (configured in IDGen format store):**

| Entity | Format | Example |
|--------|--------|---------|
| Decision packet | `AIROS-[CITY]-[YYYY]-[SEQ]` | `AIROS-BLR-2026-000042` |
| Sensor station | `SEN-[DOMAIN]-[CITY]-[SEQ]` | `SEN-AIR-BLR-0019` |
| Drain asset | `DRN-[CITY]-[SEQ]` | `DRN-BLR-1042` |

---

## 5. APIs AirOS exposes to DIGIT3

AirOS registers at `/airos/v1` and exposes the following endpoints that
other DIGIT3 modules and the Studio dashboard can call.

### 5.1 Ward climate snapshot

Returns current climate risk scores for a ward or set of wards.

```
GET /airos/v1/ward/{wardCode}/snapshot
X-Tenant-ID: {city_code}

Response:
{
  "wardCode": "BBMP_WARD_007",
  "wardName": "Ward 7 — Shivajinagar",
  "timestampBucket": "2026-05-07T06:00:00Z",
  "aqiScore": 0.72,
  "floodRisk": 0.34,
  "heatRisk": 0.61,
  "qolIndex": 0.54,
  "qolLabel": "Fair",
  "availableDomains": ["air", "heat"],
  "openDecisions": 2
}
```

**Use by other DIGIT3 modules:**
- Building permit service: check flood risk before approving construction
- Grievance service (PGR): enrich a waterlogging complaint with ward flood risk
- HRMS: show officer's ward climate status on their dashboard

### 5.2 Active decisions for a ward

```
GET /airos/v1/ward/{wardCode}/decisions?status=open
X-Tenant-ID: {city_code}

Response:
{
  "wardCode": "BBMP_WARD_007",
  "decisions": [
    {
      "packetId": "AIROS-BLR-2026-000042",
      "domain": "air",
      "decisionId": "AQ-D1",
      "urgency": "within_4h",
      "likelyCause": "Likely open waste burning — early morning spike",
      "recommendedAction": "Dispatch sanitation supervisor...",
      "escalationRequired": false,
      "status": "open",
      "generatedAt": "2026-05-07T06:12:00Z"
    }
  ]
}
```

### 5.3 City-level risk summary

```
GET /airos/v1/city/summary
X-Tenant-ID: {city_code}

Response:
{
  "cityId": "bangalore",
  "timestamp": "2026-05-07T06:00:00Z",
  "wardCount": 198,
  "openDecisions": 14,
  "immediateCount": 2,
  "availableDomains": ["air", "flood", "heat"],
  "worstWards": [
    {"wardCode": "BBMP_WARD_007", "qolIndex": 0.31, "qolLabel": "Critical"}
  ]
}
```

### 5.4 Decision acknowledgement webhook (inbound from DIGIT3 Workflow)

When an officer transitions a workflow instance via the DIGIT3 Workflow
service, DIGIT3 calls this endpoint to sync status back to AirOS.

```
POST /airos/v1/webhooks/decision-updated
X-Tenant-ID: {city_code}

{
  "entityId": "AIROS-BLR-2026-000042",
  "processCode": "AIROS_DECISION",
  "action": "ACTION_TAKEN",
  "comment": "Dispatched crew, burning stopped.",
  "performedBy": "{officer_uuid}",
  "performedAt": "2026-05-07T07:45:00Z",
  "currentState": "ACTIONED"
}
```

AirOS updates its decision packet status and records the outcome observation.

### 5.5 Subscription management

```
POST /airos/v1/subscriptions
GET  /airos/v1/subscriptions?officerId={id}
PUT  /airos/v1/subscriptions/{id}
```

Thin wrapper over Registry `airos.subscription` schema. Officers set their
preferred wards, domains, urgency threshold, and channels.

---

## 6. Role model

AirOS maps to DIGIT3/Keycloak roles. These roles are created in the city
tenant's Keycloak realm on first deployment.

| Role code | Description | Can acknowledge | Can escalate | Can see city summary |
|-----------|-------------|-----------------|-------------|---------------------|
| `AIROS_WARD_ENGINEER` | Ward engineer — sees own ward(s) | Yes | Yes | No |
| `AIROS_ZONAL_OFFICER` | Zonal officer — sees assigned zone | Yes | Yes | Zone only |
| `AIROS_CITY_ADMIN` | Commissioner / city admin — sees full city | Yes | Yes | Yes |
| `AIROS_VIEWER` | Read-only analyst or researcher | No | No | Yes |
| `AIROS_SYSTEM` | Service account for pipeline jobs | N/A | N/A | N/A |

**Workflow action guard examples:**
```json
"attributeValidation": {
  "attributes": {
    "role": ["AIROS_WARD_ENGINEER", "AIROS_ZONAL_OFFICER"]
  }
}
```

**Kong route protection example (in Kong declarative config):**
```yaml
- name: airos-ward-decisions
  paths: ["/airos/v1/ward/*/decisions"]
  plugins:
    - name: keycloak-rbac
      config:
        allowed_roles: ["AIROS_WARD_ENGINEER", "AIROS_ZONAL_OFFICER", "AIROS_CITY_ADMIN"]
```

---

## 7. Data flow — end to end

```
External sensors / APIs
        ↓
AirOS observation store (Parquet, per domain)
        ↓
AirOS feature store (DuckDB, H3 cells)
        ↓
Ward aggregation (QoL index per ward)
        ↓
Decision packet generation (trigger → attribution → action)
        ↓ ── DIGIT3 boundary ──
        ├─→ IDGen:     generate AIROS-{CITY}-{YEAR}-{SEQ} packet ID
        ├─→ Registry:  POST /registry/v1/data/airos.decision
        ├─→ Workflow:  POST /workflow/v1/transition  (action: OPEN, assignees: [ward_engineer_id])
        └─→ Notification: POST /notification/v1/notification/email + /sms
                                        ↓
                              Officer receives email/SMS
                                        ↓
                              Officer acknowledges (web inbox or one-click link)
                                        ↓
                        ── DIGIT3 boundary ──
                        ├─→ Workflow:   POST /workflow/v1/transition (action: ACTION_TAKEN)
                        └─→ AirOS webhook: /airos/v1/webhooks/decision-updated
                                        ↓
                              AirOS updates packet status + outcome observation
                                        ↓
                              SLA job: POST /workflow/v1/auto/AIROS_DECISION/_escalate
```

---

## 8. UPYOG / existing data reuse

When deployed on a UPYOG city (DIGIT 2.x → DIGIT 3.x migration), AirOS can
consume data already present in the platform without re-collection.

| UPYOG data | How AirOS uses it |
|-----------|------------------|
| Ward boundaries (Boundary service) | Replaces synthetic ward grid |
| Officer/employee list (HRMS) | Assignees in Workflow; recipients in Notification |
| Property and buildings (PT module) | Cross-reference flood/heat risk per property |
| Grievance complaints (PGR module) | Waterlogging/burning/heat complaints as AirOS observations |
| Building permits (BPA module) | Active construction → AQI and flood risk correlation |
| Water connections (WS module) | Household-level vulnerability proxy |

**Grievance → observation ingestion:**
When a PGR complaint is filed with category `WATERLOGGING` or `WASTE_BURNING`,
UPYOG can publish to a shared Kafka topic. AirOS subscribes and ingests the
complaint location + timestamp as a weighted observation in the feature store.
This closes the loop: citizen complaints improve the accuracy of the risk model.

---

## 9. WhatsApp gap

DIGIT3 Notification does not support WhatsApp. AirOS fills this with a
thin WhatsApp adapter using the Meta Cloud API.

```
AirOS dispatcher
  ├─→ email/SMS: DIGIT3 Notification service (native)
  └─→ WhatsApp:  AirOS WhatsApp adapter → Meta Cloud API
                  POST https://graph.facebook.com/v18.0/{phone_id}/messages
                  {
                    "to": "{recipient_wa_number}",
                    "type": "template",
                    "template": {
                      "name": "airos_decision_alert",
                      "language": {"code": "en_IN"},
                      "components": [{
                        "type": "body",
                        "parameters": [
                          {"type":"text","text":"{urgency}"},
                          {"type":"text","text":"{ward_name}"},
                          {"type":"text","text":"{recommended_action_short}"},
                          {"type":"text","text":"{short_url}"}
                        ]
                      }]
                    }
                  }
```

The WhatsApp adapter is designed to be replaceable with a DIGIT3 native
WhatsApp channel when eGov adds it to the Notification service.

---

## 10. Deployment topology

```
┌─────────────────────────────────────────────────────┐
│  DIGIT3 platform (city deployment)                  │
│                                                     │
│  Kong API Gateway (:443)                            │
│    ├── /boundary  → Boundary service (:8093)        │
│    ├── /workflow  → Workflow service (:8085)        │
│    ├── /notification → Notification service         │
│    ├── /registry  → Registry service (:8104)        │
│    ├── /idgen     → IDGen service (:8100)           │
│    ├── /studio    → Studio service (:8107)          │
│    └── /airos     → AirOS service (:8200)  ◄────┐  │
│                                                  │  │
│  Keycloak (:8080) — shared identity              │  │
│  PostgreSQL — shared (schema-isolated)           │  │
│  Redis — shared (topic-isolated)                 │  │
└─────────────────────────────────────────────────┼──┘
                                                   │
┌──────────────────────────────────────────────────┴──┐
│  AirOS services                                     │
│                                                     │
│  airos-api (:8200)       REST API + webhook handler │
│  airos-pipeline          domain pipelines (cron)    │
│  airos-dispatcher        notification routing       │
│  airos-dashboard         Streamlit review console   │
│                                                     │
│  DuckDB feature store    (file, mounted volume)     │
│  Parquet obs store       (file, mounted volume)     │
└─────────────────────────────────────────────────────┘
```

AirOS runs alongside DIGIT3 services and calls them over the internal
network. Kong routes `/airos` traffic to the AirOS API container. All
services share the same Keycloak realm and PostgreSQL instance.

---

## 11. Integration roadmap

### Phase 1 — Boundary + Auth (immediate)
Replace synthetic ward grid with Boundary service data. Implement Keycloak
JWT authentication on AirOS APIs. Officers log in once via UPYOG; AirOS
inherits their session.

Deliverables:
- `urban_platform/place/ward_registry.py` → calls Boundary service when available, falls back to synthetic
- AirOS API: Keycloak JWT validation middleware
- DIGIT3 role creation: `AIROS_WARD_ENGINEER`, `AIROS_ZONAL_OFFICER`, `AIROS_CITY_ADMIN`

### Phase 2 — Workflow + Decision Inbox (core value)
Register `AIROS_DECISION` workflow process. Every generated decision packet
creates a workflow instance. Officers acknowledge and action via the inbox.
SLA escalation runs on schedule.

Deliverables:
- `urban_platform/place/ward_decisions.py` → call Workflow + IDGen + Registry on packet emit
- `review_dashboard` inbox view → list officer's open workflow instances
- One-click acknowledge/action links in email

### Phase 3 — Notification (Decision Inbox delivery)
Register email and SMS templates. Wire AirOS dispatcher to call DIGIT3
Notification service instead of sending email/SMS directly.

Deliverables:
- `airos-dispatcher` service — reads subscriptions, batches by cadence, calls Notification
- Email and SMS templates registered per tenant
- Daily digest job

### Phase 4 — Registry + UPYOG data reuse
Register AirOS schemas. Ingest real ward boundaries, officer assignments,
and PGR complaints from the UPYOG deployment.

Deliverables:
- Schema registration scripts for `airos.sensor`, `airos.drain`, `airos.decision`, `airos.subscription`
- PGR complaint Kafka consumer → AirOS observation store
- Property flood/heat risk API for building permit service

### Phase 5 — WhatsApp + production hardening
WhatsApp delivery adapter. Multi-city production deployment. Kubernetes
manifests (pending DIGIT3 K8s support).

---

## 12. Open questions for eGov / NIUA

1. **DIGIT3 release timeline** — when will DIGIT3 services be production-ready
   (versioned releases, not `develop-*` images)? This gates Phase 2 deployment.

2. **UPYOG HRMS migration** — does UPYOG HRMS data (officer assignments to
   wards) migrate to DIGIT3 HRMS, or will it live in MDMS for the near term?

3. **PGR Kafka integration** — is there a standard Kafka topic schema for
   DIGIT3 PGR complaint events that AirOS should conform to?

4. **WhatsApp plan** — is eGov planning native WhatsApp support in the
   Notification service? If so, AirOS's adapter should be designed to swap
   out without re-engineering the dispatcher.

5. **Multi-city SaaS model** — does eGov have a preferred multi-tenant hosting
   model for DIGIT3 (shared cluster per state, per city, or national)? AirOS
   deployment topology follows this answer.
