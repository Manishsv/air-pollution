# AirOS Network — Node Model and Federation Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Network

---

## Purpose [INFORMATIVE]

This document defines what an AirOS node is, how nodes identify themselves, and how two or more AirOS instances coordinate across jurisdictional boundaries. The Network layer is optional — a single-node deployment operates fully without it. When present, it enables nodes to share signals, risk assessments, insights, and advisory candidates so that city operators can make decisions with awareness of conditions beyond their own boundaries.

**Coordination use cases:**

| Scenario | Sender | Receiver | What is shared |
|----------|--------|----------|---------------|
| Upstream flood early warning | Watershed authority node | Downstream city node | Flood risk signals + severity assessment |
| Regional air quality event | State node | Multiple city nodes | AQ signals, city pattern summary |
| Cross-border construction dust | City A node | Adjacent City B node | Construction signals + advisory candidate |
| Festival crowd spillover | City node | Traffic authority node | Crowd density signals + gathering alert |
| District emergency response | District node | Ward-level nodes | Field task request |

Each node remains sovereign: it runs its own Core, applies its own Rules Registry, and makes its own review decisions. The Network layer carries data between nodes; it never centralises control or creates a dependency on a central server.

---

## What a Node Is [NORMATIVE]

An AirOS node is a complete, independently-operated AirOS deployment. It consists of:

- A Core (Knowledge Store, Rules Registry, Scheduler) serving one or more cities
- Zero or more active Drivers
- Zero or more active Apps
- A node identity declaration (see below)

A node MUST:
- Have a unique, persistent `node_id` within any federation it participates in
- Declare the jurisdictions it serves
- Declare which message types it accepts from which counterparties
- Operate its Core independently — it MUST NOT share a Knowledge Store with another node

A node MUST NOT:
- Route domain logic decisions through a central authority
- Accept data payloads that bypass its own Driver conformance gate
- Apply another node's risk classification rules to its own cells without explicit operator configuration

---

## Node Identity Declaration [NORMATIVE]

Every node MUST maintain a node identity record with these fields:

```
NodeIdentity {
  node_id:           string   REQUIRED  — globally unique identifier (URL, URN, or UUID)
  display_name:      string   REQUIRED  — human-readable name (e.g. "Bangalore BBMP Node")
  operator:          string   REQUIRED  — operating organisation
  jurisdictions:     list     REQUIRED  — list of jurisdiction identifiers (city codes, admin boundaries)
  airos_spec_version: string  REQUIRED  — AirOS specification version this node implements (e.g. "1.0.0")
  contact:           string   OPTIONAL  — operator contact for federation enquiries
  public_endpoint:   string   OPTIONAL  — URL of this node's Network API (if participating in federation)
}
```

The `node_id` SHOULD be an HTTPS URL that resolves to the node's public identity document, or a URN in the form `urn:airos:node:<operator>:<deployment>`.

---

## Message Envelope [NORMATIVE]

All inter-node messages MUST be wrapped in the AirOS message envelope. The normative schema is defined in:

```
specifications/network_contracts/message_envelope.v1.schema.json
```

Key envelope fields (summary — see schema for full specification):

| Field | Required | Description |
|-------|----------|-------------|
| `message_id` | YES | Globally unique message identifier (idempotency token) |
| `message_type` | YES | What kind of message this is (see Message Types below) |
| `schema_ref` | YES | Contract key of the payload schema |
| `from_node` | YES | Sending node's `node_id` |
| `to_node` | YES | Receiving node's `node_id` (or array for multicast) |
| `jurisdiction_refs` | YES | Jurisdictions this message pertains to |
| `purpose` | YES | Routing metadata — why this message is being sent |
| `data_classification` | YES | `public` / `official_sensitive` / `restricted` / `internal` |
| `created_at` | YES | ISO-8601 timestamp |
| `priority` | YES | `low` / `normal` / `elevated` / `high` / `urgent` |
| `requires_ack` | YES | Whether the sender expects a delivery receipt |

Every envelope MUST include either `payload_ref` (reference to separately-validated payload) or `payload_hash` (integrity digest), or both.

---

## Message Types [NORMATIVE]

| `message_type` | Direction | Description |
|---------------|-----------|-------------|
| `observation_published` | Sender → Receiver | A Driver has produced new signal data for cells the receiver may be interested in |
| `assessment_published` | Sender → Receiver | A risk assessment has been written for cells in or near the receiver's jurisdiction |
| `event_published` | Sender → Receiver | A significant event was detected (fire, flood, gathering) |
| `insight_shared` | Sender → Receiver | An agent insight from the sender is shared for the receiver's situational awareness — the receiver MUST treat it as external evidence requiring its own review, not as a confirmed finding |
| `decision_packet_shared` | Sender → Receiver | A decision packet from the sender's domain is offered to the receiver |
| `advisory_candidate_shared` | Sender → Receiver | An advisory candidate (not yet approved) is shared for the receiver's situational awareness |
| `summary_published` | Sender → Receiver | A city pattern summary is shared (e.g. upstream watershed sharing flood risk synthesis) |
| `field_task_requested` | Sender → Receiver | A sender requests a field action in the receiver's jurisdiction |
| `field_task_response` | Receiver → Sender | Response to a `field_task_requested` |
| `data_request` | Sender → Receiver | A sender requests specific signals or assessments from the receiver's Knowledge Store |
| `data_response` | Receiver → Sender | Response to a `data_request` |
| `agency_status_update` | Sender → All | Node availability, jurisdiction update, or configuration change |

---

## Delivery Receipt [NORMATIVE]

When `requires_ack = true` in an envelope, the receiving node MUST send a delivery receipt. The normative schema is defined in:

```
specifications/network_contracts/delivery_receipt.v1.schema.json
```

Key receipt fields:

| Field | Required | Description |
|-------|----------|-------------|
| `receipt_id` | YES | Unique identifier for this receipt |
| `message_id` | YES | The `message_id` being acknowledged |
| `receipt_type` | YES | `delivery_ack` / `delivery_nack` / `processing_ack` / `processing_nack` |
| `status` | YES | `delivered` / `received` / `accepted` / `rejected` / `processed` / `failed` |
| `retryable` | YES | Whether the sender may retry on failure |
| `delivery_attempt` | YES | Monotonic counter — 1 for first attempt |

---

## Network Layer Responsibilities [NORMATIVE]

The Network layer MUST:
- Validate message envelopes against the `message_envelope.v1.schema.json` schema before forwarding
- Check `data_classification` against the receiving node's declared acceptance policies
- Issue delivery receipts when `requires_ack = true`
- Log all relay events in an audit trail

The Network layer MUST NOT:
- Inspect or interpret domain-specific payload content
- Apply domain risk rules to payload data
- Call Driver or App code directly
- Store payload data beyond what is required for delivery and audit

**Separation principle:** The Network layer is a smart envelope router. All domain intelligence stays in Drivers and Apps.

---

## Data Ownership [NORMATIVE]

Each node retains full ownership of the data in its own Knowledge Store. Sharing a message via the Network layer does not transfer ownership.

A receiving node that ingests data from a `data_response` or `observation_published` or `assessment_published` message MUST:
- Write it to its own Knowledge Store through its own conformance gate
- Preserve the `source`, `data_quality`, and originating `node_id` provenance from the original payload
- NOT overwrite existing local signals with received signals without operator configuration explicitly permitting this

A receiving node that receives an `insight_shared` or `advisory_candidate_shared` message MUST:
- Treat it as external evidence requiring its own agent review or human review — NOT as a pre-confirmed finding
- Write it to its own `h3_insights` with `outcome_status = 'open'` and `agent_type` identifying the sending node
- Apply all blocked-use constraints from its own domain spec YAMLs, regardless of what the sending node permits
- Require the same human review step as for locally-generated insights before any action is taken

---

## Federation Topology [INFORMATIVE]

The Network layer is agnostic to topology. Common patterns:

| Pattern | Description |
|---------|-------------|
| Bilateral | Two nodes (e.g. city + watershed authority) exchange messages directly |
| Hub-and-spoke | A state-level node receives summaries from multiple city nodes |
| Mesh | Multiple city nodes share event alerts with all peers |
| Public transparency | A node publishes summaries to a public-read endpoint |

No topology is mandated by this specification. The message envelope and delivery receipt contracts are sufficient to support all of the above.

---

## Relationship to Domain Specifications [INFORMATIVE]

The Network specification does not define what data may be shared between nodes — that is governed by:

1. The data classification in the envelope (`public` / `official_sensitive` / …)
2. The receiving node's acceptance policy (which `from_node` identifiers it trusts for which `message_type`)
3. The domain specification's `blocked_uses` (which uses of data are prohibited regardless of how it arrives)

A node that receives an `advisory_candidate_shared` message for an air quality event MUST still apply the air quality domain spec's human review requirement before acting on the advisory.

---

## Network Layer Conformance Gate [NORMATIVE]

A conformant Network layer implementation MUST enforce the following checks on every inbound message before writing any payload to the local Knowledge Store:

| Check | Severity | Description |
|-------|----------|-------------|
| Envelope schema validation | BLOCKING | Message envelope MUST conform to `message_envelope.v1.schema.json`. Malformed envelopes MUST be dropped and logged. |
| Sender trust check | BLOCKING | `from_node` MUST match a counterparty the receiving node has explicitly declared as trusted for the given `message_type`. Untrusted senders MUST be rejected. |
| `message_type` acceptance | BLOCKING | The receiving node MUST declare which `message_type` values it accepts. Messages with an unaccepted type MUST be dropped. |
| Data classification check | BLOCKING | The envelope `data_classification` MUST be within the data sharing agreement between the two nodes. If the classification exceeds what the agreement permits, the message MUST be dropped. |
| Delivery receipt required | NON-BLOCKING | A delivery receipt MUST be returned to the sender for every accepted message. Failure to send the receipt is logged but does not reject the message. |

A Network layer implementation that does not enforce the BLOCKING checks above MUST NOT be used in a production deployment. The absence of `ROUTING.md` and `AUTH.md` means additional conformance requirements for routing and authentication are pending — implementations SHOULD be conservative (deny-by-default) until those documents are published.
