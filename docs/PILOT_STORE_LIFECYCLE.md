# AirOS Pilot Store Lifecycle

## Purpose

AirOS pilot runtime currently uses **`FileAirOsStore`**: a local, file-backed store designed for **development, demos, and small pilots**.

It is **not production-secure** or production-scale in this repository configuration (no RBAC, no encryption at rest, no HA/replication). Store lifecycle operations must remain **review-support only** and must not imply approval or authorization.

`FileAirOsStore` persists runtime objects in **append-only JSONL** files under a store directory (Core API uses `AIROS_STORE_DIR`, default `data/store/api`).

This document defines a **lifecycle model** (backup, export, import, compaction, retention, migration path). Some pieces are implemented in pilot form (backup/inspect/verify/dry-run); others remain future design direction.

## Current store files

A pilot store directory contains:

- **`records.jsonl`**: persisted **inputs** accepted by the runtime (contract-keyed payloads), including timestamps and metadata.
- **`outputs.jsonl`**: persisted **review outputs** produced by allowlisted builders (dashboards, packets, tasks) with metadata and timestamps.
- **`runs.jsonl`**: **run metadata** summarizing what application ran, when, status, counts, and input/output references.
- **`validation_receipts.jsonl`**: schema validation receipts for records and outputs (valid/invalid + error details).
- **`audit_events.jsonl`**: append-only audit trail of actions (ingest, run start/complete, output generated, rejections).

Each file is line-delimited JSON (one object per line).

## Current guarantees

The pilot store aims for the following properties:

- **Append-only writes**: new entries are appended rather than edited in-place.
- **Local readability**: files can be inspected with standard tools (text editors, `jq`) for debugging and review.
- **Deterministic payload hashes (where available)**: payload hashes are used for traceability and tamper detection at the payload level (not a signature).
- **Latest-write-wins for some objects**: for ids that can repeat (e.g., a `run_id` written multiple times as status evolves), the effective “current” view is **the latest entry for that id**.
- **Evidence export support**: the store can be summarized into **evidence bundles** (portable run/deployment evidence) without executing builders.

## Current limitations

`FileAirOsStore` is intentionally simple and therefore has important limitations:

- **No transaction isolation** (multi-file updates can be partially written if interrupted).
- **No concurrent multi-writer guarantee** (not safe for many writers without coordination).
- **No database indexes** (list queries scale linearly with file size).
- **No built-in retention policy** (data grows until manually managed).
- **No compaction command yet** (old superseded entries remain in JSONL).
- **No production-grade backup system** (pilot backup exists; no restore yet).
- **No restore/import command yet** (no defined safety gates for importing stores).
- **No encryption at rest** (data is plaintext on disk).
- **No authentication/RBAC** at the store layer in this repo.
- **No HA/replication** model (single-node, local-first).

## Backup model (pilot, implemented)

AirOS includes a **pilot** backup command that creates an operationally safe snapshot of a store directory:

```bash
python tools/airos_cli.py store backup --store-dir data/store/api --output-dir data/backups
```

A backup can be inspected offline (without restoring or importing):

```bash
python tools/airos_cli.py store inspect-backup data/backups/<backup>.zip
```

A backup can be verified offline (hashes + internal consistency; no restore/import):

```bash
python tools/airos_cli.py store verify-backup data/backups/<backup>.zip
```

Backup verification checks internal consistency and file hashes only. It is **not** a digital signature, approval, or certification.

Dry-run restore checks (no writes):

```bash
python tools/airos_cli.py store restore-dry-run data/backups/<backup>.zip --target-dir /tmp/airos_restore_candidate
```

Actual restore is future work. See [`docs/PILOT_STORE_RESTORE_DESIGN.md`](PILOT_STORE_RESTORE_DESIGN.md) for the restore model and safety requirements.

A backup:

- copy all JSONL files (`records.jsonl`, `outputs.jsonl`, `runs.jsonl`, `validation_receipts.jsonl`, `audit_events.jsonl`)
- include a **`store_manifest.json`** with:
  - `created_at`
  - store version (if/when introduced)
  - file list + sizes + counts
  - file hashes (e.g., SHA-256) for integrity checks
  - a safety note: “backup is operational only; not approval or attestation”
- include **safety notes** reiterating review-only posture
- be read-only with respect to the store (no mutation)

Backups are for **operator recovery** (e.g., “I need to restore a pilot environment”), not for public sharing.

## Export/import model (future)

Future direction: a safe way to **export** a store snapshot and **import** into another local pilot environment.

Key design points:

- **Export** produces a portable archive (e.g., `.zip` or directory) containing JSONL files + `store_manifest.json` + file hashes.
- **Import**:
  - validates file hashes before import
  - validates JSON parseability and basic required fields per object type
  - preserves **audit events**
  - never executes builders during import
  - treats imported data as **untrusted until reviewed** (source, provenance, and policy must be checked outside the import tool)

Import should be explicit about scope (e.g., “replace store” vs “merge into store”), and “merge” semantics must be defined carefully to avoid silent overwrites.

## Compaction model (future)

Compaction becomes important because append-only JSONL files will grow over time, especially when ids repeat.

Why compaction is needed:

- repeated ids (e.g., runs updated from `started` → `completed`) leave superseded entries behind
- long-lived pilots accumulate large audit/event histories
- list endpoints are linear scans; smaller files improve performance

Compaction should:

- be explicit and operator-triggered (never automatic)
- create a backup before replacing files
- produce a new snapshot directory (or archive) and only swap into place when complete
- preserve object meaning and linkage (records ↔ runs ↔ outputs ↔ receipts ↔ audits)
- preserve audit events unless explicitly archived by policy
- write a **`compaction_report.json`** including:
  - input and output file hashes
  - before/after counts
  - “latest-write-wins” resolution summary (how many duplicates collapsed)
  - safety note: “compaction does not approve or alter outcomes”

Compaction must not change contract payloads or reinterpret domain meaning; it only rewrites storage layout.

## Retention model (future)

Retention policies should be deployment-scoped and governed (policy + authorization), not ad-hoc deletes.

Design considerations:

- keep **audit events** longer than transient runtime objects if policy requires
- retain **evidence bundles** separately (they are portable review artifacts)
- support deployment-specific retention windows (e.g., demo vs pilot vs internal review)
- never delete review evidence without an explicit authorized policy

## Migration path to SQLite/PostgreSQL

Staged migration path (conceptual):

- **Phase 1 (today)**: `FileAirOsStore` + evidence bundles + integrity checks + health/readiness + pagination.
- **Phase 2 (future)**: SQLite-backed store for stronger local indexing and single-node pilots.
- **Phase 3 (future)**: PostgreSQL-backed store for multi-user/beta deployments.
- **Phase 4 (future)**: managed production store with backup/retention/monitoring, RBAC, and policy enforcement.

The goal is to preserve:

- canonical platform objects and contracts
- auditability and validation receipts
- review-support posture (no automated authorization)

## Relationship to evidence bundles

- **Evidence bundles** are **portable evidence** for a run or deployment (export → inspect → verify → redact). They are designed for review/debug/audit support and safe sharing (with redaction).
- A **store backup** is an **operational backup** of the entire store directory for recovery and migration.
- An evidence bundle is **not** a full store backup.
- A store backup is **not** a decision approval, attestation, or signature.

## Safety posture

Store lifecycle operations (backup/export/import/compaction/retention) must not authorize or automate:

- fund release
- penalties / recovery
- emergency orders / evacuations
- blacklisting
- public disclosure without authorization
- any final government decision

## Open questions

- What is the retention policy per deployment (demo vs pilot vs internal review)?
- Who is allowed to export or import a store (operator roles, approvals)?
- Should audit events be immutable, append-only forever, or policy-archivable?
- Should records be encrypted at rest in pilots, and what is the key management model?
- How should compaction interact with evidence bundles (e.g., compaction artifacts referenced by bundles)?
- What metadata should be required before importing a store (source, contact, policy basis, data classification)?
- How should backups/snapshots be signed in the future (identity & trust integration) without implying legal attestation?

