# Agency node model (AirOS)

An **AirOS Node** is the **unit of deployment and trust** for AirOS Core: typically one **agency** (or tightly governed consortium) operating a bounded instance with **clear data ownership** and **decision authority**. This model supports **standalone** cities, **multi-agency** metros, **multi-city** state bodies, and **federated** networks—without assuming a single monolithic city stack.

For how nodes **interoperate**, see [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md). For deployment topologies, see [`docs/FEDERATED_DEPLOYMENT_ARCHITECTURE.md`](FEDERATED_DEPLOYMENT_ARCHITECTURE.md).

---

## Why a node model

- **Agencies are fragmented** in Indian urban governance; they often run **different** systems, budgets, and legal bases.  
- **Jurisdiction** frequently spans “city” (state boards, utilities, regional bodies).  
- **Federation** should add **coordination**, not a **shared domain brain** that overrides local authority.  

The node model makes **who owns what** explicit before any cross-agency traffic is designed.

---

## Recommended profile fields (planning / future spec alignment)

These fields guide **forward deployment** documentation and future **`agency_node.v1`-class** specifications. They are **not** yet mandatory repo artifacts.

| Field | Description |
|--------|-------------|
| **`node_id`** | Stable identifier for this deployment (e.g. `ulb-metro-east-01`). |
| **`agency_id`** | Stable identifier for the legal/operational agency (may map to external registries later). |
| **`agency_name`** | Human-readable name. |
| **`agency_type`** | E.g. ULB, utility, pollution control board, traffic police, development authority, state department, disaster cell, health department. |
| **`jurisdiction_type`** | `city` \| `multi_city` \| `district` \| `regional` \| `state` \| `national` (or documented extensions). |
| **`jurisdiction_areas`** | References to boundaries or registries (IDs, not raw sensitive geometry in public repos). |
| **`enabled_domains`** | Which **domain specs** this node activates (e.g. `air_quality`, `flood_risk`). |
| **`provider_contracts_supported`** | Which feeds this node **ingests** or **could** ingest (contract IDs / manifest entries). |
| **`consumer_contracts_supported`** | Which payloads it **emits** or **consumes** (dashboard, decision packet, field task, transparency feed). |
| **`endpoints_exposed`** | Logical surfaces (API, file drop, email gateway, event subscription)—**policy-bound**, not ad-hoc URLs in code. |
| **`events_or_messages_consumed`** | Cross-agency message types or topics the node **subscribes** to (envelope-level). |
| **`data_sharing_policy`** | What may leave the node, under which classification and agreements (high level in profile; detail in future `data_sharing_policy` spec). |
| **`authorization_model`** | Who may issue/receive messages (roles, PKI, MoU phase, etc.)—operational, not domain logic. |
| **`operational_owner`** | Named role/team accountable for the node (not personal PII in public repos). |
| **`deployment_mode`** | `standalone` \| `shared_hosted` \| `managed_service` \| `federated` (or combined). |
| **`maturity_level`** | Planning label (e.g. pilot, operational, read-only observability)—aligned with local governance, not a global score. |

---

## Node boundaries (normative intent)

- A node **owns** its ingested data, derived features, and **agency decisions** derived from them.  
- A node **does not** silently merge another agency’s restricted holdings without **explicit** sharing policy and contracts.  
- **Consumer contracts** define what **may** cross a boundary; the **Network Layer** enforces **envelope-level** policy—not domain conclusions.  

---

## Multiple nodes in one municipality

Two common arrangements:

1. **Logical partition** — one hosting footprint, strict **logical** isolation per agency (separate schemas, keys, policies).  
2. **Physical partition** — separate deployments per agency vendor or security zone.  

Both are compatible with Core; **Network Layer** adoption is orthogonal until **interop** is required.

---

## From node profile to implementation

Profiles inform **prioritization** and **MoU sequencing** only. Executable work stays **specs-first**:

1. Domain and consumer contracts relevant to this node  
2. Conformance + tests  
3. Connectors authorized for this jurisdiction  
4. Optional **cross-node** envelopes when the coordination layer is deployed  

Agents should avoid **hard-coding** agency IDs or jurisdictional quirks in shared code—use deployment configuration and specs (`AGENTS.md`, `docs/CITY_PROFILE_TEMPLATE.md`).

