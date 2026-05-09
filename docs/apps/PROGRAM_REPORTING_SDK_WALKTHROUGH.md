# Program Reporting SDK Walkthrough

This guide shows how to use the documented AirOS SDK surface to understand the
Program Reporting pilot app from the outside — what goes in, what comes out, what
safety gates apply — without running the Core API, executing application logic, or
mutating any stored state.

All SDK calls below use only symbols from `urban_platform.sdk.__all__` (the
canonical public surface documented in [`docs/SDK_SURFACE.md`](SDK_SURFACE.md)).

---

## Prerequisites

```bash
# From the repository root
pip install -e .          # or: pip install -r requirements.txt
python -c "from urban_platform.sdk import get_platform_inventory; print('ok')"
```

No API keys, no running server, and no `data/` artifacts are required. Every call
in this walkthrough reads static files from `specifications/` and `deployments/`.

---

## 1. Platform inventory — what is registered?

```python
from urban_platform.sdk import get_platform_inventory

inventory = get_platform_inventory()

print(f"Contracts : {inventory['contracts']['contract_count']}")
print(f"Apps      : {inventory['apps']['app_count']}")
print(f"Adapters  : {inventory['adapters']['adapter_count']}")
print(f"Catalogs  : {inventory['catalogs']['catalog_count']}")
print(f"Deployments: {inventory['deployments']['deployment_count']}")
```

**What this tells you:** how many contracts, apps, adapters, reference catalogs,
and deployment profiles are registered in the current repository state. For Program
Reporting specifically, you will see one app (`program_reporting_review`) and the
relevant contracts in the contract list.

---

## 2. Program Reporting app descriptor

```python
from urban_platform.sdk import list_app_ids, list_app_descriptors

# See all registered app IDs
print(list_app_ids())
# → ['flood_risk_review', 'program_reporting_review']

# Get all descriptors (returns list of dicts, one per app)
descriptors = list_app_descriptors()
pr = next(d for d in descriptors if d["app_id"] == "program_reporting_review")

print(pr["name"])            # Program Reporting Review
print(pr["status"])          # draft_demo
print(pr["input_contracts"]) # ['consumer_city_program_submission']
print(pr["output_contracts"])
# ['consumer_fund_release_review_packet', 'consumer_program_reporting_state_summary']
```

**Key things the descriptor tells you:**

| Field | Value | Meaning |
|---|---|---|
| `app_type` | `review_support` | Produces review packets for humans; does not take autonomous action |
| `execution_model` | `allowlisted_python_builder` | Only explicitly listed Python builders may run |
| `safety.review_support_only` | `true` | Platform-enforced safety gate |
| `safety.human_review_required` | `true` | Every output requires human sign-off |
| `safety.blocked_uses` | see below | Uses the platform actively prevents |

**Blocked uses (from the descriptor):**

- `automatic_fund_release`
- `automatic_penalty_or_recovery`
- `blacklisting_without_authorized_review`
- `public_disclosure_without_authorization`

These are not advisory — they are written into the output contract and checked by
the conformance engine.

---

## 3. Contracts — what goes in, what comes out?

### 3a. List contracts relevant to Program Reporting

```python
from urban_platform.sdk import list_contract_keys, contract_exists

all_keys = list_contract_keys()
pr_keys = [k for k in all_keys if "program" in k or "fund" in k or "submission" in k]
print(pr_keys)
# ['consumer_city_program_submission',
#  'consumer_fund_release_review_packet',
#  'consumer_program_reporting_state_summary',
#  'registry_program_spec_registry_v1']
```

### 3b. Inspect the input contract

```python
from urban_platform.sdk import get_contract_schema

schema = get_contract_schema("consumer_city_program_submission")
print(schema["title"])
# Consumer contract: city program submission (v1, Phase 1)

print(schema["description"])
# Phase 1: self-reported program progress and financial utilization...

print(schema["required"])
# ['submission_id', 'city_id', 'program_id', 'program_spec_version',
#  'reporting_period', 'submitted_at', 'reporting_officer_role',
#  'program_progress', 'financial_progress', 'self_reported_issues',
#  'provenance_summary', 'warnings', 'blocked_uses',
#  'human_review_required', 'reference_data_versions']
```

A city submission **must** include `blocked_uses` and `human_review_required` in
the payload itself — not just as platform metadata. This means every submitting
city explicitly acknowledges the governance posture in the data it sends.

### 3c. Inspect the output contract

```python
schema = get_contract_schema("consumer_fund_release_review_packet")
print(schema["title"])
# Consumer contract: fund release review packet (v1)

# Top-level required fields tell you what every review packet must contain:
print(schema["required"])
```

Review packets are required to include `review_status`, `blocked_uses`,
`required_human_approvals`, and `provenance`. A packet that does not conform to
this schema will be rejected by the conformance engine before it reaches reviewers.

### 3d. Validate a payload against a contract

```python
from urban_platform.sdk import validate_payload, load_json_fixture

# Load the sample submission fixture
payload = load_json_fixture(
    "specifications/examples/program_reporting/city_program_submission.sample.json"
)

result = validate_payload("consumer_city_program_submission", payload)
print(result["valid"])        # True
print(result["error_count"])  # 0
```

---

## 4. Deployment profile — how is it configured?

```python
from urban_platform.sdk import list_deployment_ids, get_deployment_profile

print(list_deployment_ids())
# ['flood_local_demo', 'program_reporting_state_demo']

profile = get_deployment_profile("program_reporting_state_demo")
print(profile["deployment_name"])  # Program Reporting state demo (fixtures only)
print(profile["deployment_type"])  # single_agency
print(profile["environment"])      # local
print(profile["enabled_domains"])  # ['program_reporting']
print(profile["notes"])
# Declarative example for Phase 1 program reporting: city submission
# fixture and fund-release review packet builder. No automated fund release.
```

The deployment profile links to:
- `deployments/examples/program_reporting_state_demo/application_registry.yaml` —
  which builders are allowed to run in this deployment
- `deployments/examples/program_reporting_state_demo/provider_registry.yaml` —
  which external data providers are enabled (empty for Phase 1: no live feeds)

---

## 5. Reference catalogs — what reference data does this domain use?

```python
from urban_platform.sdk import list_reference_catalog_ids, get_reference_catalog

print(list_reference_catalog_ids())
# ['administrative_units_demo_in', 'program_catalog_demo_in', 'reporting_periods_demo_in']

catalog = get_reference_catalog("program_catalog_demo_in")
print(catalog["catalog_type"])   # program_catalog
print(catalog["status"])         # draft_demo

for entry in catalog["entries"]:
    print(entry["code"], "—", entry["label"])
# stormwater_resilience_grant_2026 — Stormwater resilience grant 2026 (synthetic program)
```

Submissions reference catalog entries by `program_id`. The `reference_data_versions`
field in each submission records which catalog version the submitter used, enabling
the state to detect submissions that reference stale catalogs.

---

## 6. Evidence and store touchpoints (read-only overview)

These SDK functions interact with a **completed run's stored artifacts**. They do
not execute application logic and do not modify store state. You need a real
`AIROS_STORE_DIR` pointing to a store that has a completed Program Reporting run.

```python
from urban_platform.sdk import (
    export_evidence_bundle,
    inspect_evidence_bundle,
    verify_evidence_bundle,
    backup_file_store,
    inspect_store_backup,
    verify_store_backup,
)

# After a completed run (run_id from POST /applications/.../runs):
run_id = "436748cab0ad47b2"   # example from runtime smoke validation

# Export an evidence bundle for the run
bundle_path = export_evidence_bundle(run_id=run_id, output_dir="/tmp/evidence")
# → /tmp/evidence/evidence_bundle_436748cab0ad47b2_<timestamp>.zip

# Inspect without extracting
summary = inspect_evidence_bundle(bundle_path)
print(summary["run_count"])         # number of runs in bundle
print(summary["output_count"])      # number of outputs
print(summary["audit_event_count"]) # number of audit trail events

# Verify integrity (hash manifest check)
result = verify_evidence_bundle(bundle_path)
print(result["valid"])   # True if no hash mismatches

# Backup the whole store (governance snapshot)
backup_path = backup_file_store(output_dir="/tmp/backups")
inspect_store_backup(backup_path)
verify_store_backup(backup_path)

# Dry-run restore (never mutates the live store)
restore_file_store_dry_run(backup_path, target_dir="/tmp/restore_preview")
```

**What these calls are for:**

| Function | Purpose |
|---|---|
| `export_evidence_bundle` | Package run artifacts for reviewer hand-off or audit |
| `inspect_evidence_bundle` | Check bundle contents without extracting |
| `verify_evidence_bundle` | Confirm bundle integrity via hash manifest |
| `backup_file_store` | Snapshot the full store for governance archiving |
| `inspect_store_backup` / `verify_store_backup` | Audit a backup without restoring |
| `restore_file_store_dry_run` | Preview a restore without touching the live store |

Evidence bundles are **not** signed in the current pilot. See
[`docs/SIGNED_EVIDENCE_BUNDLES_DESIGN.md`](SIGNED_EVIDENCE_BUNDLES_DESIGN.md) for
the future design.

---

## 7. How a run flows end-to-end (reference, not executable)

This section maps the SDK concepts above onto a full runtime execution for context.
It requires the Core API to be running and is not part of the read-only SDK surface.

```
City submits report
        │
        ▼
POST /records/consumer_city_program_submission
  → Validates payload against contract schema (SDK: validate_payload)
  → Stores in file store (StoredRecord)
  → Appends audit event

POST /applications/program_reporting_review_packet/runs
  → Checks app is in allowlist (SDK: get_app_descriptor)
  → Creates StoredRun (status: running)
  → Executes allowlisted builder:
       build_fund_release_review_packet()
  → Stores outputs (StoredOutput)
       consumer_fund_release_review_packet  ← validated against output contract
       consumer_program_reporting_state_summary
  → Updates StoredRun (status: completed)
  → Appends audit event

Human reviewer:
  GET /outputs → inspects review packet
  export_evidence_bundle(run_id) → portable audit artifact
```

**Safety invariants at every step:**
- No step authorizes fund release
- `blocked_uses` is present in both the input payload and the output packet
- `human_review_required: true` is set in both
- Conformance engine validates output schema before the run is marked completed

---

## 8. Running the example script

A companion script at [`examples/sdk/program_reporting_walkthrough.py`](../examples/sdk/program_reporting_walkthrough.py)
runs all the read-only SDK calls from sections 1–5 above and prints a structured
summary. It does not require the Core API to be running and does not mutate any state.

```bash
python examples/sdk/program_reporting_walkthrough.py
```

Expected output sections:
1. Platform inventory counts
2. App descriptor summary (inputs, outputs, safety gates, blocked uses)
3. Contract field counts (required fields for input + output contracts)
4. Submission fixture validation result
5. Deployment profile summary
6. Reference catalog entries

---

## Related docs

- [`docs/SDK_SURFACE.md`](SDK_SURFACE.md) — canonical public SDK surface
- [`docs/CORE_API_PILOT.md`](CORE_API_PILOT.md) — Core API runtime reference
- [`docs/EVIDENCE_BUNDLES.md`](EVIDENCE_BUNDLES.md) — evidence bundle design
- [`docs/PROGRAM_REPORTING_AND_FUND_RELEASE.md`](PROGRAM_REPORTING_AND_FUND_RELEASE.md) — domain background
- [`specifications/app_descriptors/program_reporting_review.v1.yaml`](../specifications/app_descriptors/program_reporting_review.v1.yaml) — raw descriptor
- [`deployments/examples/program_reporting_state_demo/`](../deployments/examples/program_reporting_state_demo/) — deployment profile and registries
