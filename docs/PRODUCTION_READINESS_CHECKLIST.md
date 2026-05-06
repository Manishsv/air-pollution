Before beta / production readiness:
- Participant / AirOS node directory
- Agency/node identity model
- Public key or certificate references
- Signed envelopes and payload hashes
- Data-sharing policy enforcement
- API authentication / authorization
- Reference catalog pull/cache/expiry
- Program spec pull/adoption/versioning
- Audit log persistence
- Secrets management

See also: [`docs/SIGNED_EVIDENCE_BUNDLES_DESIGN.md`](SIGNED_EVIDENCE_BUNDLES_DESIGN.md) (future direction; signing not implemented in pilot runtime).

See also: [`docs/PILOT_STORE_LIFECYCLE.md`](PILOT_STORE_LIFECYCLE.md) (design-only: backup/export/import/compaction/retention and migration path).

See also: [`docs/PILOT_STORE_RESTORE_DESIGN.md`](PILOT_STORE_RESTORE_DESIGN.md) (design-only: restore modes, safety checks, and policy requirements; actual restore not implemented).