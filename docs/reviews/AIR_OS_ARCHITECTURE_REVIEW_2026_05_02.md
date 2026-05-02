# AirOS — Architecture & development approach review

**Date:** 2026-05-02  
**Scope:** Review only (no code/spec/doc changes in the rest of the repo).  
**Evidence:** Preflight on this date: `python tools/ai_dev_supervisor/run_review.py --run-conformance`, `python -m pytest -q`, and `python main.py --step conformance` all exited **0** (92 tests passed; conformance reported **108** validated checks).

---

## 1. Executive summary

AirOS is positioned as a **specs-first, multi-domain urban intelligence platform** for Indian governance realities: fragmented agencies, uneven data maturity, and the need for **open-data-first** value before deep integrations. The repository delivers this story consistently in **root `AGENTS.md`**, **`README.md`**, **`docs/URBAN_CONTEXT_INDIA.md`**, **`docs/AI_COE_OPERATING_STRATEGY.md`**, **`docs/USE_CASE_ROADMAP.md`**, **`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`**, and **`docs/DATA_SOURCE_CATALOG.md`**, backed by machine-readable policy in **`specifications/spec_policy.yaml`** and **`specifications/specs_policy.yaml`**.

The **technical spine** is strong: **`specifications/manifest.json`** registers artifacts; **`urban_platform/specifications/conformance.py`** resolves Draft 2020-12 schemas; **`urban_platform/specifications/audit.py`** runs a broad conformance audit (schema validity, manifest integrity, domain YAML structure, registered examples, output artifacts when present, OpenAPI, local API/SDK probes). The **reference air-quality application** still executes primarily through **`src/pipeline.py`** (see **`urban_platform/applications/air_pollution/pipeline.py`**, which explicitly delegates to legacy `src`), while **connectors**, **fabric** (observation/feature stores), **decision_support**, and **SDK/API** live under **`urban_platform/`**.

Two **newer vertical slices**—**flood** (`urban_platform/connectors/flood/`, `urban_platform/processing/flood/`, `urban_platform/applications/flood/`, `review_dashboard/components/flood_panel.py`) and **property/buildings** (`urban_platform/processing/property_buildings/`, `urban_platform/applications/property_buildings/`, `review_dashboard/components/property_buildings_panel.py`)—demonstrate a **repeatable pattern**: domain spec YAML, provider/consumer JSON Schemas, examples under **`specifications/examples/`**, processing + application modules, tests under **`tests/`**, and read-only dashboard panels.

**Gaps** include: no **`specifications/domain_specs/*`** entry dedicated to the **air-quality reference domain** (unlike `flood_risk.v1.yaml` and `property_buildings.v1.yaml`); **legacy vs platform** split (`src/` vs `urban_platform/`) increases cognitive load; **no `.github/` workflows** observed in-repo for automated conformance/tests; **`tools/ai_dev_supervisor/domain_maturity_probe.py`** encodes maturity only for **`flood_risk`** and **`property_buildings`**; **`dashboard_probe.py`** default expected labels skew toward an older naming (“Air Quality Review Console”) while **`review_dashboard/app.py`** uses **“AirOS Review Console”**.

Overall, AirOS is **architecturally serious about contracts and safety**; scaling to many domains will require **tightening parity** (especially AQ as a first-class domain spec + less legacy coupling), **CI enforcement**, and **config-driven** maturity/review tooling.

---

## 2. What is strong

- **Specs-first posture (strategic + operational):** Non-negotiables in **`AGENTS.md`**, sequence in **`docs/SPECS_FIRST_DEVELOPMENT.md`**, and policy flags in **`specifications/spec_policy.yaml`** align contributors and agents on provider → platform → domain → consumer ordering.
- **Conformance depth:** **`urban_platform/specifications/audit.py`** goes beyond “JSON Schema compiles”: examples registered in **`specifications/manifest.json`** are validated against artifacts; output files under **`data/outputs/`** are checked when present; domain YAML files under **`specifications/domain_specs/`** get a **required-keys** pass (`audit_domain_specs`).
- **Reusable platform objects and cross-domain semantics:** **`specifications/platform_objects/`** (e.g. `observation`, `entity`, `feature`, `source_reliability`) and **`urban_platform/quality/source_reliability.py`** are framed as variable-agnostic—appropriate for flood, traffic, AQ, etc.
- **Domain sequencing discipline:** **`docs/USE_CASE_ROADMAP.md`** phases (city base → governance → situational awareness → …) and **`AGENTS.md`** “Domain sequencing and access constraints” make **open-data-first** and **authorized integrations later** explicit.
- **Human review and safety gates:** AQ pipeline documentation and code paths emphasize **decision packets**, **audit**, **synthetic/interpolated warnings**, and **blocked recommendations**; flood/property add **`field_verification_task`** consumer contract and **`urban_platform/applications/*/field_tasks.py`** with tests.
- **Forward-deployment readiness (documentation):** **`docs/URBAN_CONTEXT_INDIA.md`** and **`docs/AI_COE_OPERATING_STRATEGY.md`** explain why specs and progressive integration matter for rotating staff and fragmented agencies—this is rare and valuable institutional context.
- **Agentic development support:** **`tools/ai_dev_supervisor/run_review.py`** composes governance probes (`spec_policy_probe`, `conformance_probe`, `domain_maturity_probe`, optional `dashboard_probe`) and can emit reports under **`tools/ai_dev_supervisor/reports/`**, giving agents a **single entrypoint** for “is this repo healthy?”

---

## 3. Key risks and gaps

| Area | Risk / gap |
|------|------------|
| **Architecture** | **Dual stack:** reference AQ remains in **`src/`** while platform direction is **`urban_platform/`**; migration note in **`urban_platform/applications/air_pollution/pipeline.py`** is honest but leaves **unclear long-term ownership** of orchestration. |
| **Specifications** | **No `domain_specs` YAML for air quality** while AQ is the flagship narrative in **`README.md`**—specs-first story is **weaker for the default app** than for flood/property. |
| **Conformance** | Strong locally, but **no in-repo CI** (`.github/` absent) to **block regressions** on PRs. |
| **Code organization** | Connectors split: AQ/weather/OSM in **`urban_platform/connectors/`** but much **feature/model/recommendation** logic still **`src/`**—boundary blur for new contributors. |
| **Dashboard usability** | Streamlit app is **local-first** and multi-tab; depends on **`UrbanPlatformClient`** (**`urban_platform/sdk/client.py`**)—good—but empty states and conformance visibility are **operator-dependent** (must run pipeline + conformance). |
| **Domain maturity** | Only **two** domains in **`domain_maturity_probe.py`**; adding domains requires **code edits** to the probe. |
| **Safety / governance** | Domain YAML checks are **structural**, not a guarantee that **runtime code** honors `safety_gates` / `blocked_uses` from YAML—**semantic gap** between spec and enforcement. |
| **Forward deployment** | No single **“city profile”** package (e.g. one directory per city with `config`, fixtures, enabled domains)—FD engineers must infer from **`config.yaml`**, **`GETTING_STARTED.md`**, and scattered outputs. |
| **Testing** | **92 tests** with good coverage on newer slices; AQ path breadth relies partly on **integration-style** historical tests—worth monitoring as **`src/`** shrinks or moves. |
| **CI/CD** | **Missing** automated pipeline in repository root—**highest process risk** for multi-vendor / agentic contribution. |

---

## 4. Specific architectural concerns

1. **`src/` vs `urban_platform/` duplication and direction**  
   **`README.md`** “Project layout” still centers **`src/`** as the pipeline home while **`urban_platform/`** is the “layered platform.” **`main.py`** loads config from **`src.config`** and runs **`urban_platform.applications.air_pollution.pipeline`**, which immediately calls **`src.pipeline.run_pipeline`**. Risk: **two places** for bugfixes and **inconsistent** application of new platform patterns (e.g. strict consumer validation at write time).

2. **Boundary: platform vs domain vs dashboard**  
   - **Good:** Flood/property **dashboard payloads** live in **`urban_platform/applications/*/dashboard_payload.py`** with tests **`tests/test_*_dashboard_payload.py`**.  
   - **Watch:** **`review_dashboard/app.py`** contains **presentation helpers** (`_queue_df`, `_banner`, `_confidence_label`)—acceptable if they only **shape** data already produced under contracts; periodic review ensures **no new domain rules** creep into Streamlit.

3. **Consumer payloads before UI**  
   Flood and property paths are **test-first against schemas**. AQ outputs are validated by **conformance audit** against **`specifications/json_schema/v1/`** decision packet and related profiles—**strong**, but the **domain spec YAML** for AQ is missing, so the **full four-layer traceability** (domain semantics file → code) is incomplete for the flagship domain.

4. **Domain logic in platform layers**  
   **`urban_platform/decision_support/`** and **`urban_platform/processing/interpolation.py`** are legitimately shared; risk is **AQ-specific thresholds** leaking further into “generic” modules without **`domain_specs`** documentation—worth cataloging as migration proceeds.

5. **Examples/fixtures vs runtime**  
   **`specifications/examples/`** is clearly separated; **`data/raw`**, **`data/processed`**, **`data/outputs`** are runtime. **`README.md`** documents **synthetic fallback** for AQ—appropriately flagged. Crowd example uses **`data/edge/video_camera_people_count.jsonl`**—edge path is clear.

6. **Synthetic / demo data**  
   Well-documented in **`README.md`** and surfaced in UI banners in **`review_dashboard/app.py`**. **No issue** if teams keep conformance + UI warnings aligned when contracts change.

7. **`urban_platform/specifications/` vs root `specifications/`**  
   Runtime code under **`urban_platform/specifications/`** **consumes** repo-root **`specifications/`** (e.g. `SPEC_ROOT` = repo `specifications/`). Naming is slightly confusing for newcomers (“two specifications folders”)—**documentation-only** clarification could help later.

8. **Dashboard probe vs UI strings**  
   **`tools/ai_dev_supervisor/dashboard_probe.py`** defaults include **“Air Quality Review Console”**; **`review_dashboard/app.py`** uses **“AirOS Review Console”**—probe may **false-negative** unless callers pass `expected_labels` or defaults are updated.

---

## 5. Specs and conformance review

- **Organization:** **`specifications/provider_contracts/`**, **`platform_objects/`**, **`consumer_contracts/`**, **`domain_specs/`**, **`examples/`**, and **`json_schema/v1/`** are **consistent** with **`specifications/README.md`** and **`specifications/ARCHITECTURE_NOTE.md`**. Manifest entries mix **`json_schema/v1/...`** and **`provider_contracts/...`** paths—**works**, but contributors should follow **existing manifest patterns** to avoid resolver/ref issues.
- **Manifest registration:** **`specifications/manifest.json`** is the **source of truth** for artifact names used in audit; **`examples`** subsection ties fixtures to **`schema_name`**—**clear** when entries exist.
- **Examples:** **`audit_examples`** validates each registered example—**high leverage** for agentic PRs.
- **Domain specs enforceability:** **`audit_domain_specs`** checks **presence of keys**, not semantic consistency with **`allowed_variables`** vs Python—**gap** between “spec as law” and “spec as structured doc.”
- **Consumer contracts strictness:** AQ-related profiles under **`json_schema/v1/decision_packet.profile.air_quality.v1.schema.json`** are **appropriately strict** for operational safety; **`urban_decision_packet_core`** offers a **looser** shell for new domains—good **progressive strictness** pattern. Risk: **inconsistent** strictness between domains until each matures—**acceptable** if documented per domain spec `decision_packet_profile`.
- **Conformance in CI:** Today **manual / agent-local**; **roadmap Phase 2** in **`docs/USE_CASE_ROADMAP.md`** already calls for conformance in CI—**implementation lag** vs intent.

---

## 6. Domain development pattern review (flood vs property/buildings)

**Common pattern (both domains):**

1. **`specifications/domain_specs/<domain>.v1.yaml`** — purpose, actors, safety, phased inputs.  
2. **Provider contracts** under **`specifications/provider_contracts/`** + **examples** under **`specifications/examples/<domain>/`**.  
3. **Consumer contracts** (dashboard + decision/review packet + **`field_verification_task`**) + examples.  
4. **Processing:** **`urban_platform/processing/<domain>/features.py`** (+ property adds **`open_data_features.py`** for open-data-first slice).  
5. **Applications:** **`dashboard_payload.py`**, packet builders (**`decision_packets.py`** vs **`review_packets.py`**), **`field_tasks.py`**.  
6. **Tests:** mirrored under **`tests/test_<domain>_*.py`**.  
7. **Dashboard:** **`review_dashboard/components/*_panel.py`** + **`tests/test_*_dashboard_panel_demo.py`**.

**Differences:**

| Aspect | Flood (`flood_risk`) | Property (`property_buildings`) |
|--------|----------------------|----------------------------------|
| **Ingestion** | **`urban_platform/connectors/flood/ingest_file.py`** on maturity checklist | **No dedicated connector** on maturity list—open-data path may be **fixture-driven** first |
| **Packet type** | **`flood_decision_packet`** consumer | **`property_building_review_packet`** consumer |
| **Open-data narrative** | Strong in domain spec + examples | Explicit **`open_data_inputs`** / phasing in YAML + **`PROPERTY_BUILDINGS_OPEN_DATA_SEQUENCE`** in **`domain_maturity_probe.py`** |
| **Maturity tooling** | Same probe | Same probe + **open-data-first sequence** string tuple |

**Verdict:** The **pattern is clear enough to replicate** for a third domain if teams copy **flood** (when file ingestion exists) or **property** (when starting from open-data features only). The **air-quality reference** should eventually **conform to the same checklist** (including a **`domain_specs/air_quality.v1.yaml`** or similarly named artifact) so **all flagship paths** teach the same lesson.

---

## 7. Agentic software engineering review (`tools/ai_dev_supervisor/`)

**Current strengths:**

- **`run_review.py`**: orchestrates **conformance subprocess**, **governance text probes**, **domain maturity** for two domains, optional **dashboard HTTP** probe, writes **`tools/ai_dev_supervisor/reports/agent_review_report.{md,json}`**.
- **`conformance_probe.py`** (imported by run_review): treats conformance as **first-class**.
- **`spec_policy_probe.py`**: validates policy files exist and **`specs_first`** flag—**fast guardrail**.

**Suggested improvements (non-implemented):**

| Idea | Rationale |
|------|-----------|
| **Domain maturity config** (YAML/JSON registry) instead of **hard-coded paths** in **`domain_maturity_probe.py`** | Scales to N domains without Python edits; FD could **add a city domain** by config PR. |
| **Dashboard smoke tests** | Beyond HTTP substring: **Playwright** or Streamlit **AppTest** (if adopted) for critical tabs; today **`dashboard_probe.py`** is **minimal** and **string-sensitive**. |
| **PR evidence bundle** | Standard artifact: `conformance_report.json` + pytest summary + maturity JSON **attached** to PR template—reduces agent “forgot conformance” risk. |
| **Cursor prompt / checklist generation** | Emit a **single markdown** from manifest + open questions in domain specs for **session bootstrap** (complements **`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`**). |
| **CI integration** | Run **`python main.py --step conformance`** and **`pytest`** on every PR—**highest ROI**. |
| **Architectural drift detection** | e.g. fail if new **`src/connectors/`** appear or if **`review_dashboard`** imports **`src.*`** directly (policy-specific). |
| **Spec↔code linkage checks** | Optional: require **domain_id** in codeowners or **manifest `domain` metadata** for new artifacts—today **no automated** “every connector has provider contract” beyond human review + rules in **`AGENTS.md`**. |

---

## 8. Forward deployment readiness

**What works for an FD engineer in a new city:**

- **Discovery:** **`docs/DATA_SOURCE_CATALOG.md`**, **`docs/USE_CASE_ROADMAP.md`**, domain YAML **`open_data_inputs` / `authorized_municipal_inputs`** (property; flood has analogous provider lists).
- **Config:** **`config.yaml`**, **`.env`** / **`.env.example`**, **`GETTING_STARTED.md`** for run instructions.
- **Local run:** **`python main.py`** (AQ reference), **`python main.py --step conformance`**, **`streamlit run review_dashboard/app.py`**.
- **Adding a connector:** Clear rule—**provider contract first** (**`AGENTS.md`**); patterns under **`urban_platform/connectors/`** (OpenAQ, flood file ingest, camera ingest).
- **Validation:** Conformance report path **`data/outputs/conformance_report.json`**; dashboard can surface it (**`review_dashboard/app.py`** sidebar).

**Friction / gaps:**

- **No “city kit”** (single folder or template) bundling boundary GeoJSON, enabled domains, and fixture sources of truth.
- **Air pollution** still **heaviest** path through **`src/`**—FD may **mistakenly patch legacy** instead of **`urban_platform/`**.
- **Operational deployment** (containers, secrets, multi-user auth) **out of scope** in repo—expected for prototype, but **P1** for real FD if not documented elsewhere.

---

## 9. Prioritized recommendations

### P0 — Must fix before scaling to more domains

| Recommendation | Rationale | Affected areas | Risk if not addressed | Bounded next task |
|------------------|-----------|----------------|------------------------|---------------------|
| **Add an air-quality (or “urban_observability_pm25”) domain spec YAML** and align README/manifest references | Specs-first requires **four families** for each domain; AQ is the **reference app** without a **`domain_specs/*.yaml`** file | `specifications/domain_specs/`, `specifications/manifest.json` (if registration needed), cross-links in `docs/` | **Strategic inconsistency**; agents ship AQ logic **without** machine-readable domain gates | Author **`air_quality.v1.yaml`** (or merge into existing template pattern) with variables, thresholds, safety gates, blocked uses—**no code behavior change** in first PR |
| **Clarify migration plan: `src/` → `urban_platform/`** (even if incremental) in a single architecture note | Reduces **duplicate expertise** and wrong-file edits | `src/`, `urban_platform/applications/air_pollution/`, `docs/` or `specifications/ARCHITECTURE_NOTE.md` | **Velocity collapse** and regression risk as domains multiply | Add a **short “current ownership map”** table: which modules are canonical vs legacy |

### P1 — Should fix before serious forward deployment

| Recommendation | Rationale | Affected areas | Risk if not addressed | Bounded next task |
|------------------|-----------|----------------|------------------------|---------------------|
| **Add CI** (GitHub Actions or equivalent) running **`pytest -q`** + **`python main.py --step conformance`** | **Institutional memory** for quality; aligns with roadmap Phase 2 | `.github/workflows/` (new), `requirements.txt` / lock | **Non-reproducible** agent merges; FD cities get **broken baselines** | One workflow file on `push`/`pull_request` |
| **Fix or parameterize `dashboard_probe` expected labels** vs **`review_dashboard/app.py`** titles | Avoid **false alarms** in supervisor | `tools/ai_dev_supervisor/dashboard_probe.py`, tests | Maturity reports **untrusted** | Change defaults to **“AirOS Review Console”** + “Flood” / “Property” tab strings **or** read from a tiny config file |
| **Semantic linkage tests** (selected): e.g. domain YAML **`allowed_variables`** subset checked against feature column names in tests | Closes gap between **structural** domain spec validation and code | `tests/`, `specifications/domain_specs/` | **Silent drift** between spec and features | One pytest that loads YAML and asserts known keys for **one domain** |

### P2 — Useful improvements

| Recommendation | Rationale | Affected areas | Risk if not addressed | Bounded next task |
|------------------|-----------|----------------|------------------------|---------------------|
| **Externalize domain maturity checklists** to data files | Faster domain onboarding | `tools/ai_dev_supervisor/domain_maturity_probe.py` | Probe file becomes **merge bottleneck** | JSON checklist + loader |
| **Conformance “dashboard” tab** enhancements | FD visibility | `review_dashboard/` | Operators skip reading JSON | Small UI: show **fail counts** by `contract_type` |
| **Expand `urban_platform/api/local.py`** contract tests for flood/property payloads | Parity with AQ artifact validation | `tests/`, `urban_platform/api/` | SDK consumers see **partial shapes** | Add tests that load **fixture JSON** from `specifications/examples/` through API builders (if wired) |

### P3 — Later enhancements

| **Observability** for connector runs (metrics, structured logs), **multi-tenant** city_id in all artifacts, **spatial indexing** for large OSM extracts (already noted in README limitations), **residual calibration** for ML uncertainty.

---

## 10. Suggested next five bounded Cursor tasks

Each task is **small**, **specs-first**, and **testable** (prompt text suitable for copy-paste):

1. **Add `specifications/domain_specs/air_quality.v1.yaml`** (or agreed name) describing PM2.5 variables, India category mapping reference, safety gates, synthetic/interpolation blocked uses, and human review prompts—**mirror** style of `flood_risk.v1.yaml` / `property_buildings.v1.yaml`. *Tests:* conformance domain spec audit still passes.

2. **Add a “Source layout” subsection** to **`specifications/ARCHITECTURE_NOTE.md`** documenting **`src/` vs `urban_platform/`** ownership and the **`run_air_pollution_pipeline` → `src.pipeline`** delegation. *Tests:* none required; human readability.

3. **Add CI workflow** `.github/workflows/ci.yml` running Python **3.10+** with `pip install -r requirements.txt`, `pytest -q`, and `python main.py --step conformance`. *Tests:* CI green on branch.

4. **Align `dashboard_probe` default `expected_labels`** with **`review_dashboard/app.py`** (`page_title` / sidebar title) and add a **unit test** that defaults match. *Tests:* `tests/test_ai_dev_supervisor_dashboard_probe.py` updated.

5. **Add `domain_maturity` checklist file** (e.g. `tools/ai_dev_supervisor/domain_checklists/flood_risk.json`) and **refactor probe** to load paths from file—**behavior unchanged** for flood/property. *Tests:* existing supervisor tests + new test for loader.

---

## Appendix: Files and directories explicitly reviewed

**Context & strategy:** `README.md`, `AGENTS.md`, `docs/URBAN_CONTEXT_INDIA.md`, `docs/AI_COE_OPERATING_STRATEGY.md`, `docs/USE_CASE_ROADMAP.md`, `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`, `docs/SPECS_FIRST_DEVELOPMENT.md`, `docs/DATA_SOURCE_CATALOG.md`

**Specifications:** `specifications/spec_policy.yaml`, `specifications/specs_policy.yaml`, `specifications/manifest.json`, `specifications/domain_specs/`, `specifications/provider_contracts/`, `specifications/platform_objects/`, `specifications/consumer_contracts/`, `specifications/examples/`, `specifications/json_schema/v1/`, `urban_platform/specifications/` (`audit.py`, `conformance.py`, …)

**Implementations:** `urban_platform/` (connectors, fabric, processing, applications, decision_support, sdk, api), `src/`, `review_dashboard/`, `tools/ai_dev_supervisor/`, `tests/`, `main.py`

**Crowd example:** `urban_platform/connectors/camera/`, `data/edge/video_camera_people_count.jsonl`, `README.md` “Crowd” section

---

*End of review.*
