# AirOS Execution Tracker

## Recent Sessions

### 2026-05-06 – SDK stabilization and AQ legacy boundary labeling

**Scope:** docs, tests, SDK, API (no runtime behavior changes intended)

**Changes (already committed this session):**

- Labeled legacy Air Quality boundaries and updated:
  - `docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`
  - `docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`
  - `docs/reviews/AIR_OS_ARCHITECTURE_CHECKPOINT_2026_05_02.md`
  - `specifications/ARCHITECTURE_NOTE.md`
- Added a fast, deterministic AQ legacy pipeline smoke test:
  - `tests/test_air_quality_smoke.py`
- Centralized app descriptor loading via SDK helper:
  - New helper: `urban_platform/sdk/specs_helpers.py`
  - Refactor: `urban_platform/api/app_descriptors.py`, `urban_platform/sdk/apps.py`
  - New tests: `tests/test_sdk_app_descriptor_helper.py`, `tests/test_airos_core_api_apps.py`
- Updated status docs for SDK stabilization:
  - `docs/PROJECT_STATUS.md`
- Drafted adapter descriptor helper design:
  - `docs/ADAPTER_DESCRIPTOR_HELPER_DESIGN.md` (untracked, design-only)

**Verification (latest for this work):**

- `python -m pytest -q`: 385 passed
- `python main.py --step conformance`: 148 checks validated
- `python tools/ai_dev_supervisor/run_review.py --run-conformance`: pass (exit 0)

**Git/GitHub state at end of session:**

- Branch: `main`
- Status: clean working tree except untracked docs/tools (`.agent-loop/`, `docs/ADAPTER_DESCRIPTOR_HELPER_DESIGN.md`, `docs/EXECUTION_TRACKER.md`, `node_modules/`, `package-lock.json`, `package.json`, `tools/agent-loop/`)
- Ahead of `origin/main` by 5 commits (docs + tests + SDK helper).

---

## Purpose

This document tracks implementation progress against the AirOS product-model transition plan. It is the operational control board for contributors and coding agents.

It answers:

- What is the current milestone?
- What has been completed?
- What is in progress?
- What is blocked?
- What should happen next?
- Which commits prove completion?

## Status legend

- **Done**
- **In progress**
- **Not started**
- **Blocked**
- **Deferred**
- **Design-only**
- **Pilot** (implemented + tested, but not production-hardened)

## Current verification baseline

Last updated: **2026-05-06**

- **pytest**: **pass** (`383 passed`)
- **conformance**: **pass** (`148 checks`)
- **supervisor conformance**: **pass** (`exit 0`)
- **latest verified commit**: **`e35f6a8`**

Notes:

- This repo remains **review-oriented** and **not production-secure** (no auth/RBAC/hardening). Do not claim production readiness.
- A clean baseline for this tracker assumes `git status` has no tracked changes; untracked local tooling folders may exist in developer workspaces.

## Milestone overview

| Milestone | Status | Evidence | Next action |
|---|---|---|---|
| Product model and canonical docs | **Done** | `docs/PRODUCT_MODEL.md`, `docs/START_HERE.md`, `docs/PROJECT_STATUS.md` | Keep aligned as architecture evolves |
| Core API pilot runtime | **Pilot** | Records/runs/outputs/receipts/audit + discovery endpoints under `urban_platform/api/` | Maintain; keep safety posture explicit |
| Program Reporting pilot app | **Pilot** | Core API allowlisted run + dashboard API mode + evidence tooling | Maintain; avoid “automation” claims |
| Flood pilot app | **Pilot** | Core API allowlisted run + dashboard API mode + descriptors | Maintain |
| App and adapter descriptors | **Pilot (metadata)** | `specifications/app_descriptors/`, `specifications/provider_adapters/` + discovery via API/CLI/SDK | Maintain; no plugin loading |
| SDK / CLI discovery and governance tools | **Pilot** | `urban_platform/sdk/`, `tools/airos_cli.py`, `tools/ai_dev_supervisor/` | Stabilize SDK surfaces; reduce internal coupling |
| Evidence and store governance | **Pilot** | Evidence + store backup/inspect/verify/dry-run helpers | Maintain; signing remains design-only |
| Docs rationalization | **Done** | Onboarding/canonical docs cleanup commits | Keep consistent; avoid drift in contributor guidance |
| Legacy AQ boundary clarity | **Done** | Playbook + architecture notes label AQ legacy boundaries | Keep “no move until first-class app migration” rule |
| AQ smoke test | **Done (minimal)** | `tests/test_air_quality_smoke.py` | Monitor flakiness; keep bounded |
| SDK stabilization | **In progress** | Recent SDK/API refactors (descriptor loading) | Finish decoupling and document supported SDK imports |
| Physical repo restructuring | **Deferred** | `docs/REPO_RESTRUCTURING_PLAN.md` | Do not start large moves yet |
| Identity & Trust | **Deferred** | Product model / docs only | Future |
| Network Layer | **Deferred** | Product model / docs only | Future |
| Production hardening | **Deferred** | Readiness/checklist docs | Future |

## Completed task ledger (recent)

| Date/order | Task | Commit | Verification | Notes |
|---|---|---|---|---|
| recent | Product model + governance docs consolidation | `0b0a3e8` | green at time of merge | Establishes product boundaries + safety posture |
| recent | Provider adapter descriptors | `5100298` | green at time of merge | Metadata only; not executable plugins |
| recent | Core API discovery and health endpoints | `6023053` | green at time of merge | Enables apps/adapters/catalogs/deployments/inventory discovery |
| recent | SDK expansion (discovery/governance helpers) | `fb55c8c` | green at time of merge | Enables CLI/SDK inventory & inspection |
| recent | CLI discovery and governance commands | `2b550f2` | green at time of merge | Keeps `tools/` entrypoints stable |
| recent | Dashboard runtime trace + API data modes | `6c7d32c` | green at time of merge | Improves review traceability in UI |
| recent | Flood descriptor alignment | `c1c9797` | green at time of merge | Keeps descriptors consistent with pilot flows |
| recent | Readiness store check fix | `ed38ab3` | green at time of merge | Correctness hardening |
| recent | Onboarding / canonical docs rationalization | `46ebb54` | green at time of merge | Improves contributor entry |
| recent | Product model to repository map | `b6b1e61` | green at time of merge | Adds explicit product→repo mapping table |
| recent | Restructuring plan aligned to product model + pilot | `e18499f` | green at time of merge | Phase ordering + governed artifact stability rule |
| recent | Legacy AQ doc labels + watermark historical reviews | `2a5646a` | green at time of merge | Fixes stale `src/` guidance; archives review docs safely |
| recent | Minimal Air Quality legacy pipeline smoke test | `e82bdc8` | green at time of merge | Bounded test; keep reliable |
| recent | Reduce SDK/API coupling (descriptor loading helper) | `e35f6a8` | green at time of merge | Moves toward SDK stabilization |

## Current active track

Current active track: **Execution tracking + guardrails for incremental progress**.

Current next task: **Keep this tracker updated after each merged task (docs-only first, then SDK stabilization).**

Scope:

- docs-only updates to the tracker and contributor guidance
- no runtime feature work unless explicitly scoped and verified

Non-goals:

- no code deletion
- no Air Quality refactor
- no repo moves
- no schema changes

## Next three tasks (exactly three)

1. **Add legacy Air Quality documentation labels.**
2. **Add a fast AQ pipeline smoke test, only if reliable.**
3. **Decouple SDK app descriptor loading from API module.**

## Deferred work

- Physical repo migration (moves) beyond compatibility wrappers
- Deleting legacy AQ modules
- Removing Program Reporting fallbacks
- Actual store restore (beyond restore-dry-run)
- Digital signatures for evidence bundles
- Identity & Trust implementation (auth/RBAC/keys/policies)
- Network Layer implementation (cross-node runtime messaging)
- Production deployment hardening (DB store, monitoring, runbooks, security review)

## Update rule for Cursor

After every task, Cursor (or any coding agent) must update this file with:

- task status (milestones + ledger row)
- commit hash (if committed)
- verification results (pytest + conformance + supervisor conformance)
- next task (single sentence)

Cursor must **not** mark a milestone **Done** unless:

- tests pass
- conformance passes
- supervisor conformance passes
- relevant smoke checks pass (if required by that milestone)
- a commit exists (or the user explicitly requested no commit)

