# Build Your First AirOS App

This tutorial is for developers who want to understand the **governed AirOS app-development workflow**.

**Important:** This tutorial does **not** create a runnable production app. It shows how to scaffold, edit, validate, package, and inspect an AirOS App **without** executing it. Execution requires review, registration, and allowlisting later.

## What you will build

A fictional **Streetlight Maintenance Review** app.

Conceptually, it ingests streetlight status records and produces **review outputs** such as:

- lights needing inspection
- likely outage clusters
- proposed next steps for maintenance teams
- `blocked_uses` and safety notes that prevent misuse

AirOS outputs are **review support only**. This app does **not** dispatch work orders automatically, and it does **not** authorize any government action.

## AirOS development loop (high level)

In AirOS, the beginner-friendly loop is:

`apps scaffold`
→ edit descriptor + contracts + examples + decision logic (your repo/workspace)
→ `apps validate`
→ `apps package`
→ `apps inspect-package`
→ `catalog add-package` (local metadata)
→ request review + registration + allowlisting later (so it can run safely)

## Step 1: Scaffold

Scaffold a new local app folder (this does **not** register or execute anything):

```bash
python tools/airos_cli.py apps scaffold streetlight_maintenance_review \
  --domain-id streetlight_maintenance \
  --output-dir /tmp/streetlight_maintenance_review
```

## Step 2: Inspect the generated structure

Your scaffolded folder should look like this (names may evolve, but the intent stays consistent):

- `README.md`: app purpose, safety posture, and how to validate/package
- `app_descriptor.yaml`: governed metadata (what the app is, what it consumes/produces, safety notes)
- `contracts/`: **local** contract drafts you’ll later upstream into `specifications/`
- `examples/`: sample JSON payloads (fixtures) you’ll later upstream into `specifications/examples/`
- `builders/`: decision logic code (should be pure, reviewable, testable)
- `dashboard/`: optional UI wiring notes (presentation only)
- `deployments/`: example deployment wiring placeholders (declarative configuration)
- `tests/`: local tests you’ll later adapt into repo CI tests

**Reminder:** A scaffold is a template. It’s expected to have placeholders and warnings until you fill in contracts, examples, and builder logic.

## Step 3: Define an input contract (conceptual)

For Streetlight Maintenance Review, imagine a provider sends a feed of status events.

Conceptual contract key (illustrative): `provider_streetlight_status_feed`

Example shape (illustrative only; not a real repo contract file):

```json
{
  "provider_id": "utility_portal_demo",
  "source_name": "Utility streetlight portal",
  "source_type": "city_portal",
  "license": "demo_fixture_only",
  "source_metadata": { "ingested_at": "2026-05-01T10:00:00Z" },
  "city_id": "city_demo_a",
  "reporting_period": "2026_Q2",
  "streetlight_id": "sl_ward_12_0001",
  "ward_id": "ward_12",
  "status": "suspected_outage",
  "last_seen_at": "2026-05-01T09:55:00Z",
  "quality_flag": "unverified",
  "provenance": {
    "fixture_only": true,
    "contains_real_pii": false,
    "notes": "Synthetic tutorial payload."
  }
}
```

In the real AirOS workflow, you would later:

- formalize this as a JSON Schema under `specifications/provider_contracts/`
- add one or more fixtures under `specifications/examples/`
- register both in `specifications/manifest.json`

## Step 4: Define an output contract (conceptual)

The output should be a review payload that’s safe for officials to read and act on through existing processes.

Conceptual contract key (illustrative): `consumer_streetlight_maintenance_review`

Example shape (illustrative only; not a real repo contract file):

```json
{
  "review_id": "streetlight_review_demo_001",
  "city_id": "city_demo_a",
  "reporting_period": "2026_Q2",
  "generated_at": "2026-05-01T10:05:00Z",
  "lights_needing_inspection": [
    { "streetlight_id": "sl_ward_12_0001", "ward_id": "ward_12", "reason": "repeated_outage_reports" }
  ],
  "outage_clusters": [
    { "ward_id": "ward_12", "suspected_outages": 17, "note": "cluster suggests feeder issue; confirm on ground" }
  ],
  "proposed_actions": [
    { "action_type": "inspection", "target": "ward_12", "priority": "high", "notes": "dispatch field team for verification" }
  ],
  "blocked_uses": ["automatic_work_order_dispatch", "public_outage_shaming"],
  "human_review_required": true,
  "provenance": {
    "builder_id": "streetlight_maintenance_review",
    "inputs": ["provider_streetlight_status_feed"],
    "contains_real_pii": false,
    "notes": "Tutorial output; review support only."
  }
}
```

Key safety choices:

- **Explicit `blocked_uses`** to prevent automation beyond review support.
- **`human_review_required: true`** to reinforce governance.
- Proposed actions are **suggestions** for authorized teams, not automatic dispatch.

## Step 5: Add sample fixtures (conceptual)

Before anyone can trust an app, it needs sample inputs and outputs:

- Sample inputs help reviewers and CI see what “valid provider data” looks like.
- Sample outputs help reviewers and CI see what “review-ready output” looks like.

In AirOS, fixtures are generally:

- synthetic (demo-only)
- non-secret
- non-PII (or explicitly authorized, which is not Phase 1 default)

## Step 6: Write decision logic (conceptual)

For Streetlight Maintenance Review, your decision logic might:

- group outage records by `ward_id`
- flag repeated failures for the same `streetlight_id`
- detect clusters where many streetlights show `suspected_outage` in a short window
- propose **inspection and verification** steps

**Guardrails:**

- outputs must be review-oriented (clear next human step)
- no enforcement language
- no automatic dispatch
- clear uncertainty and data quality signals (`quality_flag`, warnings, provenance)

## Step 7: Validate the local app (read-only)

Validate your local app package folder:

```bash
python tools/airos_cli.py apps validate /tmp/streetlight_maintenance_review
```

For scaffolds, **`valid_with_warnings`** is expected until you replace placeholders with real contracts/examples and decision logic.

Validation does **not** execute your builder code.

## Step 8: Package (review artifact)

Create a portable zip package:

```bash
python tools/airos_cli.py apps package /tmp/streetlight_maintenance_review --output-dir /tmp/airos_dist
```

Packaging does **not** install, register, or execute the app.

## Step 9: Inspect the package (read-only)

Inspect the zip package:

```bash
python tools/airos_cli.py apps inspect-package /tmp/airos_dist/streetlight_maintenance_review-v1.zip
```

Inspection is read-only and focuses on:

- package metadata
- descriptor presence and safety fields
- suspicious/secret-like files
- basic structure

## Step 10: Add to a local catalog (metadata only)

Add the package metadata to a local catalog index:

```bash
python tools/airos_cli.py catalog add-package /tmp/airos_dist/streetlight_maintenance_review-v1.zip --catalog-dir /tmp/airos_catalog

python tools/airos_cli.py catalog list --catalog-dir /tmp/airos_catalog
python tools/airos_cli.py catalog show streetlight_maintenance_review --catalog-dir /tmp/airos_catalog
```

The local catalog is **metadata only**. It does not make the app runnable.

## Step 11: What is still required before execution

To run an app in AirOS demos/pilots, additional governance steps are required. Typically:

- **Real contracts** added under `specifications/` (provider + consumer as needed)
- **Examples/fixtures** added under `specifications/examples/` (synthetic) and registered in `specifications/manifest.json`
- **App descriptor** registered (governed metadata, not a dynamic plugin)
- **Tests** added/updated so CI validates outputs against schemas
- **Builder implementation review** (safety, correctness, provenance, blocked uses)
- **Safe builder registry allowlisting** (explicit, fail-closed; no dynamic loading)
- **Deployment example** (declarative registries + profile) if you want a runnable demo path
- **Conformance pass** (`python main.py --step conformance`)
- **Safety review** (ensure outputs are review support only and don’t imply automated authority)

## Safety posture (repeat)

AirOS supports **review**. It does **not** authorize or automate:

- penalties / recovery
- emergency orders / evacuations
- blacklisting
- public disclosure without authorization
- any final government decision

Streetlight Maintenance Review outputs are **proposed next steps** for authorized human teams and must be treated as decision support, not automatic action.

