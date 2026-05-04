# Program reporting and fund-release review (design)

## 1) Purpose

This document designs a **Program Reporting and Fund-Release Review** capability for AirOS: **state-to-city** (or state-to-agency) **programmatic progress** reporting and **evidence-backed** submissions that support **comparable, auditable** review for **fund release**—without replacing cities’ internal systems and **without** automating finance or legal outcomes.

**Scope:** design and documentation only. **No schemas, code, or CLI commands described here are implemented** unless already present elsewhere in the repository under other names. Implementation must follow the repo’s **specs-first** rules when work begins.

---

## 2) Governance problem

A recurring pattern in urban and sectoral programs:

- **State schemes and grants** require cities (ULBs, parastatals, implementing agencies) to submit **progress and utilization** evidence on a schedule.  
- Submissions are often **Excel, PDF, email, or portal uploads** assembled manually; **evidence** sits in **works management**, **finance**, **field inspection**, **GIS**, **photos**, and **certificates**—each a different system or spreadsheet.  
- **State review** is **slow and inconsistent**: reviewers lack a single schema for “complete enough,” comparability across cities is weak, and audit trails are fragmented.  
- **Cities** face **reporting burden**, rework, and **back-and-forth** when requirements change or are interpreted differently.  
- **Staff transfers** erode **institutional memory**; the same questions recur each cycle.

AirOS does not solve organizational politics, but it can offer a **shared reporting contract**, **validation**, and **review packets** that reduce ambiguity and improve auditability—if adopted through specs, registries, and human-gated processes.

---

## 3) Core AirOS approach

- **State AirOS** (or a state-designated authority node) **publishes** a **program reporting specification** bundle: what must be reported, in what shape, with what evidence, and under what review rules.  
- **City AirOS** instances **import or adopt** that specification into a **deployment-scoped** workspace (registries + deployment profile).  
- Cities **map local data sources** to **provider contracts** that normalize into **platform objects** and program-specific **evidence** requirements.  
- Cities **generate** **city program submission packets** (consumer-contract-shaped payloads) for each reporting period.  
- **State AirOS** **validates** submissions (schema, manifest keys, completeness, evidence linkage), queues them for **human review**, and emits **fund-release review packets** and **deficiency memos** where gaps exist.  
- **Actual fund release** remains an **authorized human / government finance** process; AirOS supplies **review support**, not disbursement automation.

Framing for agencies: **one reporting contract, many local backends**—comparability and audit without a single monolithic city ERP.

---

## 4) Architecture

High-level flow (logical; physical deployment may be Level 1 or Level 2 multi-container later).

```
┌─────────────────────────────────────────────────────────────────┐
│ State AirOS                                                      │
│  • Program Specification Registry                                │
│  • Program specs, reporting contracts, evidence requirements     │
│  • Fund-release review rules (review prompts, completeness gates) │
└────────────────────────────┬────────────────────────────────────┘
                             │ publish / distribute bundle
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ City AirOS                                                       │
│  • Local deployment workspace                                    │
│  • Provider mappings (local feeds → provider contracts)          │
│  • Local evidence (files, APIs, GIS, inspections—authorized)    │
│  • City program submission packet (consumer contract)           │
└────────────────────────────┬────────────────────────────────────┘
                             │ submit (future: envelope / API / SFTP / email)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ State AirOS                                                      │
│  • Submission validation                                        │
│  • Review dashboard / queue                                      │
│  • Fund-release review packet                                    │
│  • Deficiency memo                                                │
│  • (Human + finance authority → actual release)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Separation of concerns:** network transports move **envelopes and receipts** (see existing network-contract posture in [`docs/CROSS_AGENCY_COORDINATION_LAYER.md`](CROSS_AGENCY_COORDINATION_LAYER.md)); **program meaning** stays in **domain specs**, **provider/consumer contracts**, and **application** builders—not in the transport plane.

---

## 5) Program specification bundle

A **program specification bundle** is a versioned, portable set of artifacts the state publishes. Conceptual layout (names illustrative until specs exist):

| Path | Role |
|------|------|
| `program_spec.yaml` | **Identity and lifecycle:** `program_id`, `version`, effective dates, status, title, owning jurisdiction, required provider roles, required outputs, references to contract files. |
| `provider_contracts/` | **Inputs cities must be able to supply** (e.g. project progress, expenditure statements, field evidence)—each a provider contract artifact key + JSON Schema (or agreed schema mechanism). |
| `consumer_contracts/` | **Outputs** cities produce (e.g. `city_program_submission`) and state produces (e.g. `fund_release_review_packet`, `deficiency_memo`, dashboard payloads). |
| `rules/` | **Completeness and review rules** machine-readable or referenced (thresholds, required evidence types, cross-field checks)—must remain aligned with domain spec safety language. |
| `examples/` | **Fixture JSON** for demos, conformance, and onboarding—no real city financial or PII data in public repos. |
| `metadata/` | **Provenance:** checksums, signing hooks (future), publication notes, contact for program office (non-secret). |

Bundles are **not** a substitute for law, finance policy, or GFR/CAG compliance; they are the **technical contract** layer AirOS can enforce through **conformance** and **validation**.

---

## 6) Discovery and adoption workflow

**Phase A — Manual import (first realistic phase)**  
State publishes a bundle (portal, secure file share, or git submodule in a **private** deployment repo). City operators **copy** artifacts into `deployments/...` and register them in **provider_registry** / **application_registry** per [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md).

**Phase B — State catalog (intermediate)**  
State exposes a **read-only catalog** (HTTPS index or signed manifest) listing `program_id`, versions, hashes, and download URLs. City AirOS **imports** by URL with audit metadata stored in deployment profiles.

**Phase C — Network pull (later; requires network contracts + governance)**  
City node pulls program artifacts over an agreed transport with **message envelopes** and **delivery receipts**—still **no** program semantics in the network layer.

**Illustrative future CLI (not implemented):**

```text
airos program list --from <state-airos-url>
airos program pull stormwater_resilience_grant_2026 --version v1
airos program enable stormwater_resilience_grant_2026 --deployment <city-deployment>
```

These are **placeholders for product/CLI design**; today, use **manual file placement** + **`deployment validate`** / **`deployment run`** only where a demo exists.

---

## 7) City submission workflow

1. **Local data sources** — project MIS, finance vouchers summaries, inspection apps, GIS layers, document stores (each authorized and scoped).  
2. **Provider contracts** — each source maps to an allowed **provider contract**; ingestion **normalizes** to canonical **Observations / Events / Assets / Entities** as appropriate.  
3. **Evidence mapping** — photos, PDFs, geo-tags linked with **provenance** (who, when, method—not anonymous scrapes).  
4. **Officer certification** — designated role attests submission completeness **within city policy** (human step; may be recorded as structured fields in the submission packet metadata).  
5. **`city_program_submission` packet** — single consumer-shaped payload (or bounded set) per period, conforming to `city_program_submission.v1` when specified.  
6. **Transmission (future)** — submission travels via **AirOS message envelope** (reuse `network_message_envelope` concepts), **API**, **SFTP**, or **email adapter**—transport only; validation on receipt at state.

---

## 8) State review workflow

1. **Validation** — schema + manifest registration + cross-reference to program bundle version city declared.  
2. **Completeness checks** — required sections, required evidence types, date ranges, project IDs.  
3. **Evidence checks** — linkage integrity, allowed file types, duplicate detection flags (non-punitive).  
4. **Review queue** — human reviewers see structured **review packets**, not raw dumps only.  
5. **Deficiency memo** — consumer contract `deficiency_memo.v1` when gaps exist; cites **specific** missing or inconsistent items.  
6. **Fund-release review packet** — `fund_release_review_packet.v1`: recommendation language, risk flags, **blocked uses** reminders, **no auto-release** statement.  
7. **Authorized human approval** — finance / program authority acts **outside** AirOS or via integrated finance systems per government rules.

---

## 9) Contracts likely needed (future specs)

All paths below are **proposed**; they must be added under `specifications/` with manifest registration and conformance **before** any implementation ships.

**Domain**

- `specifications/domain_specs/program_reporting.v1.yaml` — variables, evidence types, review prompts, **safety gates**, **blocked uses**, human-review requirements.

**Registry**

- `specifications/registry_contracts/program_spec_registry.v1.schema.json` — optional: how state lists and versions program bundles.

**Provider contracts (illustrative filenames)**

- `city_project_progress_feed.v1.schema.json`  
- `city_expenditure_statement_feed.v1.schema.json`  
- `city_field_evidence_feed.v1.schema.json`  
- `geo_tagged_asset_progress_feed.v1.schema.json`  

**Consumer contracts**

- `city_program_submission.v1.schema.json`  
- `fund_release_review_packet.v1.schema.json`  
- `deficiency_memo.v1.schema.json`  
- `program_progress_dashboard.v1.schema.json`  

**Network**

- Reuse **`network_message_envelope`** and **`network_delivery_receipt`** (or current v1 equivalents in `specifications/network_contracts/`) for submission transport—**no** fund semantics in envelopes.

---

## 10) Versioning and change governance

Program bundles must carry:

- **`program_id`** — stable identifier (e.g. `stormwater_resilience_grant_2026`).  
- **`version`** — semver or dated version (`v1`, `2026.04`).  
- **`effective_from` / `effective_until`** — reporting windows.  
- **`status`** — `draft` | `published` | `deprecated`.  

**Breaking changes** require a **new version**; cities **adopt** versions **explicitly** in deployment profile (no silent upgrades). **Notice periods** and parallel acceptance windows are organizational policy; AirOS can surface **version mismatch** warnings at validation time.

---

## 11) Safety and blocked uses

Program reporting and fund-release **review** must inherit AirOS safety posture:

- **No automatic fund release** — disbursement is always **human/finance-authoritative**.  
- **No automatic penalty, recovery, or enforcement** from AirOS outputs alone.  
- **No blacklisting** of contractors, cities, or officers based solely on model or aggregation output.  
- **No public release** of sensitive financial detail, contractor bids, or restricted personal data **without explicit authorization** and consumer-contract scope.  
- **Human review required** for any output that could influence funding decisions or reputational harm.  
- **Finance department process** and **delegated financial powers** remain **authoritative**; AirOS is **decision-support and audit structure**, not a ledger of record.

These belong in **`program_reporting.v1.yaml`** under blocked uses and in consumer contracts’ review metadata.

---

## 12) Demo scenario (first demo — design only)

**Program:** Stormwater Resilience Grant 2026  

**Actors:**  
- State Urban Department (publisher / reviewer)  
- City A ULB (stronger evidence maturity)  
- City B ULB (gaps for deficiency path)  

**Inputs (fixtures only in public repo):**  
- Project progress fixture  
- Expenditure statement fixture  
- Field inspection evidence fixture  
- Geo-tagged asset evidence fixture  

**Outputs:**  
- City A: **`city_program_submission`** → state **`fund_release_review_packet`** marked **review-ready** (still human-approved for release).  
- City B: **`city_program_submission`** incomplete → state **`deficiency_memo`** listing missing evidence / inconsistencies.  
- State: **`program_progress_dashboard`** aggregate payload for leadership (non-enforcement, non-punitive framing).  

**Demo behavior:**  
- One city **sufficient evidence** → review packet ready for human sign-off.  
- One city **missing evidence** → deficiency memo.  
- **No fund release automated** in any path.

---

## 13) Relationship to existing AirOS architecture

| Existing concept | Role in program reporting |
|------------------|---------------------------|
| **Provider registry** | Maps city local feeds to program-required **provider contracts**. |
| **Application registry** | Selects builders that emit **city_program_submission**, state **review packet** / **deficiency memo** / **dashboard** consumers. |
| **Deployment profile** | Binds `program_id` + **adopted version**, enabled domains, paths to registries, environment. |
| **Agency node profile** | City vs state **node identity** and jurisdiction context for federation-aware deployments. |
| **Network contracts** | Future submission transport via **envelopes + receipts** only. |
| **Conformance** | Gates every schema/manifest/example before trust. |
| **AI supervisor** | CI-style hygiene across specs and examples when extended for program artifacts. |
| **Docker / CLI** | Same **doctor → validate → run** posture for demos once program demo exists; no change implied by this design doc alone. |

See also [`specifications/ARCHITECTURE_NOTE.md`](../specifications/ARCHITECTURE_NOTE.md) and [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md).

---

## 14) Implementation roadmap (bounded phases)

| Phase | Deliverable |
|-------|----------------|
| **1** | This **design doc** + alignment with domain/playbook docs. |
| **2** | **Domain spec** + **registry/consumer/provider** schemas + **examples** + manifest registration. |
| **3** | **Fixture-based builders** (city submission + state review packet + deficiency memo) with conformance. |
| **4** | **Deployment demo** (e.g. `deployments/examples/program_reporting_demo`) + validator + optional runner allowlist. |
| **5** | **CLI** `program list` / `pull` / `enable` **or** documented import scripts—only after contracts exist. |
| **6** | **Network submission** path (envelope + receipt + policy) with agency authorization. |

Each phase should end with **`python main.py --step conformance`** and supervisor evidence per `AGENTS.md`.

---

## 15) Agency pitch (one paragraph)

**“The state defines the reporting contract once. Every city can pull it, validate against it, and submit evidence-backed progress packets. The state gets comparable, auditable, review-ready data for fund release without forcing every city to use the same internal system—and fund release stays where it belongs: with authorized people and finance processes.”**

---

## Honesty checklist

- **Schemas and CLI** in §6 and §9 are **future** unless separately implemented.  
- **Fund release** is **never** automated by this design.  
- **Public repositories** must use **fixtures and synthetic examples** only for demos; real utilization data belongs in **private deployment** workspaces per existing deployment guidance.
