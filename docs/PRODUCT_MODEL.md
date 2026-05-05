# AirOS Product Model

## Purpose

AirOS is a Decision Support Operating System for urban governance.

It turns contract-shaped data into validated records, applies domain-specific decision logic, and produces review outputs, proposed actions, validation receipts, run metadata, and audit trails for authorized human decision-making.

AirOS is not itself an air quality, flood, heat, property, complaint, revenue, or program-reporting application. Those are AirOS Apps that run on AirOS Core.

AirOS does not authorize or automate final government actions.

## Core flow

Data sources  
→ Provider adapters  
→ Validated AirOS records  
→ Decision logic  
→ Review outputs  
→ Proposed actions  
→ Authorized human decision  
→ Audit trail, validation receipts, and run metadata

**Decision logic** is the set of rules, models, simulations, scoring methods, and workflow checks that convert validated records into review outputs.

**Review outputs** are structured packets, summaries, flags, scores, warnings, evidence, and next-step guidance for human review.

**Proposed actions** are suggested next steps such as “request clarification,” “queue for authorized review,” “field verification required,” or “monitor further.” Proposed actions are not final decisions.

## Product model at a glance

Generic product category | AirOS product area | Meaning
---|---|---
Operating platform | **AirOS Core** | Domain-neutral runtime for records, validation, runs, outputs, receipts, and audit.
Domain applications | **AirOS Apps** | Packages domain-specific decision logic and review experiences.
Data-source connectors | **AirOS Provider Adapters** | Connect external systems and normalize their data into AirOS records.
Developer framework | **AirOS SDK** | Helps developers build apps, adapters, contracts, and tests.
Developer/operator tools | **AirOS Studio / CLI** | Tools to scaffold, validate, run, package, deploy, and inspect AirOS apps.
Application marketplace | **AirOS App Catalog** | Discovery, installation, and governance of apps, adapters, dashboards, deployment templates, and contract packs.
Identity directory | **AirOS Identity & Trust** | Participants, users, organizations, roles, keys, certificates, and policies.
Network fabric | **AirOS Network Layer** | Cross-node messaging, routing, envelopes, delivery receipts, retries, and inter-agency communication.
Operational traceability | **AirOS Audit, Runs, and Validation Receipts** | Explains what was ingested, validated, run, produced, and audited.

## AirOS Core

AirOS Core is domain-neutral. It provides:

- contracts and manifest
- record ingestion
- validation
- validation receipts
- allowlisted decision-logic execution
- output storage
- run metadata
- audit events
- deployment configuration
- reference catalog support
- identity and policy later
- network envelopes later

Core should not contain PM2.5, flood, heat, property, revenue, complaint, or fund-release-specific decision logic.

## Decision Logic

Decision logic is the domain-specific processing layer inside an AirOS App. It may include rules, thresholds, scoring methods, simulations, statistical models, machine-learning models, and workflow checks.

Decision logic can produce flags, scores, classifications, review statuses, evidence summaries, and proposed actions. It must not directly execute final government decisions.

## AirOS Apps

Air Quality, Flood, Heat, Program Reporting, Property, Complaints, Revenue, and other domains are AirOS Apps. An AirOS App is a packaged decision-support capability that runs on AirOS Core and emits contract-shaped outputs for review workflows.

AirOS Apps package domain-specific decision logic, contracts, examples, dashboard panels, deployment templates, tests, documentation, and safety constraints.

The distinction is important:

- Decision logic is what processes the data.
- An AirOS App is how that logic is packaged, deployed, tested, governed, and presented.

Each app package should eventually contain:

- input contracts
- output contracts
- examples or fixtures
- decision logic
- dashboard panel
- deployment template
- tests
- documentation
- safety constraints

## Provider Adapters

Provider adapters connect external systems to AirOS by turning source-system data into contract-shaped AirOS records.

Provider adapters:

- connect to external systems
- fetch or receive raw data
- normalize data into AirOS records or platform objects
- attach provenance, source metadata, quality flags, and timestamps
- submit records through `POST /records/{contract_key}`

Provider adapters do not produce final decisions.

## AirOS SDK

The SDK should help developers build apps and adapters without knowing all Core internals.

AirOS has an early SDK skeleton under `urban_platform/sdk/` that provides stable helper imports for:

- inspecting app descriptors (metadata only)
- validating payloads/fixtures by `contract_key` (manifest-backed)
- computing deterministic payload hashes

It does not replace the Core API and does not enable dynamic plugins.

Future SDK capabilities:

- contract helpers
- builder decorators
- local test harness
- fixture generator
- output validation helpers
- receipt and audit helpers
- packaging helpers

## AirOS Studio / CLI

Today, Studio/CLI is mostly repository tooling. Later it may include a UI.

Capabilities:

- doctor
- conformance
- app scaffold
- app validate
- app test
- app package
- deployment init/validate/run
- core serve
- records post
- runs list
- outputs list
- receipts inspect
- audit inspect

## AirOS App Catalog

The App Catalog is future-facing but important.

AirOS App Descriptors (under `specifications/app_descriptors/`) are the first step toward a governed catalog:

- they document app boundaries and safety posture without moving folders
- they are validated against a schema (and cross-checked against the manifest, builder allowlist, and deployment examples)
- they are not dynamic plugin loading; execution still goes through the safe builder registry

Catalog should eventually include:

- apps
- provider adapters
- dashboard panels
- deployment templates
- reference catalogs
- contract packs

Each listing should include:

- app_id or package_id
- publisher
- version
- input contracts
- output contracts
- required reference catalogs
- required permissions
- safety and blocked uses
- conformance status
- signature or trust status later

## Identity & Trust

This layer answers:

- who is this user, service, agency, or node?
- which organization do they belong to?
- what roles do they have?
- which public keys or certificates identify them?
- which policies apply?

This is production-readiness work and is not done today.

## Network Layer

This layer answers:

- how do AirOS nodes discover each other?
- how are messages packaged?
- how are messages routed?
- how are delivery receipts handled?
- how are retries and failures handled?
- how do city, state, and agency nodes communicate?

Message envelopes and delivery receipts exist as early contract direction, but production networking is future work.

## AirOS Audit, Runs, and Validation Receipts

This area explains what happened:

- what was ingested
- which contracts were applied
- what validation passed or failed
- which allowlisted run executed
- what inputs were used
- what outputs were produced and stored
- what audit evidence was written

## Current repository mapping

This repo is not yet physically organized into separate products. Current mapping:

- **Core today**: `urban_platform/api/`, `urban_platform/storage/`, `urban_platform/deployments/`, `specifications/`
- **Apps today**: `urban_platform/applications/`
- **Provider adapters today**: `urban_platform/connectors/`
- **Studio/CLI today**: `tools/airos_cli.py`, `tools/deployment_runner/`, `tools/ai_dev_supervisor/`
- **Dashboard today**: `review_dashboard/`
- **Catalog/spec foundations today**: `specifications/manifest.json`, `deployments/examples/`

## Future repo direction

Future reorganization may separate:

- core/
- sdk/
- studio/
- apps/
- adapters/
- dashboard/
- catalog/

This document does not imply immediate movement of folders.

For a safe, phased approach (without breaking imports or introducing dynamic plugin loading), see [`docs/REPO_RESTRUCTURING_PLAN.md`](REPO_RESTRUCTURING_PLAN.md).

## Safety posture

AirOS may produce **review outputs** and **proposed actions**, but final decisions remain with authorized human and institutional processes.

It does not authorize or automate:

- fund release
- penalties or recovery
- emergency orders
- demolitions
- blacklisting
- public disclosure
- any final government decision

