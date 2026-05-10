# AirOS Next Implementation Backlog

## Purpose

This document converts [`docs/PROJECT_STATUS.md`](PROJECT_STATUS.md) into a short execution backlog. The intent is to **avoid too many parallel feature tracks**, keep safety posture consistent, and make it obvious what to do next (and what not to do yet).

## Current recommendation

**Primary next implementation track: finish evidence/store governance (pilot).**

Why:

- The repo already has a coherent pilot lifecycle (backup → inspect → verify → restore-dry-run; evidence export → inspect → verify → redact).
- This track improves integrity, operator confidence, and review/governance posture without expanding into risky areas (actual restore, signing, trust).
- It keeps new work focused on **read-only verification, safety checks, and clarity** rather than new execution surfaces.

## Priority 0: Stabilization (always on)

1. **Keep verification green**
   - Acceptance: `pytest`, conformance, and supervisor review pass on main.
   - Verification:
     - `python -m pytest -q`
     - `python main.py --step conformance`
     - `python tools/ai_dev_supervisor/run_review.py --run-conformance`
   - Non-goals: no new feature scope.

2. **Keep project status truthful**
   - Acceptance: `docs/PROJECT_STATUS.md` matches actual repo state after every meaningful change.
   - Likely files: `docs/PROJECT_STATUS.md`, `docs/START_HERE.md`, `README.md`
   - Non-goals: no aspirational “implemented” claims.

3. **Remove stale doc language**
   - Acceptance: store lifecycle docs do not claim “not implemented” for implemented pilot tools (and vice versa).
   - Likely files: `docs/PILOT_STORE_LIFECYCLE.md`, `docs/EVIDENCE_BUNDLES.md`, `docs/DEVELOPER_GUIDE.md`

## Priority 1: Finish the selected track (evidence/store governance)

### Task 1: Standardize integrity wording across evidence + store tools (Done)

Why:
Reviewers and operators must see consistent language: hashes/verification are **internal consistency only**, not signatures/approvals/certification.

Likely files:
- `urban_platform/sdk/evidence.py`
- `urban_platform/sdk/store_backup.py`
- `tools/airos_cli.py`
- `docs/EVIDENCE_BUNDLES.md`
- `docs/PILOT_STORE_LIFECYCLE.md`

Acceptance criteria:
- CLI outputs consistently include “not a digital signature” and “not approval/certification”.
- Docs use consistent phrases for evidence vs store backups.
- No claims of production recoverability.

Verification:
- `python -m pytest -q`
- `python main.py --step conformance`
- `python tools/ai_dev_supervisor/run_review.py --run-conformance`

Non-goals:
- no actual restore implementation
- no signing

### Task 2: Tighten backup/restore collision policy (dry-run only) (Done)

Why:
Dry-run should clearly surface collision risks (existing files, overwrite risks) in a predictable way.

Likely files:
- `urban_platform/sdk/store_backup.py`
- `tools/airos_cli.py`
- `tests/test_airos_sdk_store_restore_dry_run.py`
- `tests/test_airos_cli_store_restore_dry_run.py`

Acceptance criteria:
- Dry-run clearly reports: `target_exists`, existing store members found, and whether overwrite would occur.
- Output includes explicit no-write language.

Verification:
- `python -m pytest -q`

Non-goals:
- no writes to target directories

### Task 3: Add explicit “redacted artifacts are not restorable stores” guardrails (docs + warnings)

Why:
Prevent accidental misuse where reviewers treat redacted evidence artifacts as restorable runtime stores.

Likely files:
- `docs/EVIDENCE_BUNDLES.md`
- `docs/PILOT_STORE_RESTORE_DESIGN.md`
- `docs/PILOT_STORE_LIFECYCLE.md`

Acceptance criteria:
- Docs explicitly state: evidence bundles are not store backups; redacted evidence bundles must never be restored as stores.
- (Optional) CLI warnings in store commands when filenames imply “redacted”.

Verification:
- `python -m pytest -q`

Non-goals:
- no enforcement via runtime policy; messaging only unless already supported

### Task 4: Add “operator checklist” section to lifecycle docs (pilot)

Why:
Operators need a copy/pasteable, low-risk flow to follow.

Likely files:
- `docs/PILOT_STORE_LIFECYCLE.md`
- `docs/DEVELOPER_GUIDE.md`

Acceptance criteria:
- A short checklist shows: backup → inspect → verify → restore-dry-run.
- Includes explicit non-goals: no restore, no import, no approval.

Verification:
- `python -m pytest -q`

Non-goals:
- no new commands

## Priority 2: Secondary cleanup (useful, not urgent)

1. **CLI output consistency pass**
   - Align headings and final “read-only” safety footer across evidence/store commands.
   - Files: `tools/airos_cli.py`, CLI tests.

2. **Docs deduplication**
   - Reduce repeated command blocks in multiple docs by linking to a single canonical section.
   - Files: `docs/DEVELOPER_GUIDE.md`, `docs/START_HERE.md`, `docs/CORE_API_PILOT.md`.

3. **Add a small “known limitations” block to Core API docs**
   - Make pagination/backward-compat behavior obvious and discourage unbounded list calls.
   - Files: `docs/CORE_API_PILOT.md`.

4. **Add link integrity smoke test (optional)**
   - Lightweight test that key docs referenced from README exist.
   - Non-goal: no network, no external link checks.

## Priority 3: Later / do not start yet

Explicitly defer until the Priority 1 track is complete and `PROJECT_STATUS` is updated:

- **Actual store restore** (writes files)
- **Any repo folder moves / migration refactors**
- **Digital signatures / key management / certificates**
- **Identity & Trust implementation**
- **Network Layer implementation**
- **Production deployment hardening** (monitoring, secrets, scaling)
- **Dynamic plugin loading**
- **Installing/running apps from packaged zips**

## Decision rule

Do not start a new product area until the selected **Priority 1** track is complete **and** `docs/PROJECT_STATUS.md` is updated to reflect the new repo state.

## Standard verification

Every implementation task must end with:

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance
```

