# AirOS Project Status

## Current framing

AirOS is a **Decision Support Operating System for urban governance**.

Core flow:

Data sources  
→ Provider adapters  
→ Validated AirOS records  
→ Decision logic  
→ Review outputs  
→ Proposed actions  
→ Authorized human decision  
→ Audit trail, validation receipts, and run metadata

AirOS supports **review**. It does **not** authorize or automate final government decisions.

## Status legend

- **Done**: implemented and tested in this repo.
- **Pilot**: works for local/demo/pilot use, but not production-ready.
- **In progress**: partially implemented or actively being wired.
- **Design-only**: documented direction; no runtime implementation yet.
- **Future**: not implemented.
- **Not implemented**: explicitly not present in the repo yet (or only referenced in plans).

## Capability status table

| Area | Status | What exists now | What remains |
|---|---|---|---|
| Product model | Done | `docs/PRODUCT_MODEL.md` (Decision Support OS framing; safety posture) | Keep docs aligned as architecture evolves |
| Generic Core API | Pilot | Health (`/health`, `/health/live`, `/health/ready`), manifest, contracts, records, allowlisted runs, runs/outputs/validation receipts/audit events, apps/adapters/catalogs/deployments/inventory discovery, pagination/filtering | Auth/RBAC, production hardening, database-backed store, operational runbooks |
| Program Reporting app | Pilot (end-to-end demo) | City submissions → review packets + state summary; dashboard API mode; evidence and store lifecycle support | Real finance integration, authorized workflows, production data governance |
| Flood app | Pilot | Multi-input Core API flow; flood outputs, decision packets, field verification tasks; dashboard API mode | Real sensors/providers, operational workflow integration, production governance |
| App descriptors | Done (metadata) | Schema + `program_reporting_review` and `flood_risk_review` descriptors; discovery via API/CLI/SDK | Catalog governance, signing, install/register workflow (future) |
| Provider adapter descriptors | Pilot (metadata) | Schema + 3 adapter descriptors; discovery via API/CLI/SDK | More adapters, runtime integration policy, connector certification |
| Reference catalogs | Pilot (local examples) | Schema + 3 local reference catalog examples; discovery via API/CLI/SDK | Pull/cache/TTL, publication workflow, signatures + trust policy (future) |
| SDK | Pilot (emerging) | Contracts/apps/adapters/catalogs/deployments/inventory; evidence + store backup/inspect/verify/dry-run helpers | Stable public API surface, packaging/versioning policy |
| Studio / CLI | Pilot (emerging) | `doctor`, `conformance`, `inventory`, `health`; discovery; app scaffold/validate/package/inspect-package; local catalog; evidence; store tools | UX polish, command stability guarantees, release packaging |
| App Catalog | Pilot (metadata-only) | Local catalog index for packaged apps | Trusted catalog, publisher identity, install/register/review workflow |
| Evidence bundles | Pilot | Export/inspect/verify, redaction, hash manifest support | Signatures + trust model (design-only); redaction policy maturity |
| Pilot store lifecycle | Pilot (design-backed) | `FileAirOsStore`; backup/inspect/verify; restore-dry-run; lifecycle + restore design docs | Actual restore (not implemented), compaction (future), retention policy enforcement, SQLite/PostgreSQL migration |
| Dashboard | Pilot | Review dashboard; Program Reporting + Flood API modes; Runtime Trace panel | Role-aware views, production UX, deeper cross-app cohesion |
| Docker / Compose | Pilot | Single-image Docker + Compose pilot-runtime profile | Production deployment hardening, monitoring, secrets, scaling |
| Repo restructuring | Design-only / skeleton | `docs/REPO_RESTRUCTURING_PLAN.md` + namespace skeleton | Gradual moves with compatibility wrappers; keep conformance green |
| Identity & Trust | Future / design direction | Product model framing | Participants/users/orgs/roles/keys/policies/RBAC |
| Network Layer | Future / design direction | Product model framing | Routing, delivery receipts, retries, replay protection, cross-node exchange |
| Production readiness | Future | `docs/PRODUCTION_READINESS_CHECKLIST.md` + design docs | Auth/RBAC, DB store, monitoring, privacy/security review, operational runbooks, backup/restore maturity |

## What is safe to demo now

Pilot-safe demo paths (using demo/pilot data unless explicitly configured otherwise):

- CLI deployment demos (`deployments/examples/*`)
- Generic Core API pilot runtime (records → allowlisted runs → outputs)
- Program Reporting review flow (pilot)
- Flood review flow (pilot)
- Dashboard file mode and API modes (as applicable)
- Evidence bundle export → inspect → verify (pilot governance support)
- Store backup → inspect-backup → verify-backup → restore-dry-run (pilot operational support; no restore)
- Docker Compose pilot-runtime profile

## What must not be claimed

AirOS must not be presented as:

- production-ready or production-secure
- legally binding approval or attestation
- automated fund release
- automated emergency orders/evacuations
- automated enforcement/penalty/recovery
- authorization for public disclosure
- a trusted cross-agency network (not implemented)
- signed evidence attestation (design-only; signing not implemented)

## Recommended next work (near-term)

1. Close any remaining gaps in discovery endpoints and CLI/SDK parity (apps/adapters/catalogs/deployments/inventory).
2. Continue dashboard API-mode consolidation and reviewer UX hardening (without moving domain logic into Streamlit).
3. Keep evidence/store integrity tooling aligned (hash manifests, redaction, backup verification, dry-run collision checks).
4. Keep tutorials and docs current for app/adaptor developers.
5. Only begin deeper repo migration after discovery + SDK/CLI ergonomics stabilize and compatibility paths are clear.
6. Design Identity & Trust before signed artifacts or cross-node networking.

## Implementation gap summary

Area | Implemented? | Tests? | Docs? | Next action
---|---|---|---|---
Core API discovery + runtime surfaces | Yes (pilot) | Yes | Yes | Keep route docs aligned; add auth/RBAC only after trust model
CLI/SDK developer workflow | Yes (pilot) | Yes | Yes | Stabilize CLI surface and SDK exports; tighten wording + help output
Evidence + store governance tooling | Yes (pilot) | Yes | Yes | Keep integrity checks aligned; defer signing to trust model
Dashboard API/runtime trace | Yes (pilot) | Yes | Yes | Continue UX hardening; keep Streamlit presentation-only
Actual store restore | No | N/A | Yes (design) | Implement empty-dir restore only after policy + acknowledgements are defined
Identity & Trust | No | N/A | Partial (product model) | Produce specs-first contracts before any signing/RBAC claims
Network Layer | No | N/A | Partial (product model) | Produce contracts/envelopes specs before implementation

## Recommended next implementation track

**Finish evidence/store governance (pilot)**: focus on aligning and hardening the existing integrity and lifecycle tools (backup → inspect → verify → restore-dry-run) and documentation, while keeping actual restore and signing gated behind explicit policy + identity/trust design.

Recent: integrity wording was standardized across evidence and store verification surfaces (CLI + docs) so hashes/verification are consistently described as internal-consistency-only (not signatures/approval/certification).

## How to verify current repo health

From repo root:

```bash
python -m pytest -q
python main.py --step conformance
python tools/ai_dev_supervisor/run_review.py --run-conformance

python tools/airos_cli.py doctor
python tools/airos_cli.py inventory
```

See also:

- [`docs/NEXT_IMPLEMENTATION_BACKLOG.md`](NEXT_IMPLEMENTATION_BACKLOG.md)

