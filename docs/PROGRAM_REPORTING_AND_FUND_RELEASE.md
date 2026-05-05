# Program reporting and fund-release review (design)

## 1) Purpose

This document designs a **Program Reporting and Fund-Release Review** capability for AirOS: **state-to-city** (or state-to-agency) **programmatic progress** reporting and **evidence-backed** submissions that support **comparable, auditable** review for **fund release**—without replacing cities’ internal systems and **without** automating finance or legal outcomes.

**Scope:** design and documentation, plus a **minimal Phase 1 fixture demo** (review packet builder + example deployment run) described under *Phase 1 fixture demo implementation* below. Broader product features remain future work; implementation must follow the repo’s **specs-first** rules when expanding beyond this demo.

### Phase 1 in this repository (intentional narrow scope)

The **first Program Reporting demo** in `specifications/` is deliberately minimal: **program progress** and **financial utilization** aggregates in a single **`city_program_submission`** consumer payload per period, and a state **`fund_release_review_packet`** that signals **review_ready**, **clarification_required**, **human_review_required**, or **rejected**—plus **fund_release_review_status** for authorized human review. **No automatic fund release** and no enforcement automation.

**Explicitly deferred to later phases:** separate **provider** feeds (per-project progress, line-item expenditure, field inspection, geo-tagged assets, utilization certificates as structured inputs), **photographic / field / geo evidence** as required contract data, **deficiency_memo** and **program_progress_dashboard** consumer contracts, and detailed deficiency workflows. Those capabilities remain valid **design directions** below; they are **not** Phase 1 conformance artifacts.

#### Phase 1 reference data (catalogs)

- The **state** (publisher) maintains **shared reference catalogs** so cities and the state program office use the same **codes** for administrative units, programs, and reporting periods. The canonical shape is **`platform_objects/reference_catalog.v1.schema.json`** (manifest: `platform_reference_catalog`).
- **Demo fixtures** live under `specifications/examples/reference_data/` (`administrative_units`, `program_catalog`, `reporting_periods`) and are registered for **conformance example validation only**.
- Each **`city_program_submission`** and **`fund_release_review_packet`** carries **`reference_data_versions`** (e.g. `v1` per catalog family) so reviewers know which catalog revision the payload assumed.
- The **program spec** lists **`required_reference_catalogs`** and states that **`city_id`**, **`program_id`**, and **`reporting_period`** on submissions should match **`code`** values from the administrative-units, program, and reporting-period catalogs respectively.
- **Distribution, pull/cache, TTL, and cryptographic signing** of catalogs are **out of scope** for this specs step; they remain **future implementation** work.

#### Phase 1 fixture demo implementation

- **City submission sample:** `specifications/examples/program_reporting/city_program_submission.sample.json` (synthetic).
- **Second city submission:** `specifications/examples/program_reporting/city_program_submission_city_b.sample.json` (synthetic; intentionally triggers multiple flags).
- **Review packet builder:** `urban_platform.applications.program_reporting.review_packets.build_fund_release_review_packet` reads a submission-shaped `dict` and emits a **`fund_release_review_packet`**-shaped `dict` with deterministic flags (`progress_delay` if `overall_progress_pct < 50`, `low_fund_utilization` if `utilization_pct < 50`, `financial_inconsistency` if `amount_spent > amount_released`), fixed **`blocked_uses`**, and role-based **`required_human_approvals`**. **No automatic fund release** or finance integration.
- **State summary builder:** `urban_platform.applications.program_reporting.review_packets.build_program_reporting_state_summary` aggregates multiple review packets into a small multi-city monitoring payload (demo-only; no schema yet). It includes:
  - **Financial totals** (approved/released/spent + overall utilization)
  - **City financial rows** and **city progress rows** for state-level review
  - **Action items** for state reviewers (queue for authorized review vs request clarification) — **no** automatic disbursement or enforcement actions
- **Deployment example:** `deployments/examples/program_reporting_state_demo/` — after `deployment validate`, run `python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo` to write:
  - `fund_release_review_packets.json` (two cities, schema-validated)
  - `state_program_summary.json` (multi-city monitoring summary)
  - `deployment_run_summary.json` (counts + warnings)
- **Review dashboard tab:** default **file mode** reads deployment JSON under `data/outputs/deployments/program_reporting_state_demo/`; run `streamlit run review_dashboard/app.py` and open the **Program Reporting** tab (presentation-only). **Optional API mode** (`AIROS_DASHBOARD_DATA_MODE=api` + running Core API) reads the same shapes from generic `GET /outputs` instead—see [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md).
- **Future:** catalog pull/cache, dashboards, signed envelopes / network submission flows, and evidence-heavy workflows.

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
- **State AirOS** **validates** submissions (schema, manifest keys, completeness; **Phase 1:** no separate evidence-linkage requirement), queues them for **human review**, and emits **fund-release review packets**. **Deficiency memos** and multi-feed validation are **later** when those consumer/provider contracts exist.  
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
│  • Fund-release review packet (Phase 1)                          │
│  • Deficiency memo (deferred)                                     │
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
| `consumer_contracts/` | **Outputs** cities produce (e.g. `city_program_submission`) and state produces (e.g. `fund_release_review_packet`). Phase 1 stops there; deficiency memos and dashboard payloads are **future** consumer contracts when specified. |
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

**Phase 1 (fixtures today):** the city produces one **`city_program_submission`** per reporting period with **aggregated** `program_progress` and `financial_progress`, **role** (`reporting_officer_role`, not personal names), **warnings**, **blocked_uses**, and **`human_review_required`** (Phase 1 contract requires human review path).

**Later phases (design):** local MIS, finance exports, inspection apps, and GIS may map to **provider contracts**; evidence linking and richer completeness scores then apply. That **multi-feed, evidence-backed** path is **not** required for Phase 1 schemas in `specifications/`.

1. **Local context (future)** — project MIS, finance summaries, inspections, GIS (authorized and scoped).  
2. **Provider contracts (future)** — normalize to platform objects where adopted.  
3. **Evidence mapping (future)** — photos, PDFs, geo-tags with provenance.  
4. **Officer / role attestation** — designated **role** and policy inside the ULB; Phase 1 carries **role** only on the submission.  
5. **`city_program_submission` packet** — Phase 1: single consumer-shaped payload per period (`city_program_submission.v1`).  
6. **Transmission (future)** — envelope / API / SFTP / email—transport only; validation at state on receipt.

---

## 8) State review workflow

**Phase 1:** validate the submission against the consumer schema; apply **program_spec** `review_rules` only as **demo flags** (e.g. progress_delay, low_fund_utilization, financial_inconsistency); emit **`fund_release_review_packet`** with **review_status**, **fund_release_review_status**, assessments, **flags**, **required_human_approvals**, **confidence**, **blocked_uses**, and **review_notes**. **No** automated fund release.

**Future:** completeness against multiple provider feeds, evidence linkage checks, deficiency memos, and leadership dashboards—each as **additional** contracts when specified.

1. **Validation** — schema + manifest + declared `program_spec_version`.  
2. **Completeness (Phase 1)** — required sections `program_progress` and `financial_progress` on the submission object.  
3. **Evidence checks** — **deferred** (not part of Phase 1 required inputs).  
4. **Review queue** — humans consume structured **review packets**.  
5. **Deficiency memo** — **deferred** consumer contract.  
6. **Fund-release review packet** — `fund_release_review_packet.v1` (Phase 1 fields only).  
7. **Authorized human approval** — finance / program authority remains **outside** automated AirOS disbursement.

---

## 9) Contracts and fixtures (Phase 1 demo pack in repo)

The **Stormwater Resilience Grant 2026** Phase 1 pack under `specifications/` includes **domain spec**, **registry schema**, **program bundle YAML**, **two consumer schemas**, one **reference catalog** platform schema, **six** registered JSON examples under program reporting + reference data, plus a **fixture review-packet builder** and **deployment demo run** (no city ingestion network, no catalog pull/cache, no automated fund release). Manifest keys:

**Domain**

- `specifications/domain_specs/program_reporting.v1.yaml`

**Registry**

- `specifications/registry_contracts/program_spec_registry.v1.schema.json` → manifest: `registry_program_spec_registry_v1`

**Program bundle**

- `specifications/program_specs/stormwater_resilience_grant_2026/program_spec.yaml` (includes `required_reference_catalogs`)

**Platform object — reference catalog**

- `specifications/platform_objects/reference_catalog.v1.schema.json` → `platform_reference_catalog`

**Consumer contracts** (`specifications/consumer_contracts/`)

- `city_program_submission.v1.schema.json` → `consumer_city_program_submission`  
- `fund_release_review_packet.v1.schema.json` → `consumer_fund_release_review_packet`  

**Examples** (`specifications/examples/program_reporting/`)

- `city_program_submission.sample.json` → `example_program_reporting_city_program_submission`  
- `fund_release_review_packet.sample.json` → `example_program_reporting_fund_release_review_packet`  
- `program_spec_registry.sample.json` → `example_program_reporting_program_spec_registry`  

**Examples** (`specifications/examples/reference_data/`)

- `administrative_units.sample.json` → `example_reference_data_administrative_units`  
- `program_catalog.sample.json` → `example_reference_data_program_catalog`  
- `reporting_periods.sample.json` → `example_reference_data_reporting_periods`  

**Deferred (not in Phase 1 manifest):** separate program-reporting **provider** schemas (project progress feed, expenditure feed, field evidence, geo-tagged progress), `deficiency_memo`, `program_progress_dashboard`, and their samples—**future phases** when provider contracts and consumer surfaces are specified again.

**Network**

- Reuse **`network_message_envelope_v1`** and **`network_delivery_receipt_v1`** for future submission transport—**no** fund semantics in envelopes.

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

## 12) Demo scenario (fixtures in repo; processing still future)

**Program:** Stormwater Resilience Grant 2026  

**Actors:** State Urban Department (publisher / reviewer); City ULB program cell (**synthetic** `city_demo_a`, roles not names).  

**Inputs (Phase 1 fixtures):** a single **`city_program_submission`** with aggregated progress and financial placeholders (no bank accounts, vendors, or real locations).  

**Outputs:** state **`fund_release_review_packet`** with `review_status` / `fund_release_review_status`, rule-driven **flags** (e.g. progress_delay in the sample), **blocked_uses** mirroring submission, and **required_human_approvals**.  

**Deferred demo paths:** separate provider fixtures, deficiency memo, and dashboard—**future** once those contracts return to the manifest.  

**Invariant:** **No fund release automated** in any path.

---

## 13) Relationship to existing AirOS architecture

| Existing concept | Role in program reporting |
|------------------|---------------------------|
| **Provider registry** | Maps city local feeds to program-required **provider contracts**. |
| **Application registry** | Selects builders that emit **city_program_submission** and state **fund_release_review_packet** (Phase 1); further consumers when specified. |
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
| **1a (repo)** | **Phase 1 contracts:** domain spec + registry + program bundle + **two** consumer schemas + **three** examples + manifest (progress + financial monitoring only; **no** evidence provider feeds). |
| **1b (design)** | This **design doc** + alignment with domain/playbook docs for **full** evidence-backed trajectory. |
| **2** | **Fixture-based builders** (submission + review packet) with conformance; optional **provider** feeds and deficiency/dashboard **when re-specified**. |
| **3** | **Deployment demo** + validator + optional runner allowlist. |
| **4** | **CLI** `program list` / `pull` / `enable` **or** documented import scripts—only after contracts exist. |
| **5** | **Network submission** path (envelope + receipt + policy) with agency authorization. |

Each phase should end with **`python main.py --step conformance`** and supervisor evidence per `AGENTS.md`.

---

## 15) Agency pitch (one paragraph)

**“The state defines the reporting contract once. Every city can pull it, validate against it, and submit structured progress and utilization for review. The state gets comparable, auditable inputs for fund-release **review** without forcing every city to use the same internal system—and fund release stays where it belongs: with authorized people and finance processes.”** (Richer evidence-backed reporting is an explicit later phase.)

---

## Honesty checklist

- **Phase 1 repo contracts** in §9 are **present** for conformance and demos; a **fixture review-packet builder** and **`deployment run`** for `program_reporting_state_demo` exist (see §1 fixture demo); generic **`program list` / `pull` / `enable`** samples in §6 remain **future** unless implemented elsewhere.  
- **Fund release** is **never** automated by this design.  
- **Evidence-heavy provider feeds and deficiency/dashboard contracts** are **deferred**—see §1 Phase 1 note and §9.  
- **Public repositories** must use **fixtures and synthetic examples** only for demos; real utilization data belongs in **private deployment** workspaces per existing deployment guidance.
