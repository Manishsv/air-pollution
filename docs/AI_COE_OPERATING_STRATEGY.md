# AI Centre of Excellence — operating strategy (AirOS)

This document describes how an **AI CoE** can run AirOS as a **reusable urban intelligence core** while using **forward deployment** to meet **fragmented Indian city agencies** where they are—in capacity, data maturity, and priority.

## Role of the AI CoE

The CoE owns **platform integrity** and **governance**: specifications, conformance, shared components, safety patterns, and training for field teams. It does **not** replace municipal decision authority; it **enables** accountable decision support.

## Core platform team responsibilities

- Maintain **provider**, **platform object**, **domain**, and **consumer** specifications and the **manifest**.
- Keep **conformance** green and visible (`python main.py --step conformance`).
- Publish **bounded reference implementations** (e.g. air quality) that other domains can mirror.
- Define **non-negotiables**: provenance, reliability, human review, blocked uses—**no weakening** for speed.
- Curate **reusable playbooks** (`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`, `docs/URBAN_CONTEXT_INDIA.md`) so agents and vendors align without ad-hoc reinvention.

## Forward deployment engineer responsibilities

Forward deployment (“FD”) engineers work **inside or alongside** city contexts to:

- Discover **what data exists** (open, licensed, export, manual) and **what decisions** actors need.
- **Configure** domains, boundaries, and review workflows to **local priorities** (see `docs/USE_CASE_ROADMAP.md`).
- Stand up **connectors and dashboards** only where **contracts** exist—never “just wire JSON.”
- Train local staff on **interpretation limits** (synthetic flags, interpolation, blocked uses).
- Capture **feedback** as spec or playbook changes—not one-off hacks in a single city fork.

## Working with fragmented agencies

- Map **actors and decisions** before mapping tables: who acts, on what evidence, under what law or SOP?
- Prefer **read-only** and **review-first** surfaces until governance is explicit.
- Use **specs as the handshake** between agencies: shared consumer contracts reduce miscommunication when multiple vendors touch the same city.
- Expect **partial participation**: some agencies join late—**progressive adoption** is normal.

## Local priorities drive domain sequencing

The CoE does not force a single national domain order. **City A** may need flood and drainage first; **City B** may need air and heat. FD teams propose **bounded vertical slices** per city; the **roadmap** and **domain specs** record the rationale. The **core** stays shared; **activation order** is local.

## Agentic software development — used safely

Cursor and similar tools can **accelerate** specs, tests, and bounded implementations when:

- **Specs exist first** (or are written in the same PR before behavior lands).
- **Conformance** is run before merge.
- **Human review** applies to high-risk domains (revenue, enforcement, safety-of-life).

Agents are **not** a substitute for municipal legal process or field truth. They **reduce friction** on the path from contract to code—not on the path from signal to punishment.

## Field learnings feed the core

FD teams should routinely contribute:

- **New provider patterns** (as contracts + examples).
- **Domain threshold** and **review prompt** refinements (as domain spec changes).
- **Playbook** updates when a city discovers a repeatable integration pitfall.

The core team **generalizes** learnings so the next city inherits the fix—not a private branch.

## How success should be measured

Mix **platform** and **deployment** signals:

- **Specs & conformance**: manifest complete for active domains; conformance pass rate on CI.
- **Reuse**: second city adopts a domain with **less net new** spec surface than the first.
- **Safety**: blocked-use and provenance warnings remain visible in consumer UIs; no silent “production truth” from demos.
- **Operational fit**: reviewers and field staff can explain **what they will not do** with the output (healthy skepticism).
- **Time-to-first-value**: credible open-data slice in a new city within a predictable bounded window—not “full enterprise integration” as the only bar.

Read [`docs/URBAN_CONTEXT_INDIA.md`](URBAN_CONTEXT_INDIA.md) for the institutional backdrop, [`docs/DOMAIN_DEVELOPMENT_PLAYBOOK.md`](DOMAIN_DEVELOPMENT_PLAYBOOK.md) for the day-to-day agent workflow, and [`docs/reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md`](reviews/AIR_OS_ARCHITECTURE_REVIEW_2026_05_02.md) for a consolidated **architecture and development-approach** review (what to reinforce vs what to fix over time).
