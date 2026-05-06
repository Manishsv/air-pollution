# AirOS Evidence Bundles

## Purpose

An **evidence bundle** is a portable package of runtime evidence for a **pilot-runtime** run or deployment. It helps reviewers understand:

- what data came into AirOS (records)
- what schema validation happened (validation receipts)
- what allowlisted decision logic executed (runs)
- what review outputs were produced (outputs)
- what trace events were recorded (audit events)

Evidence bundles are useful for **review**, **debugging**, **demos**, and **governance discussions**.

**Evidence bundles are not:**

- an approval
- a certification
- a signature / cryptographic trust proof
- a legal attestation
- a final government decision

For future signed bundle design (not implemented), see [`docs/SIGNED_EVIDENCE_BUNDLES_DESIGN.md`](SIGNED_EVIDENCE_BUNDLES_DESIGN.md).

## What an evidence bundle contains

An exported bundle zip contains:

- **`README.md`**: human overview of what the bundle includes and how to inspect it
- **`manifest.json`**: bundle metadata (bundle id, creation time, selector run/deployment id, counts) and a safety note
- **`hash_manifest.json`**: SHA-256 hashes for each included bundle file (integrity support only; not a signature)
- **`runs.json`**: run metadata (what application ran, when, status, counts)
- **`records.json`**: ingested records (contract-shaped inputs stored by the pilot runtime)
- **`outputs.json`**: generated outputs (contract-shaped review payloads stored by the pilot runtime)
- **`validation_receipts.json`**: schema validation receipts for records and outputs
- **`audit_events.json`**: audit trail events recorded during ingestion and execution
- **`safety_notes.md`**: explicit safety posture (review support only; no automation/authorization)

## Runtime evidence model (plain language)

### Records
**Records** are what came into AirOS (ingested inputs). They are stored after (or alongside) schema validation.

### Validation receipts
**Validation receipts** record whether a payload **passed or failed schema validation** against a contract.

They help answer: “Did this payload match the agreed shape?”

They do **not** mean:

- the payload is true or complete
- a department audited it
- financial approval occurred
- legal acceptance occurred

### Runs
**Runs** record what allowlisted application logic executed (application id, deployment id, status, timestamps, counts).

Runs are traceability evidence. They are not approvals.

### Outputs
**Outputs** are the review payloads produced by a run (dashboards, packets, tasks, summaries). Outputs should contain warnings, provenance, and `blocked_uses` to prevent unsafe interpretation.

### Audit events
**Audit events** record operational trace events (ingested, rejected, run started, output generated, run completed, etc.).

Audit events provide traceability, not authority.

## Evidence workflow (export → inspect → verify)

1) Run an AirOS app through the Core API or deployment runner (pilot workflows).

2) Export evidence (read-only):

```bash
python tools/airos_cli.py evidence export \
  --run-id <run_id> \
  --store-dir data/store/api \
  --output-dir data/outputs/evidence
```

3) Inspect evidence offline (read-only):

```bash
python tools/airos_cli.py evidence inspect data/outputs/evidence/<bundle>.zip
```

4) Verify internal consistency offline (read-only):

```bash
python tools/airos_cli.py evidence verify data/outputs/evidence/<bundle>.zip
```

## Redaction (sharing copies)

Before sharing evidence bundles more widely, create a **redacted copy**. Redaction removes or masks sensitive fields while preserving structure and traceability.

Example (public demo sharing copy):

```bash
python tools/airos_cli.py evidence redact data/outputs/evidence/<bundle>.zip \
  --profile public_demo \
  --output-dir data/outputs/evidence
```

Then inspect/verify the redacted bundle:

```bash
python tools/airos_cli.py evidence inspect data/outputs/evidence/<bundle>.public_demo.redacted.zip
python tools/airos_cli.py evidence verify data/outputs/evidence/<bundle>.public_demo.redacted.zip
```

Redaction is a **pilot profile** feature. It does not approve, certify, sign, execute, import, or publish anything.

## What `verify` checks

Verification checks **internal consistency** only:

- required files exist in the bundle
- JSON files parse
- manifest counts match the included file contents
- file hashes match `hash_manifest.json` when present (integrity check; not a signature)
- payload hashes match where the bundle includes `payload_hash`
- run/output references are consistent where possible
- validation receipts reference known records/outputs where possible
- audit events can be related to known ids where possible
- `safety_notes.md` is present and contains review / non-approval safety wording

Verification (including file-hash checks via `hash_manifest.json`) is **not** a digital signature, approval, or certification.

## What `verify` does not check

Verification does **not**:

- check cryptographic signatures
- prove the source agency identity
- prove legal authorization
- certify official truth
- approve any action
- execute decision logic again
- import records into a store
- publish data

**Important:** Verification is **not** certification. It is a local consistency check to detect missing files, mismatched counts, and obvious tampering (e.g., hash mismatches when hashes are present).

## Validation receipts versus approvals

A **validation receipt** means a payload passed/failed **contract/schema validation**. It does not mean the payload is correct, complete, authorized, or approved.

Treat receipts as “shape checks,” not “decision checks.”

## Evidence bundles and human review

Evidence bundles support human review by packaging:

- inputs (records)
- validation results (receipts)
- runtime trace (runs + audit events)
- review outputs and proposed actions (outputs)
- warnings and blocked uses

Final decisions remain with authorized human and institutional processes.

## Current limitations (pilot runtime)

- File-backed pilot store (`FileAirOsStore`)
- No cryptographic signing yet
- No participant directory / certificate trust yet
- No RBAC/auth in pilot runtime
- No legal attestation workflow
- No production retention policy
- No external “source of truth” verification
- Not production-ready

## Future work (direction, not implemented here)

- Signed evidence bundles
- Participant identity and key verification
- Policy-controlled disclosure and redaction profiles
- Immutable audit backend
- Retention policy and deletion governance
- Reviewer sign-off workflow
- Integration with case/workflow systems

## Safety posture

AirOS proposes review outputs and proposed actions. It does **not** authorize fund release, penalties, emergency orders, demolitions, blacklisting, public disclosure, or final government decisions.

