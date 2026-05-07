# AIROS Platform — DIGIT3 Infrastructure Specification

## 1. Purpose

DIGIT3 is the infrastructure layer embedded within AIROS. This document
specifies how AIROS configures and uses DIGIT3 services — which services it
depends on, the exact API calls at each boundary, the data contracts, and the
provisioning sequence for a new city deployment.

AIROS is the platform. DIGIT3 is its foundation. A city deploys AIROS and
receives a fully-working urban climate platform; DIGIT3 is an implementation
detail of that deployment, not its host.

See [`AIR_PLATFORM_ARCHITECTURE.md`](AIR_PLATFORM_ARCHITECTURE.md) for the
full three-layer positioning (AIROS / AIRNet / AIR Climate Suite).

---

## 2. AIROS identity within DIGIT3

AIROS registers itself with DIGIT3's Studio service so that DIGIT3 tooling
(dashboards, audit, service discovery) can locate and manage it. This
registration does not make AIROS subordinate to DIGIT3 — it is the mechanism
by which AIROS declares its API surface and governance bindings to the
infrastructure layer it runs on.

| Field | Value |
|-------|-------|
| **Service code** | `airos` |
| **Service name** | AIROS — Urban Climate Platform |
| **Module type** | `GOVERNANCE` |
| **Version** | `1.0.0` |
| **API base path** | `/airos/v1` |
| **DIGIT3 services used** | `boundary`, `workflow`, `notification`, `registry`, `idgen`, `governance`, `account` |

**Studio service registration** — full `serviceDefinition` (called once per city deployment):

```json
POST /studio/v1/services
X-Tenant-ID: {city_code}
X-Client-ID: airos-admin

{
  "serviceCode": "airos",
  "name": "AIROS — Urban Climate Platform",
  "moduleType": "GOVERNANCE",
  "status": "ACTIVE",
  "metadata": {
    "version": "1.0.0",
    "description": "Urban climate decision platform — ward-level QoL scoring, multi-domain decision packets, officer Decision Inbox, and governance accountability for the AIR Climate Suite.",
    "apiBaseUrl": "http://airos:8200",
    "domains": ["air", "flood", "heat"],
    "dependencies": ["boundary", "workflow", "notification", "registry", "idgen", "governance", "account"]
  },
  "serviceDefinition": {
    "caseModel": {
      "fields": [
        {"name": "packetId",           "type": "string",  "required": true},
        {"name": "domain",             "type": "string",  "required": true},
        {"name": "wardCode",           "type": "string",  "required": true},
        {"name": "urgency",            "type": "string",  "required": true},
        {"name": "sourceAttribution",  "type": "string",  "required": false},
        {"name": "rulesetVersion",     "type": "integer", "required": true}
      ]
    },
    "governance": {
      "rulesetBindings": [
        "airos_air_decisions_v1",
        "airos_flood_decisions_v1",
        "airos_heat_decisions_v1",
        "airos_cross_domain_v1"
      ]
    },
    "workflow": {
      "verificationProcessCode": "AIROS_DECISION"
    },
    "appeals": {
      "enabled":        true,
      "appellateRole":  "AIROS_ZONAL_OFFICER"
    }
  }
}
```

After creation, run two Studio jobs to activate:

```json
// Bind governance rulesets
POST /studio/v1/jobs
{ "jobType": "APPLY_RULESETS", "serviceCode": "airos", "tenantId": "{city_code}" }

// Publish service (makes it live)
POST /studio/v1/jobs
{ "jobType": "PUBLISH_SERVICE", "serviceCode": "airos", "tenantId": "{city_code}" }
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

**Registry `as_of` gap and resolver wrapper:**

Registry records carry `effectiveFrom`/`effectiveTo` per version but expose no
endpoint that accepts a timestamp and returns the version active at that moment.
GCP requires that AirOS can reconstruct which sensor or drain record was in
effect when a decision was made.

AirOS ships a thin `RegistryResolver` utility (~25 lines):

```python
def resolve_as_of(schema_code: str, entity_id: str, as_of: str, tenant_id: str) -> dict:
    """Return the Registry record version active at as_of (ISO-8601 timestamp)."""
    resp = registry_client.get(
        f"/registry/v1/data/{schema_code}/{entity_id}",
        params={"history": "true"},
        headers={"X-Tenant-ID": tenant_id},
    )
    versions = resp.json().get("records", [])
    # Filter to versions where effectiveFrom <= as_of and (effectiveTo is null or > as_of)
    active = [
        v for v in versions
        if v.get("effectiveFrom", "") <= as_of
        and (not v.get("effectiveTo") or v["effectiveTo"] > as_of)
    ]
    if not active:
        raise RegistryVersionNotFound(schema_code, entity_id, as_of)
    return max(active, key=lambda v: v["effectiveFrom"])
```

This wrapper is invoked by the Governance receipt builder to snapshot the exact
sensor state that fed a decision, enabling full reconstruction.

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

### 4.6 Governance service — decision rules, traces, and receipts

The Governance service stores versioned YAML rulesets, validates facts against
a JSON Schema contract, emits hash-chained decision traces, and manages an
appeals/orders lifecycle. AirOS publishes its attribution and triage rules here
so that every climate decision is backed by a contestable, auditable rule.

This is the GCP alignment point: source attribution logic moves from hard-coded
Python into governed, versioned rulesets with published limitations.

#### 4.7.1 Ruleset structure (YAML, stored in Governance service)

**Air quality decisions ruleset** (`airos_air_decisions_v1`):

```yaml
rulesetId: airos_air_decisions_v1
version: 1
description: >
  Triage rules for ward-level air quality decision packets.
  Source attribution is based on time-of-day patterns and AQI magnitude.
  Limitations: no direct emission source data; inference is probabilistic.
factsContract:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  required: [avg_aqi_score, timestamp_bucket, hour_of_day]
  properties:
    avg_aqi_score:    {type: number, minimum: 0, maximum: 1}
    timestamp_bucket: {type: string, format: date-time}
    hour_of_day:      {type: integer, minimum: 0, maximum: 23}
    cell_count:       {type: integer}
rules:
  - ruleId: AQ-R1
    description: "High AQI + early morning (05–08h) → waste burning probable"
    condition:
      and:
        - {field: avg_aqi_score, op: gte, value: 0.60}
        - {field: hour_of_day,   op: gte, value: 5}
        - {field: hour_of_day,   op: lte, value: 8}
    outcome:
      decision_id:        AQ-D1
      urgency:            within_4h
      source_attribution: waste_burning
      confidence:         medium
  - ruleId: AQ-R2
    description: "Immediate AQI (≥0.80) → immediate urgency"
    condition:
      {field: avg_aqi_score, op: gte, value: 0.80}
    outcome:
      decision_id:        AQ-D2
      urgency:            immediate
      source_attribution: traffic_or_industrial
      confidence:         medium
  - ruleId: AQ-R3
    description: "Moderate AQI (0.40–0.60) outside morning → mixed sources"
    condition:
      and:
        - {field: avg_aqi_score, op: gte, value: 0.40}
        - {field: avg_aqi_score, op: lt,  value: 0.60}
    outcome:
      decision_id:        AQ-D4
      urgency:            within_24h
      source_attribution: mixed_sources
      confidence:         low
```

**Flood decisions ruleset** and **heat decisions ruleset** follow the same
structure (see `docs/architecture/WARD_DECISION_CATALOGUE.md` for thresholds).

#### 4.7.2 Publishing a ruleset (called during provisioning)

```json
POST /governance/v1/rulesets
X-Tenant-ID: {city_code}

{
  "rulesetId": "airos_air_decisions_v1",
  "version": 1,
  "content": "<base64-encoded YAML above>",
  "tenantId": "{city_code}"
}
```

#### 4.7.3 Emitting a decision trace (called by AirOS on every packet)

```json
POST /governance/v1/decisions
X-Tenant-ID: {city_code}

{
  "rulesetId":      "airos_air_decisions_v1",
  "rulesetVersion": 1,
  "entityType":     "airos.decision",
  "entityId":       "AIROS-BLR-2026-000042",
  "facts": {
    "avg_aqi_score":    0.72,
    "timestamp_bucket": "2026-05-07T06:00:00Z",
    "hour_of_day":      6,
    "cell_count":       18
  },
  "outcome": {
    "decision_id":        "AQ-D1",
    "urgency":            "within_4h",
    "source_attribution": "waste_burning",
    "confidence":         "medium"
  },
  "tenantId": "{city_code}"
}
```

The Governance service responds with a `decisionReceipt`:

```json
{
  "receiptId":       "gov-rcpt-8f3a9c",
  "entityId":        "AIROS-BLR-2026-000042",
  "rulesetId":       "airos_air_decisions_v1",
  "rulesetVersion":  1,
  "factsHash":       "sha256:a1b2c3...",
  "outcomeHash":     "sha256:d4e5f6...",
  "chainHash":       "sha256:g7h8i9...",
  "issuedAt":        "2026-05-07T06:12:05Z",
  "contestationUrl": "/governance/v1/appeals?entityId=AIROS-BLR-2026-000042"
}
```

The `chainHash` links this receipt to the previous receipt in the sequence,
providing tamper-evident continuity (GCP audit trail).

#### 4.7.4 Appeals lifecycle

If a ward engineer believes the decision is incorrect (e.g. wrong source
attribution), they can raise an appeal:

```json
POST /governance/v1/appeals
X-Tenant-ID: {city_code}
Authorization: Bearer {officer_jwt}

{
  "entityId":   "AIROS-BLR-2026-000042",
  "rulesetId":  "airos_air_decisions_v1",
  "reason":     "INCORRECT_ATTRIBUTION",
  "evidence":   "Field inspection found no burning; spike likely from passing vehicle convoy.",
  "tenantId":   "{city_code}"
}
```

Appeals are reviewed by `AIROS_ZONAL_OFFICER` role and can result in:
- `UPHELD` → source attribution corrected; ruleset limitation noted for next review cycle
- `DISMISSED` → original decision stands; reason logged

Every upheld appeal feeds back into the ruleset review process, closing the
governance loop.

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
        ↓ ── DIGIT3 boundary ──────────────────────────────────────────────
        │
        ├─→ IDGen:        generate AIROS-{CITY}-{YEAR}-{SEQ} packet ID
        │
        ├─→ Governance:   POST /governance/v1/decisions
        │                   facts + ruleset → decisionReceipt (hash chain)
        │
        ├─→ Registry:     POST /registry/v1/data/airos.decision
        │
        ├─→ Workflow:     POST /workflow/v1/transition
        │                   (action: OPEN, assignees: [ward_engineer_id])
        │
        └─→ Notification: POST /notification/v1/notification/email + /sms
                                        ↓
                              Officer receives email/SMS
                                        ↓
                              Officer acknowledges (web inbox or one-click link)
                                        ↓
                        ── DIGIT3 boundary ──────────────────────────────────
                        │
                        ├─→ Workflow:     POST /workflow/v1/transition
                        │                  (action: ACTION_TAKEN)
                        │
                        └─→ AirOS webhook: /airos/v1/webhooks/decision-updated
                                        ↓
                              AirOS updates packet status + outcome observation
                                        ↓
                              SLA job: POST /workflow/v1/auto/AIROS_DECISION/_escalate

Officer raises appeal (if attribution disputed):
        └─→ Governance: POST /governance/v1/appeals
                          reviewed by AIROS_ZONAL_OFFICER
                          upheld → feeds back into ruleset review cycle

AirOS → AIRNet (separate service, see AIRNET_COORDINATION_SPEC.md):
        Entity graph, event trail, and cross-system traces are managed by
        AIRNet, not DIGIT3. AirOS calls AIRNet APIs in parallel with
        the DIGIT3 calls above.
```

---

## 8. DIGIT3 platform data reuse

When deployed alongside a city's DIGIT3 installation, AirOS can consume data
already present in the platform without re-collection.

| DIGIT3 data | How AirOS uses it |
|------------|------------------|
| Ward boundaries (Boundary service) | Replaces synthetic ward grid |
| Officer/employee list (HRMS) | Assignees in Workflow; recipients in Notification |
| Property and buildings (PT module) | Cross-reference flood/heat risk per property |
| Grievance complaints (PGR module) | Waterlogging/burning/heat complaints as AirOS observations |
| Building permits (BPA module) | Active construction → AQI and flood risk correlation |
| Water connections (WS module) | Household-level vulnerability proxy |

**Grievance → observation ingestion:**
When a PGR complaint is filed with category `WATERLOGGING` or `WASTE_BURNING`,
the DIGIT3 platform can publish to a shared Kafka topic. AirOS subscribes and
ingests the complaint location + timestamp as a weighted observation in the
feature store. Citizen complaints improve the accuracy of the risk model.

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
WhatsApp channel if it is added to the Notification service in a future release.

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
JWT authentication on AirOS APIs. Officers log in once via DIGIT3/Keycloak;
AirOS inherits their session.

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

### Phase 4 — Governance + Registry (accountability layer)
Publish decision rulesets to Governance service. Register AirOS Registry
schemas. Ingest DIGIT3 platform data (PGR complaints, officer assignments).
AIRNet entity graph integration is a parallel track (see
`AIRNET_COORDINATION_SPEC.md`).

Deliverables:
- Governance rulesets: `airos_air_decisions_v1`, `airos_flood_decisions_v1`, `airos_heat_decisions_v1`, `airos_cross_domain_v1`
- `RegistryResolver` utility for `as_of` record resolution (GCP reconstruction)
- `ward_decisions.py` → emit Governance `decisionReceipt` on every packet
- Schema registration scripts: `airos.sensor`, `airos.drain`, `airos.decision`, `airos.subscription`
- PGR complaint Kafka consumer → AirOS observation store
- Property flood/heat risk API for building permit service
- `provision_city.py` script (full 11-step idempotent provisioning)

### Phase 5 — WhatsApp + production hardening
WhatsApp delivery adapter. Multi-city production deployment. Kubernetes
manifests (pending DIGIT3 K8s support).

---

## 12. Provisioning sequence

A complete AirOS deployment on a new city tenant follows this exact sequence.
Steps that are DIGIT3-native (Account, Registry, IDGen, Studio, Governance,
Workflow, Notification) are idempotent and can be re-run safely.

```
Step 1 — Create tenant (Account service)
  POST /account/v1/tenant
  { "tenantId": "bangalore", "name": "Bruhat Bengaluru Mahanagara Palike" }
  → Keycloak realm created, shared PostgreSQL tenant schema provisioned

Step 2 — Register Registry schemas
  POST /registry/v1/schema  ×4
  airos.sensor, airos.drain, airos.decision, airos.subscription
  (see §4.4 for schema definitions)

Step 3 — Register IDGen templates
  POST /idgen/v1/format  ×3
  airos.decision  → AIROS-[CITY]-[YYYY]-[SEQ]
  airos.sensor    → SEN-[DOMAIN]-[CITY]-[SEQ]
  airos.drain     → DRN-[CITY]-[SEQ]

Step 4 — Publish Governance rulesets
  POST /governance/v1/rulesets  ×4
  airos_air_decisions_v1, airos_flood_decisions_v1,
  airos_heat_decisions_v1, airos_cross_domain_v1
  (rulesets must be published BEFORE service goes live — GCP requirement)

Step 5 — Register Studio service definition
  POST /studio/v1/services
  (full serviceDefinition from §2, including rulesetBindings + workflow code)

Step 6 — Activate via Studio jobs
  POST /studio/v1/jobs  { jobType: APPLY_RULESETS, serviceCode: airos }
  POST /studio/v1/jobs  { jobType: PUBLISH_SERVICE, serviceCode: airos }

Step 7 — Create Keycloak roles in city realm
  AIROS_WARD_ENGINEER, AIROS_ZONAL_OFFICER, AIROS_CITY_ADMIN,
  AIROS_VIEWER, AIROS_SYSTEM

Step 8 — Create Workflow process
  POST /workflow/v1/process    (AIROS_DECISION)
  POST /workflow/v1/process/{id}/state  ×6  (OPEN → RESOLVED lifecycle)
  POST /workflow/v1/state/{id}/action   ×6  (ACKNOWLEDGE, ACTION_TAKEN, …)

Step 9 — Register Notification templates
  POST /notification/v1/template  ×3
  AIROS_DECISION_EMAIL, AIROS_DECISION_SMS, AIROS_DIGEST_EMAIL

Step 10 — Seed AIRNet entities (separate service)
  POST /airnet/v1/entities  (one per ward — see AIRNET_COORDINATION_SPEC.md)
  This step is skipped if AIRNet is not deployed in this environment.

Step 11 — Smoke test
  POST /airos/v1/ward/{any_ward}/snapshot  → expect QoL scores
  POST /governance/v1/decisions  (synthetic facts) → expect decisionReceipt
  Check Notification service queue for test email delivery
```

A `scripts/provision_city.py` script in the AirOS repo wraps these steps
with idempotency checks and rolls back on any failure.

---

## 13. GCP alignment — Inference Objects and contested attribution

The Government Coordination Protocol (GCP) requires that every public decision
that uses inference or discretion must reference a **published, versioned
Inference Object** that existed *before* the inference was applied.

In AirOS, source attribution (e.g. "early morning AQI spike → waste burning")
is discretionary inference. Under GCP:

**Before DIGIT3 integration:** this logic is embedded in Python code in
`urban_platform/place/ward_decisions.py:_attribute_air()`. It is correct but
not independently published, versioned, or contestable.

**After DIGIT3/GCP integration:** the same logic becomes a Governance ruleset
(`airos_air_decisions_v1`) published before any decision is made. Each
ruleset:

| GCP requirement | DIGIT3 / AirOS implementation |
|-----------------|-------------------------------|
| Published before use | Ruleset published in Step 4 of provisioning, before service goes live (Step 6) |
| Versioned | `rulesetVersion` incremented on every rule change; old versions remain queryable |
| Independently contestable | `POST /governance/v1/appeals?entityId={packet}` available to any AIROS_WARD_ENGINEER |
| Limitations declared | `description` and `confidence` fields in each rule outcome |
| Auditable receipt | `decisionReceipt` with `factsHash`, `outcomeHash`, `chainHash` |
| Reconstructable | `RegistryResolver.resolve_as_of()` recreates sensor state at decision time |

**Decision Object anatomy** (the GCP atomic unit, as emitted by AirOS):

```
AirOS decision packet
  ├── rule_reference:      airos_air_decisions_v1, version 1, rule AQ-R1
  ├── evidence_snapshot:   avg_aqi_score=0.72, hour_of_day=6, timestamp=…
  │                        (Registry record version, retrieved via RegistryResolver)
  ├── inference_reference: airos_air_decisions_v1 (published before use)
  ├── reasoning_trace:     "AQI 0.72 ≥ 0.60, hour 6 in [5,8] → waste_burning (medium)"
  ├── outcome:             decision_id=AQ-D1, urgency=within_4h
  ├── governance_receipt:  receiptId=gov-rcpt-8f3a9c, chainHash=sha256:…
  └── contestation_path:   /governance/v1/appeals?entityId=AIROS-BLR-2026-000042
```

**Key constraint:** when a ruleset changes (e.g. the waste burning time window
is adjusted from 05–08h to 04–09h based on field data), the old version is
preserved. Decisions made under v1 are always reconstructable against v1 rules,
not silently re-evaluated against v2. This prevents retroactive change of
official decisions — a hard GCP requirement.

---

## 14. Open questions for DIGIT3 platform teams

1. **DIGIT3 release timeline** — when will DIGIT3 services be production-ready
   (versioned releases, not `develop-*` images)? This gates Phase 2 deployment.
   Governance and Studio are on the `coordination-integration-20260408` branch
   and not yet in upstream master.

2. **HRMS officer data** — does DIGIT3 HRMS carry officer-to-ward assignment
   data, or does this live in MDMS for the near term? AirOS Workflow assignees
   need officer user IDs at packet creation time.

3. **PGR Kafka integration** — is there a standard Kafka topic schema for
   DIGIT3 PGR complaint events that AirOS should conform to?

4. **WhatsApp in Notification service** — is native WhatsApp support planned
   for the Notification service? AirOS's Meta Cloud API adapter is designed to
   swap out without re-engineering the dispatcher.

5. **Multi-city hosting model** — is there a preferred multi-tenant hosting
   topology for DIGIT3 (shared cluster per state, per city, or national)?

6. **Governance service DSL extension** — the current Governance YAML DSL
   supports `eq` and `present` predicates. AirOS attribution rules require
   `gte`/`lte` numeric comparisons. Should AirOS pre-evaluate thresholds and
   pass boolean results as enriched facts, or is predicate extension planned?
