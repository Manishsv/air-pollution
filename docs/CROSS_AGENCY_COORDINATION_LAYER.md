# Cross-agency coordination layer — AirOS Network Layer

This document specifies the **intent and boundaries** of the **AirOS Network Layer**: the optional, **domain-agnostic**, **contract-aware**, **policy-enforcing** facility that routes **messages** between **AirOS Nodes** when agencies must interoperate **without** sharing a single monolithic deployment.

It is analogous in role to **protocol and transport semantics** (e.g. addressing, sequencing, acknowledgement, congestion/retry discipline)—**not** to application-level reasoning about pollutants, floods, buildings, traffic, tax, or enforcement.

Companion documents: [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md), [`docs/AGENCY_NODE_MODEL.md`](AGENCY_NODE_MODEL.md).

---

## Positioning

| Question | Answer |
|----------|--------|
| Is the Network Layer required? | **No.** Many nodes operate **standalone**. |
| Is it “another product”? | **No.** It is **native** to the AirOS reference architecture but **separately deployable**. |
| Does it interpret PM2.5, flood stages, permits, SLA rules? | **No.** Domain semantics remain in **domain specs** and **applications**. |
| What does it do? | Validates **message envelopes**, **contract references**, **authorization**, **routing**, **delivery state**, **audit/provenance linkage**—and invokes **generic** schema validation for payloads keyed by `schema_ref`. |

---

## AirOS Core vs Network Layer vs domain stack

```
┌─────────────────────────────────────────────────────────────┐
│  Domain specs · applications · decision workflows · review  │  ← meaning, thresholds, gates
├─────────────────────────────────────────────────────────────┤
│  Consumer/provider contracts · platform objects · conform.  │  ← shared language
├─────────────────────────────────────────────────────────────┤
│  AirOS Network Layer (optional)                              │  ← envelope, policy, routing, audit
├─────────────────────────────────────────────────────────────┤
│  Transports: email (Phase 1), API, webhook, bus, file, …     │  ← carriers (not the layer itself)
└─────────────────────────────────────────────────────────────┘
```

The **same logical message** should be expressible across **multiple transports**; transports differ in **capacity, latency, security, and ops maturity**, not in **domain meaning**.

---

## Message envelope (conceptual contract)

The Network Layer is **contract-aware**: it knows **how** a message is addressed and **which schema** governs the payload body. It does **not** embed domain rules.

**Fields the Network Layer understands (illustrative):**

| Field | Role |
|--------|------|
| `message_id` | Idempotency, deduplication, audit correlation |
| `message_type` | Logical type (e.g. `decision_packet_exchange`, `task_handoff`)—**not** a domain enum like “air_action_level_3” |
| `schema_ref` | Pointer to a **registered** contract (e.g. consumer schema URI / manifest ID) |
| `from_node` / `to_node` | Participant identity consistent with **`node_id`** / **`network_participant`** profiles |
| `jurisdiction_refs` | Stable references to jurisdictions (IDs), not adjudication outcomes |
| `purpose` | Allowable routing purpose (coordination metadata), not operational orders |
| `data_classification` | Drives policy (e.g. public / official / restricted) |
| `authorization_policy` | Reference to applicable sharing / MoU policy artifact |
| `delivery_status` | Transport state machine hooks |
| `acknowledgement` | Receipt semantics (who acknowledged, when) |
| `retry_audit_metadata` | Attempt counts, backoff, dead-letter linkage |
| `provenance_references` | Links to lineage records **without** the layer re-deriving domain provenance |

**Payload validation:** the layer may invoke a **generic** JSON Schema (or successor) validator for the body **using `schema_ref`**—never hand-written domain predicates.

---

## What the Network Layer must **not** do

- Embed **domain-specific validation** (“if PM2.5 > X then reject”) unless expressed as **data-driven policy attachments** formally outside domain reasoning (preferred: stay in agency workflow tools).  
- **Make operational decisions** or convert decision-support artifacts into **binding orders**.  
- **Override** lawful agency authority or human-review requirements.  
- **Expose sensitive data** inconsistent with `data_classification` and `authorization_policy`.  
- Understand **traffic congestion models**, **water pressure**, **sanitation SLA logic**, **tax rules**, **enforcement escalation**, etc.

Those belong to **domain applications**, **domain specs**, **agency SOPs**, and **human review**.

---

## What the Network Layer **may** do

- Validate **structural envelope** completeness and semantic consistency of envelope fields  
- Resolve **`schema_ref`** against a known **manifest / catalog** (“known contract”)  
- Enforce **routing rules** (which `to_node` may receive which `message_type` under which policy)  
- Preserve **audit trails** and **delivery receipts**  
- Coordinate **retry** and **non-repudiation-oriented** logging (design-time choice, jurisdiction-dependent)  
- Invoke **generic** payload validation against the referenced schema  

---

## Cross-agency coordination patterns

| Pattern | Description |
|---------|-------------|
| **Publish / subscribe event** | Nodes emit **contract-shaped** events; subscribers receive **envelopes** matching policy. |
| **Request / response data access** | Time-bounded access to an allowed consumer shape (still spec-bound). |
| **Decision packet exchange** | Route **decision/review packets** to entitled recipients; no automatic “accept.” |
| **Field task handoff** | Transfer **field task** payloads between agencies with acknowledgement. |
| **Agency response status** | Status-only messages (received / in review / cannot act / needs info). |
| **Aggregated state-level observability** | Roll-ups that remain **contract-shaped** and **classification-safe** (no silent merge of restricted layers). |
| **Public transparency feed** | Emits **public-safe** derivatives per consumer contract; policy strips or redacts. |

---

## Air pollution example (routing vs meaning)

**Scenario:** A domain application (air quality) produces a **hotspot decision packet** under **`air_quality` domain spec** and **consumer contract**—including **review prompts**, **uncertainty**, and **blocked uses**.

**Network Layer role:**

1. Wrap the packet in a **`decision_packet_exchange`**-class message with `schema_ref` → the **decision packet consumer schema**.  
2. Route **copies or scoped views** to entitled nodes, e.g.:  
   - Pollution control board  
   - ULB / sanitation  
   - Traffic police  
   - Construction / building authority  
   - Health / education  
   - City administrator / disaster cell  
3. Record **delivery** and **acknowledgements**; apply **classification** (operational vs public transparency).  
4. Optionally attach **field tasks** to agencies that own follow-up verification.

**Not** the Network Layer’s job: deciding **which agency must act**, **what legal instrument applies**, or **whether** a hotspot is “real” for enforcement—that stays in **domain meaning**, **agency workflow**, and **human review**.

---

## Email as a Phase 1 **transport adapter** (not the Network Layer)

Email is a **practical, low-friction carrier** in fragmented governance environments. It is **not** the Network Layer and **not** a substitute for durable APIs where scale or security demands them.

**Clarifications**

- **Email = transport adapter.** The **AirOS Network Layer** remains **domain-agnostic** and **contract-aware**; email only **carries** standardized **AirOS message envelopes** and **payloads**.  
- **Payload form:** JSON **attachments** and/or **structured sections** in the body that map 1:1 to the same logical envelope fields used on other transports.  
- **Good fit:** low-frequency **coordination**, **task handoffs**, **decision packet** sharing (where policy allows), **acknowledgements**, **status updates**.  
- **Poor fit:** high-frequency **sensor streams**, **real-time** control loops, **large geospatial** bulk transfers, **sensitive personal data** without **stronger controls** (encryption, DLP, dedicated channels).  
- **Future transports:** HTTPS APIs, webhooks, event buses, SFTP/file drops, national exchange fabrics (e.g. IUDX-class patterns), Beckn-like networks, secure message queues—the **same envelope** should port across carriers.  

Operational security (SPF/DKIM/DMARC, encryption, attachment policies) is **deployment policy**, not domain logic.

---

## Future specifications (names only; not implemented here)

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

Until these exist, treat cross-agency integration as **documentation + private deployment playbooks**—not ad-hoc code paths that bypass specs.

---

## Forward deployment checklist (coordination-specific)

Before enabling the Network Layer (even with email transport):

- Map **senders and receivers** as **nodes** / **participants**  
- Map **message types** actually needed (avoid “sync everything”)  
- Map **classification** and **legal basis** for each flow  
- Confirm **consumer contracts** on both sides  
- Define **human review** touchpoints for high-risk packets  
- Choose **transport** per pattern (email vs API vs file) without changing **envelope semantics**
