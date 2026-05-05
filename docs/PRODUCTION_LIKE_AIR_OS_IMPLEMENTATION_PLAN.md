# Production-like AirOS — phased implementation plan

**Audience:** technical leads sequencing platform work.  
**Scope:** planning only. This document does not change code or runtime behavior.

**Related reading:** [`docs/INTEROPERABILITY_MODEL.md`](INTEROPERABILITY_MODEL.md), [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md), [`docs/PLUGIN_AND_REGISTRY_ARCHITECTURE.md`](PLUGIN_AND_REGISTRY_ARCHITECTURE.md), [`docs/CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md`](CONTAINERIZED_DEPLOYMENT_ARCHITECTURE.md), [`docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md`](PROGRAM_REPORTING_AND_FUND_RELEASE.md), [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md).

---

## 1) Current state summary

AirOS today is **specs-first** and **demo- and validation-oriented**. It is suitable for **governed development**, **conformance-gated releases**, and **fixture-based agency demos**—not as a full production municipal operations platform without substantial additional work.

**How it works today (high level):**

- **Contracts and manifest:** JSON Schemas and YAML specs live under `specifications/` (`provider_contracts`, `consumer_contracts`, `platform_objects`, `domain_specs`, `network_contracts`, `registry_contracts`). [`specifications/manifest.json`](../specifications/manifest.json) registers schemas and examples for conformance.
- **Conformance:** `python main.py --step conformance` validates artifacts against the manifest; CI and the AI supervisor can run the same checks.
- **Deployment examples:** `deployments/examples/*` provide declarative `deployment_profile.yaml` + `provider_registry.yaml` + `application_registry.yaml` (e.g. [`flood_local_demo`](../deployments/examples/flood_local_demo/), [`program_reporting_state_demo`](../deployments/examples/program_reporting_state_demo/)).
- **Deployment validation (read-only):** [`tools/deployment_runner/validate_deployment.py`](../tools/deployment_runner/validate_deployment.py) checks files, manifest references, and basic safety (no secrets in YAML).
- **Deployment runner (POC):** [`tools/deployment_runner/run_deployment.py`](../tools/deployment_runner/run_deployment.py) is **allowlisted**: it reads **fixture JSON** from paths in registries, runs **hard-coded or allowlisted** Python callables (e.g. flood ingest + feature build + application builders; program reporting fixture submissions → review packets). It writes **JSON** under `data/outputs/deployments/<deployment_id>/`. The runner can **optionally** also write a **JSONL** pilot store (`records.jsonl`, `outputs.jsonl`, `audit_events.jsonl`) when invoked with `--store-dir <path>` (or via `python tools/airos_cli.py deployment run … --store-dir …`); **`data/outputs/` remains the default demo output path** and is unchanged when `--store-dir` is omitted.
- **Shared deployment YAML parsing:** [`urban_platform/deployments/config_loader.py`](../urban_platform/deployments/config_loader.py) centralizes parsing of deployment YAML into a **`DeploymentConfig`** (used by validation, runner, and the supervisor’s [`deployment_probe`](../tools/ai_dev_supervisor/deployment_probe.py)). It does **not** import connectors or execute builders.
- **Supervisor:** [`tools/ai_dev_supervisor/`](../tools/ai_dev_supervisor/) probes repo health, registry alignment, and deployment examples (read-only).
- **CLI:** [`tools/airos_cli.py`](../tools/airos_cli.py) wraps doctor, conformance, deployment validate/run (subprocess to runner), review, and **examples list/describe** (read-only scan).
- **Core API (pilot-runtime):** optional local FastAPI app under [`urban_platform/api/`](../urban_platform/api/) for the **Program Reporting** path (ingest → store → run builders → read outputs/audit). See [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md). Not production-secured; does not replace deployment JSON outputs or conformance.
- **Dashboard:** [`review_dashboard/`](../review_dashboard/) (Streamlit) **reads generated files** from `data/outputs/...` for several tabs; it is **presentation-first** and must not own domain rules.
- **Docker (Level 1):** Single image; doctor/conformance/deployment demos per [`docs/DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md).
- **Docker Compose (Level 2 POC):** [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md) — minimal multi-container topology (packaging/orchestration slice), **not** production guidance.
- **Pilot storage building block:** `urban_platform/storage/file_store.py` provides a **file-backed JSONL store** for ingested records, generated outputs, and audit events. This is additive scaffolding for future APIs/audit; demos still write primary outputs under `data/outputs/`.

**Explicit non-production areas today:**

- No durable **multi-user service** model for ingestion and review (no production API surface for all flows).
- No **authoritative persistent store** for all ingested payloads and outputs (files under `data/` are workspace artifacts).
- **Allowlisted** execution only; **no** safe arbitrary “registry-driven plugin” runtime.
- **Security/trust** (authN/Z, signed envelopes, participant directory, catalog pull/cache) is **documented as future**, not implemented as a productized subsystem.
- **Program reporting** Phase 1 is **review support**; **no** fund release, finance integration, or enforcement automation.

---

## 2) Target production-like architecture

**Intent:** move from “run fixtures locally and inspect JSON files” to “ingest validated data into a core service, persist it, run registered builders, expose outputs and audit through APIs—while keeping specs-first contracts and human-gated review posture.”

**Components (target):**

| Layer | Role |
|-------|------|
| **Provider/adapters** | Push or sync data using **provider contracts**; may be separate processes or scheduled jobs. |
| **AirOS Core service** | Validates against contracts, assigns IDs/receipts, writes to store, emits audit events, orchestrates **allowlisted** application runs. |
| **Persistent store** | Durable records: raw ingested payloads, normalized/platform objects (as adopted), generated outputs, deployment snapshots, audit log. |
| **Application services / builders** | Consume stored, validated inputs; emit **consumer contract** outputs (review packets, dashboard payloads). |
| **Output API + dashboard** | Role-aware read paths; dashboard uses **API mode** in production-like deployments; **file mode** remains for demos. |
| **Audit log** | Append-only (conceptually) record of ingest, validation, runs, outputs, conformance/deployment validation, future user actions. |
| **Optional network adapter services** | Envelope transport per **network contracts**; **policy plane**, not domain semantics. |
| **Future federation** | Cross-agency exchange via agreed contracts + governance (out of scope for early phases). |

**Text diagram:**

```
Provider (API / file / sync / event)
        │
        ▼
AirOS Core — ingestion API
        │  contract validation (provider contracts → platform objects path)
        ▼
Persistent store (records + lineage)
        │
        ▼
Application execution — allowlisted builders (consumer contracts)
        │  schema validation on outputs
        ▼
Review-ready outputs (packets, summaries, tasks)
        │
        ├──► Dashboard / Output API  ──►  role-based consumers
        │
        └──► Audit log (all steps above + governance events)
```

---

## 3) Key architectural shift

| Today (demo path) | Target (production-like path) |
|-------------------|-------------------------------|
| Fixture file on disk | Validated **ingestion** (API/sync) with **receipt** |
| Allowlisted runner **directly** calls builders | Core **stores** input, **schedules/executes** builder with context |
| JSON written to `data/outputs` as primary artifact | **Store** is source of truth; files may be **export** or **cache** |
| Dashboard reads **files** | Dashboard/API reads **stored outputs** (with **file fallback** for dev/demo) |
| Conformance is repo CI gate | Conformance **plus** runtime validation receipts + **audit** |

The **specs-first** model (contracts, manifest, domain specs, blocked uses) remains; only **execution and persistence** mature.

---

## 4) Production-like capability areas

### A. Shared DeploymentConfig loader

**Status in repo:** **`urban_platform/deployments/config_loader.py`** exists; **`load_deployment_config()`** is used by deployment validation, deployment runner, and deployment probe.  
**Follow-up:** extend use to any remaining tools that still parse deployment YAML ad hoc (e.g. CLI **examples** path only lists directories—no change required unless new commands appear).

### B. Safe application builder registry

- Declare **`builder_id`** (or reuse **`application_id`**) in registries; resolve via **explicit allowlist in code** mapping id → callable.
- **Never** `importlib.import_module()` arbitrary strings from YAML.
- Prepares for “plugin-like” extensibility **without** dynamic execution risk.

### C. Persistent store

- Phase 1: abstract interface + **SQLite** or **file-backed** JSON with clear schema/versioning.
- Later: **PostgreSQL** for multi-tenant and HA.
- Store: ingested payloads, normalized entities (when applicable), builder outputs, deployment snapshots, audit events.
  - **Pilot-ready starting point in repo:** `urban_platform/storage/` (JSONL file store; no external DB dependency).

### D. Ingestion API

- **POST** payloads validated against **provider** or agreed **consumer ingest** contract (e.g. city program submission).
- Return **validation receipt** (success/errors, schema version, record id).
- Start with **Program Reporting** city submission as first vertical.

### E. Application execution API

- **POST** “run application X for deployment/program/period” with store-backed inputs.
- Persist outputs after **consumer** schema validation.

### F. Output API

- GET outputs by deployment, program, period, city.
- Dashboard uses API in “server mode”; **local file** mode remains for laptop demos.

### G. Audit log

- Correlation id across ingest → validate → run → output.
- Include conformance/deployment validation runs (batch or event).

### H. Dashboard data-source abstraction

- Pluggable **FileOutputSource** vs **ApiOutputSource**; same panel code, different backend.

### I. Docker Compose Level 2

- Services: **airos-core**, **store**, **dashboard**, **worker or app** for program reporting; optional **provider simulator** later.
- Align with [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md) but evolve toward API-backed paths.

### J. Security and trust (later / beta blocker)

AuthN/Z, RBAC, secrets, participant directory, signed envelopes, data-sharing policy enforcement, reference catalog pull/cache, program spec distribution—**explicitly later** once APIs exist.

---

## 5) Recommended phased roadmap

Each phase includes **goal**, **likely touch areas**, **must not regress**, **acceptance criteria**, **suggested tests**, **risks**.

### Phase 0: Stabilization baseline

- **Goal:** Freeze understanding of current demos; keep conformance green.
- **Files:** CI docs, `README`, existing tests; no functional churn.
- **Must not change:** Spec semantics; demo outputs for tagged releases.
- **Acceptance:** All tests + conformance + supervisor pass; demo scripts documented.
- **Tests:** Full suite; optional snapshot of `deployment validate` output for example deployments.
- **Risks:** Documentation drift from code—mitigate with pointers to exact commands.

### Phase 1: Shared deployment config loader — **largely complete**

- **Goal:** One YAML parse path for deployment directories.
- **Files:** [`urban_platform/deployments/config_loader.py`](../urban_platform/deployments/config_loader.py), [`validate_deployment.py`](../tools/deployment_runner/validate_deployment.py), [`run_deployment.py`](../tools/deployment_runner/run_deployment.py), [`deployment_probe.py`](../tools/ai_dev_supervisor/deployment_probe.py).
- **Must not change:** Validation rules; runner allowlists; demo JSON outputs.
- **Acceptance:** Parity in counts/metadata vs pre-refactor behavior; tests cover loader + deployment probe + validation.
- **Tests:** `tests/test_deployment_config_loader.py`, existing deployment tests.
- **Risks:** Subtle ordering of validation vs errors—mitigate with regression tests.

### Phase 2: Safe builder registry

- **Goal:** Replace **deployment_id** branches and scattered dicts with a single **allowlisted** map from registry **`application_id` / `builder_id`** to known callables; YAML remains declarative, Python remains explicit.
- **Files:** `urban_platform/applications/...`, `tools/deployment_runner/run_deployment.py`, possibly `urban_platform/deployments/builder_registry.py` (new).
- **Must not change:** Conformance; consumer contracts; no dynamic imports from YAML.
- **Acceptance:** Flood + program reporting demos unchanged; runner codepaths shorter; negative test rejects unknown ids.
- **Tests:** Unit tests for registry map; integration run of both demos.
- **Risks:** Accidental broadening of callable surface—mitigate with exhaustive allowlist tests.

### Phase 3: Storage abstraction

- **Goal:** Introduce `AirOsStore` (or equivalent) interface: **put_ingest**, **put_output**, **get_latest**, **list_by_period**, **append_audit**.
- **Files:** new `urban_platform/storage/` (suggested); minimal SQLite or JSON-L implementation.
- **Must not change:** Existing file outputs until explicitly migrated; demos can still write `data/outputs` as export.
- **Acceptance:** Program reporting can round-trip a submission and an output in store-backed tests.
- **Tests:** Repository tests with temp DB/dir.
- **Risks:** Dual-write confusion—document **one** source of truth per mode (demo file vs store).

### Phase 4: Program Reporting vertical slice (production-like)

- **Goal:** HTTP ingest of **`city_program_submission`** → validate → store → run existing builder → store **`fund_release_review_packet`** + state summary → read API.
- **Files:** new API module under `urban_platform/` (e.g. `api/` or `runtime/`); reuse [`urban_platform/applications/program_reporting/`](../urban_platform/applications/program_reporting/).
- **Must not change:** Schemas; safety/blocked uses; no fund release automation.
- **Acceptance:** End-to-end test without Streamlit; payloads conform to consumer contracts.
- **Tests:** API integration tests (FastAPI/Flask TBD); schema validation reused from conformance utilities.
- **Risks:** PII in ingest—enforce synthetic/demo policy until security phase.

### Phase 5: Minimal AirOS Core API

- **Goal:** Single service boundary: **health**, **manifest/conformance summary**, **ingest**, **run application**, **fetch outputs**, **audit tail**.
- **Files:** new service package; reuse conformance and store.
- **Must not change:** CLI and Docker entrypoints for existing flows until explicitly wired.
- **Acceptance:** OpenAPI or documented REST; auth optional stub only.
- **Tests:** Contract tests on API responses.
- **Risks:** Premature public exposure—default bind localhost; document threat model.

### Phase 6: Dashboard API mode

- **Goal:** [`review_dashboard`](../review_dashboard/) selects **file** vs **API** backend via env/config.
- **Files:** `review_dashboard/...`, thin client module for HTTP.
- **Must not change:** Default demo behavior (file-based) for contributors without a server.
- **Acceptance:** Program Reporting tab works against API in CI (mock server optional).
- **Tests:** Panel tests with injected source.
- **Risks:** Duplicating domain logic in UI—keep panels presentation-only.

### Phase 7: Docker Compose Level 2 (production-like path)

- **Goal:** Compose brings up **core + store + dashboard + worker**; program reporting flow uses API + store.
- **Files:** `docker-compose.yml`, [`docs/DOCKER_COMPOSE_POC.md`](DOCKER_COMPOSE_POC.md) evolution.
- **Must not change:** Level 1 single-image story.
- **Acceptance:** One command brings stack up; smoke test hits health + ingest + output GET.
- **Tests:** CI job optional (heavy); document manual smoke.
- **Risks:** Compose drift from real deploy—label as POC.

### Phase 8: Governance and audit hardening

- **Goal:** Durable audit; deployment snapshots; validation receipts; output provenance linkage (ids, schema versions, manifest hashes).
- **Files:** storage layer, API, audit schema (spec increment when ready).
- **Must not change:** Review-only semantics for demos.
- **Acceptance:** Audit export for an incident review table-top.
- **Tests:** Audit ordering and immutability assumptions.
- **Risks:** Storage growth—retention policy documented.

### Phase 9: Beta security and federation preparation

- **Goal:** Auth, RBAC, secrets, signed envelopes, participant directory, policy enforcement, catalog/spec pull—**only** with explicit specs and deployment governance.
- **Files:** cross-cutting; new specs under `specifications/` as prerequisites per repo rules.
- **Must not change:** Domain meaning in network layer; no weakening conformance.
- **Acceptance:** Threat model + phased rollout doc per deployment class.
- **Risks:** Over-building before core store/API stable—gate on Phase 5–7 exit criteria.

---

## 6) Per-phase template (for execution tracking)

For each phase when executed:

| Field | Content |
|-------|--------|
| **Goal** | One paragraph outcome |
| **Files/modules likely affected** | Paths and ownership |
| **What should not change** | Contracts, conformance posture, demo safety wording |
| **Acceptance criteria** | Measurable |
| **Suggested tests** | pytest, conformance, manual smoke |
| **Risks** | Top 1–3 and mitigations |

*(Phases 0–9 above already include these bullets.)*

---

## 7) Concrete next three implementation tasks

These are **bounded**, Cursor-ready follow-ons. **Phase 1 (loader) is already landed**; treat Task 1 as **verification + residual integration** or move straight to Task 2.

### Task 1: DeploymentConfig loader — parity audit and CLI alignment

**Description:** Confirm **every** deployment-aware tool uses **`load_deployment_config()`** for YAML that describes the same deployment folder; add thin wrappers or helpers where [`tools/airos_cli.py`](../tools/airos_cli.py) or other entrypoints still duplicate path logic. Add regression tests if any gap is found. **No change** to validation rules, runner allowlists, or output shapes.

**Acceptance criteria:** Grep shows no stray `yaml.safe_load` of deployment registries outside the loader (except optional legacy scripts explicitly documented); full test + conformance pass; `deployment validate` / `deployment run` unchanged for `flood_local_demo` and `program_reporting_state_demo`.

### Task 2: Safe application builder registry (allowlisted)

**Description:** Introduce a single Python module that maps **`application_id`** (from `application_registry.yaml`) to **explicit** callables for the POC runner—replacing `APPLICATION_ALLOWLIST` scattered logic and **deployment_id** special-cases where safe. Registries remain declarative; resolution is **code-defined**. Unknown ids fail closed with a clear error.

**Acceptance criteria:** Same demo outputs (or byte-identical JSON where deterministic); unknown `application_id` in registry fails in tests; no dynamic import from YAML strings.

### Task 3: Storage abstraction for ingests and outputs

**Description:** Define a small **`AirOsStore`** interface and a **SQLite** (or file-backed) implementation to persist **ingested payloads** and **builder outputs** keyed by `deployment_id`, `program_id`, `reporting_period`, `city_id`, etc. Program Reporting is the first consumer: store submission and generated review packet references. File writes under `data/outputs` may remain as **export** for backward compatibility.

**Acceptance criteria:** Unit tests for round-trip; no schema changes; Program Reporting E2E test can read back stored records without the dashboard.

---

## 8) Non-goals (this plan does not commit to immediate delivery of)

- Arbitrary plugin loading or runtime module resolution from registries
- Real fund release, treasury integration, or enforcement automation
- Real emergency dispatch or operational orders from AirOS outputs
- Production-grade security (auth, HSM, full RBAC) before explicit phase
- Multi-agency signed messaging at scale
- Kubernetes/Helm as the default distribution model
- Full reference catalog pull/cache/TTL and cryptographic signing
- Full program spec registry network pull/adoption

---

## 9) Risk register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dynamic code execution from YAML/registry strings | Critical | Allowlists only; code review; tests that unknown ids fail |
| Dashboard accumulates domain logic | High | Enforce presentation-only panels; builders own semantics |
| Demo JSON mistaken for government decisions | High | Fixed blocked uses, copy, audit disclaimers; RBAC later |
| Validator vs runner schema drift | Medium | Shared validation helpers; conformance + integration tests |
| YAML parsing duplication (partially addressed) | Medium | Mandatory use of `DeploymentConfig` loader in new code |
| Weak audit trail | High | Phase 8 focus before external APIs |
| Unclear storage ownership (file vs DB) | Medium | Explicit modes; documented retention |
| APIs exposed without auth | Critical | Localhost default; auth phase gate |

---

## 10) Document history

| Version | Note |
|---------|------|
| 1.0 | Initial production-like roadmap; reflects repo state including shared deployment config loader. |
