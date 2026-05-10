# AirOS Network — Specification Index

The Network component enables two or more AirOS nodes to share observations, insights, and advisory candidates across jurisdictional boundaries. It is optional — a single-node deployment operates fully without it.

| Document | What it specifies |
|----------|------------------|
| [NODE_MODEL.md](NODE_MODEL.md) | Node identity, message envelope (prose spec), message types, delivery receipt, federation topology, data ownership |

**JSON Schemas (normative):**

| Schema | Location | What it validates |
|--------|----------|------------------|
| Message envelope | [`../../specifications/network_contracts/message_envelope.v1.schema.json`](../../specifications/network_contracts/message_envelope.v1.schema.json) | All inter-node message wrappers |
| Delivery receipt | [`../../specifications/network_contracts/delivery_receipt.v1.schema.json`](../../specifications/network_contracts/delivery_receipt.v1.schema.json) | Acknowledgement messages |

**Planned (not yet written):**
- `ROUTING.md` — how the Network layer decides which node receives which message; policy evaluation; multicast rules
- `AUTH.md` — authentication and authorisation between nodes; credential bundle format; policy bundle format

> **⚠ Network spec is partial.** Until `ROUTING.md` and `AUTH.md` are published, no conformance claim can be made for the Network component. Single-node deployments are fully specifiable from the Core, Drivers, and Apps sections alone. Multi-node deployments MUST NOT be considered conformant under this spec version until the routing and auth contracts are published.
