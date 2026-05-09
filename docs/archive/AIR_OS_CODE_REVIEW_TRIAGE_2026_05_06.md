# AirOS Deep Code Review — Triage and Response
**Review date:** 2026-05-06
**Review source:** Claude Code deep code review (10-dimension structured review, findings F-01 through F-20)
**Triage author:** Project owner response via ChatGPT, recorded here for contributor reference
**Scope of this document:** Classification only. No runtime code, schemas, or tests are changed here.

---

## 1. Context and Framing

The code review is **directionally correct** on major structural risks. However, it evaluates AirOS against a production-grade standard, while the current milestone is a **pilot, review-oriented Decision Support Operating System**. The correct response is to classify findings by phase rather than treat them all as immediate work.

**Principle:** Do not let this review push the project into a large production-hardening phase ahead of schedule. The review becomes a structured backlog, not a redirect from the current SDK use-case track.

**Current active track remains:** SDK-driven Program Reporting use case.

---

## 2. Finding Classification

### 2a. Already Addressed / Partially Addressed

| Finding | Title | Status | Notes |
| --- | --- | --- | --- |
| F-07 | Health check is non-functional | **Partially addressed** | `/health/ready` exists and was smoke-tested with a fresh store (2026-05-06 runtime smoke session). The finding title is stale; remaining gap is production-level observability (dependency health, structured metrics), which is deferred. Downgrade severity from High to Low for current pilot phase. |
| — | SDK is an early skeleton | **Addressed** | SDK now has a documented public surface (`docs/SDK_SURFACE.md`), internal/advanced labeling, guardrails committed in `07bf7f2`, and the current track is an SDK-driven use case. Review observation was based on an earlier state. |
| — | Platform is only air-quality-centric | **Addressed** | Core API, Program Reporting, Flood, descriptors, evidence bundles, and store lifecycle have all been validated in runtime smoke. Multi-domain architecture is operational. |

---

### 2b. Accepted for Immediate Small Fixes ("Do Now")

These are small, safe changes that align with the current pilot phase and governance/safety posture. Each is a separate bounded task.

| Finding | Title | Effort | Rationale |
| --- | --- | --- | --- |
| F-04 | Synthetic fallback masks provider failures | Small | Directly supports governance/safety posture. Emit a structured `provider_failure` audit event and ERROR log when synthetic fallback fires. First recommended fix. |
| F-05 | OpenAQ v2 function still present | Small | Dead/legacy code removal. Hard-deprecate or delete `fetch_openaq_pm25()`. |
| F-06 | `sample_mode: true` production risk | Small | Change `DevConfig.sample_mode` default to `False`; add startup warning when `sample_mode` is `True` in non-dev context. |
| F-07 (residual) | Update review note for `/health/ready` | Small | Downgrade finding in project docs; note that production-level observability is deferred. No code change. |
| F-13 | No CI/CD pipeline | Small | Add minimal GitHub Actions workflow: `pytest -q`, `conformance`, schema lint. One-day investment, high return. |
| F-17 | Secrets not validated at startup | Small | Add `validate_environment()` check for required API keys at startup; emit structured warning when OpenAQ connector is enabled without key. |
| F-20 | `fabric/` naming implies distributed architecture | Small | Add module-level docstring clarifying `fabric/` is an in-memory aggregation layer, not a distributed event fabric. No rename yet. |

---

### 2c. Accepted but Deferred ("Do Soon" — after current SDK track)

These are valid fixes that improve correctness and maintainability but are not blocking the current track.

| Finding | Title | Effort | Rationale |
| --- | --- | --- | --- |
| F-09 | IDW runs with fewer than min stations | Small | Add minimum-station guard before IDW; return NaN cells instead of meaningless single-station gradient. |
| F-12 | Forward-fill of NaN cells is arbitrary | Small | Replace with explicit NaN + `pm25_fill_method` flag. |
| F-10 | Cache invalidation is TTL-only | Small | Add config-sensitive parameters (lookback_days, h3_resolution) to cache key. |
| F-16 | CRS hardcoded for India | Small | Auto-detect appropriate UTM zone from study area centroid; validate at startup. |
| F-15 | No model versioning or drift detection | Medium | Add lightweight model registry: training timestamp, input hash, feature list, metrics, baseline comparison. |
| F-08 | No observability infrastructure | Medium | Add structured logging fields, run duration instrumentation, structured audit event fields. Full Prometheus/OTel deferred. |
| F-11 | `conformance.fail_on_error` defaults to False | Small | Change default to `True`; add `warn_only` escape for dev. Requires decision on governance gate model (see Q6). |

---

### 2d. Production-Hardening Backlog ("Defer")

These are real and critical for production but are explicitly out of scope for the current pilot milestone. They belong in the **Production hardening** and **Identity & Trust** milestones.

| Finding | Title | Effort | Why Deferred |
| --- | --- | --- | --- |
| F-01 | No API authentication or authorization | Large | Critical for production multi-agency deployment. Deferred to Identity & Trust milestone. |
| F-02 | JSONL file store is not concurrency-safe | Large | Critical for production. Deferred to Persistence milestone (SQLite → PostgreSQL). |
| F-03 | `legacy_pipeline.py` is a 767-line monolith | Large | Valid but not the product-runtime path. Deferred to AQ first-class app migration. |
| F-14 | All pipeline I/O is synchronous and blocking | Medium | Valid performance concern for multi-city production. Deferred with F-03. |
| F-18 | Incomplete type annotations | Medium | Good hygiene; deferred until mypy can be added to CI cleanly. |
| F-19 | Review dashboard has no access control | Medium | Deferred to Identity & Trust. Note: treat dashboard as pilot console only until then. |

---

### 2e. Needs Owner Decision

These findings require a product/governance decision before implementation can proceed.

| Finding | Title | Decision required | See Q# |
| --- | --- | --- | --- |
| F-11 | `conformance.fail_on_error` default | Should conformance failure block outputs from reaching reviewers, or flag for operator review? | Q6 |
| F-01 | API auth/RBAC | Multi-tenant shared deployment vs. separate instances per agency? | Q2 |
| F-15 | Model retraining cadence | Retrain per run (demo) vs. scheduled/triggered (production)? | Q5 |
| — | Synthetic data as simulation mode | Is synthetic data only degraded fallback, or also an explicit scenario-modeling mode? | Q10 |

---

## 3. Current Owner Decisions (Answers to Review Questions Q1–Q10)

### Q1. Should `legacy_pipeline.py` remain separate from Core API?

**Decision:** No, not permanently. But do not merge abruptly.

Near term, treat `legacy_pipeline.py` as the **legacy Air Quality reference pipeline**. The Core API is the **product-runtime path** for AirOS pilot apps. The unification path is app-by-app: first make Air Quality a first-class AirOS app descriptor with bounded builders and explicit contracts, then migrate selected AQ outputs into Core records/runs/outputs/evidence. Do not force the 767-line pipeline directly into the Core API.

---

### Q2. Multi-agency deployment: shared multi-tenant or separate instances?

**Decision:** For v1 pilot, assume **separate deployment instances per city/agency** with network isolation. Do not design row-level multi-tenancy yet.

For production, multi-agency sharing will require: tenant IDs, agency identity, scoped API keys/JWT claims, row-level access control, and audit events tied to identities. That is a later Identity & Trust track.

---

### Q3. Who is the SDK for?

**Decision:** The SDK serves three audiences in order:
1. Internal AirOS developers
2. Trusted implementation partners building apps/adapters
3. Eventually, external ecosystem developers

For now, document it as **pilot/stable-for-trusted-developers**, not public semver-stable. The supported surface is exactly what `docs/SDK_SURFACE.md` says. Internal helpers like `specs_helpers` must not be advertised as public API.

---

### Q4. Is `OPENAQ_API_KEY` mandatory for production?

**Decision:** Yes. Treat `OPENAQ_API_KEY` as **mandatory when the OpenAQ connector is enabled** in production-like mode.

Unauthenticated fallback is acceptable only for local demo/dev. The system must emit a structured warning or `validate_environment()` failure when production-like mode enables OpenAQ without a key. This is part of F-17 (Do Now).

---

### Q5. Model retraining cadence?

**Decision:** For demos, retrain-per-run is acceptable.

For production: do not retrain blindly on every run. Use a model registry and retrain on schedule or when data quality/volume thresholds are met. Store model metadata: training timestamp, input hash, feature list, metrics, and previous baseline comparison. This is F-15 (Deferred: Do Soon).

---

### Q6. Should conformance failure block outputs?

**Decision:** For governance outputs, yes — conformance failure should prevent outputs from reaching reviewers as valid decision-support artifacts.

The graduated model:
- `development`: warn-only allowed
- `pilot/review mode`: store failed run + receipt, but do not publish valid output
- `production`: hard gate

The current default (`fail_on_error: false`) should move toward hard-gate for non-dev contexts. Implement `conformance.warn_only: true` as an explicit dev-mode escape hatch. This is F-11 (Deferred: Do Soon, pending this decision being finalized in config).

---

### Q7. Are Flood and Property production-intended or templates?

**Decision:** Flood is a pilot app. Program Reporting is a pilot app. Property Buildings is an experimental/template vertical unless documented otherwise.

Any module with placeholder decision logic must be **marked as pilot/template** and must not be presented as production-ready. Audit placeholder comments before any public-facing deployment documentation claims production readiness for these domains.

---

### Q8. Who accesses the review dashboard?

**Decision:** Currently, treat the Streamlit dashboard as a **developer/reviewer pilot console for controlled environments only**.

If used by real governance reviewers, it must sit behind auth (reverse proxy/basic auth short term, integrated identity later). Do not expose the dashboard on a public network without auth.

---

### Q9. Is H3 resolution 8 the default for all cities?

**Decision:** No. H3 resolution should depend on city area, sensor density, intended decision granularity, and compute budget.

Resolution 8 may be reasonable for some pilots, but the pipeline should validate whether station density is sufficient for the chosen resolution and warn or block interpolation when coverage is inadequate. This connects to F-09 (minimum station guard, Deferred: Do Soon).

---

### Q10. Is synthetic data only demo/dev, or also a simulation mode?

**Decision:** Split into two explicit modes:
- **Synthetic fallback mode:** degraded provider failure path — never valid for real recommendations, always triggers a structured audit event (F-04, Do Now)
- **Simulation/scenario mode:** explicit, labeled, acceptable for what-if analysis — must be a separate mode with clear labeling and must not be mixed with operational recommendations

Currently, synthetic data is treated only as fallback. This decision formalizes that production must never silently substitute synthetic for real observations. Scenario modeling should be a separately flagged and labeled path.

---

## 4. Recommended Implementation Sequence

Based on the classification above and the current active track (SDK-driven Program Reporting use case), the recommended sequence is:

### While the SDK use case track is active:
- No review fixes. SDK walkthrough, example, tests, and verification first.

### After the SDK use case track closes:
1. **Create code review triage document** (this document — already done)
2. **F-04:** Emit structured `provider_failure` audit event when synthetic fallback fires (first implementation fix)
3. **F-13:** Add minimal GitHub Actions CI workflow
4. **F-06:** Change `sample_mode` default; add startup warning
5. **F-05:** Hard-deprecate or remove `fetch_openaq_pm25()` (v2)
6. **F-17:** Add `validate_environment()` startup check for connector keys
7. **F-20:** Add `fabric/` module docstring
8. Then: Do Soon fixes (F-09, F-12, F-10, F-16, F-11, F-15, F-08) as separate bounded tasks

---

## 5. What This Document Is Not

- This document is **not a sprint plan or task brief** — it is a classification record.
- It does **not authorize** starting any production-hardening work (F-01, F-02, F-03, F-14, F-18, F-19) before the relevant milestones are selected.
- It does **not override** `docs/EXECUTION_TRACKER.md` — the tracker remains the operational control board. This document is an input to the tracker's backlog.
- Coding agents must **not begin implementing any fix** listed here without an explicit task in the tracker with status **Not started → In progress**.
