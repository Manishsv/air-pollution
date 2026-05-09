# Signed Evidence Bundles Design

## Purpose

Today, AirOS evidence bundle **verification checks internal consistency only** (files exist, JSON parses, counts/hashes/links match). This is useful for review and debugging, but it does not provide cryptographic integrity or signer identity checks.

Future **signed evidence bundles** would add cryptographic mechanisms to help answer:

- **Who created this bundle?**
- **Has the bundle changed since signing?**
- **Which AirOS node or agency signed it?**
- **Which key/certificate was used?**
- **What trust policy was applied when verifying?**

Signed bundles still do **not** automatically approve or authorize government action. They remain evidence for review and audit support.

## Current state (what exists today)

Current evidence workflow:

- export (bundle creation)
- inspect (offline summary)
- verify internal consistency (offline checks)
- redact (sharing copy)

Current verification checks:

- required files exist
- JSON parsing
- manifest counts
- file hashes via `hash_manifest.json` when present (integrity support only; not a signature)
- payload hashes (where present)
- run/output/receipt/audit internal consistency where possible
- safety notes present (review / non-approval language)

Current verification does **not** check:

- signer identity
- key/certificate validity
- participant directory membership
- revocation status
- legal authorization
- policy authorization
- official approval

## Future signing model (conceptual)

Signed bundles would introduce additional bundle artifacts, for example:

- `signature.json`: signature material (algorithm, signature bytes, signed-at timestamp, signing scope)
- `signer_metadata.json`: signer identity references (node id / agency id, key id, certificate ref)
- `trust_policy.json` (or `trust_policy_ref`): policy used by a verifier to decide “trust / don’t trust”
- `signing_manifest.json`: file hash manifest + metadata that is actually signed

### Signature scope options

Typical signature scope options:

- sign `manifest.json` (simple, but incomplete)
- sign **hashes of every included file** (recommended baseline)
- include a bundle hash (hash of hash-manifest)
- include `created_at` + `signed_at`
- include `signer_node_id`
- include `key_id` or certificate reference

The recommended baseline is: **sign a canonical file-hash manifest** over all included bundle files.

## Signing sequence (future)

Proposed future sequence:

1. Generate evidence bundle.
2. Optionally redact (for sharing copies).
3. Verify internal consistency (local).
4. Generate a canonical file-hash manifest for all bundle members.
5. Sign the hash manifest using a node signing key.
6. Add signature + signer metadata + policy reference to the bundle.
7. Verify signature against a trusted participant directory and trust policy.

## Verification sequence (future)

Future signed verification should check:

- internal consistency (today’s checks)
- file hashes match the signed hash manifest
- signature validity over the hash manifest
- signer identity resolves in the participant directory
- key/certificate status (validity period, rotation, revocation)
- trust policy match (who is trusted to sign what)
- authorization rules for the relevant context (deployment policy, disclosure policy)

## Identity & Trust dependency (not implemented today)

Signing requires an **Identity & Trust** subsystem, including:

- participant directory (nodes/agencies/users/services)
- stable node ids and agency ids
- public keys / certificates (and how they are referenced)
- key rotation procedures
- revocation mechanisms
- trust policies (who can sign which bundle types)
- signing authority rules (node vs agency vs user vs service)

These capabilities are not implemented in the current pilot runtime.

## Network Layer dependency (not implemented today)

Signed bundles may be exchanged across AirOS nodes via the future Network Layer:

- message envelopes with schema references
- routing and delivery receipts
- replay protection
- correlation ids
- policy-enforced transport adapters

This is not implemented today.

## Redaction and signing order

Recommended ordering:

- **External sharing**: redact first, then sign the **redacted** bundle.
- **Internal audit**: sign the original bundle; if a redacted copy is later created, sign the redacted copy **separately**.

A redacted bundle must not claim to preserve original payload hashes unless it includes an explicit mapping (e.g., `original_payload_hash` and `redacted_payload_hash`).

## What signatures do and do not mean

Signatures can mean:

- the bundle came from a holder of a private key
- the signed files have not changed since signing
- signer identity can be checked against a trust directory (when implemented)

Signatures do **not** mean:

- the data is true
- outputs are approved
- proposed actions are authorized
- a legal decision has been made
- an agency has accepted liability
- public disclosure is allowed

## Safety posture

Signed or unsigned, AirOS evidence bundles support review and audit. They do **not** authorize fund release, penalties, emergency orders, demolitions, blacklisting, public disclosure, or final government decisions.

## Future implementation phases (direction only)

**Phase 1:**
- hash manifest only (no signing)
- improve internal consistency verification

**Phase 2:**
- local development signing with test keys
- clearly marked non-production

**Phase 3:**
- participant directory integration
- key/certificate verification
- revocation checks

**Phase 4:**
- policy-based verification
- cross-node exchange
- audit-grade evidence workflows

## Open questions

- Who is allowed to sign (AirOS node, agency, user, service account)?
- Should signatures be per bundle, per file, or per output?
- How are keys rotated and stored?
- How is revocation checked in offline verification?
- How are redacted bundles represented and linked to originals (if at all)?
- What is the legal meaning of a signature in each deployment context?
- What retention and disclosure policies apply?

