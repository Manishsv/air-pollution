# AirOS Apps — Review Contract Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Apps

---

## Purpose [INFORMATIVE]

The Review Contract defines what any human review interface must present to a reviewer, what actions it must make available, and what it must record when a reviewer acts. It is implementation-agnostic: the contract is satisfied by a web dashboard, a mobile app, a field tablet, or an API-driven workflow — as long as all normative requirements are met.

The review interface is the architectural enforcement point for AirOS's mandatory human-in-the-loop constraint. An insight that bypasses this interface and is acted upon directly is a safety violation, not a workflow shortcut.

---

## What Requires Review [NORMATIVE]

The following Knowledge Store items MUST pass through a human review step before any action is taken on them:

| Item | Table | Review action |
|------|-------|--------------|
| Agent insight | `h3_insights` | Officer closes with `outcome_status` |
| Decision packet | `h3_packets` | Officer reviews evidence and records disposition |

A review interface MUST present both types. An interface that surfaces only insights without surfacing the decision packets that support them is non-conformant.

---

## The Review Inbox [NORMATIVE]

A conformant review interface MUST provide a **review inbox** — a prioritised list of open items awaiting human review.

### Inbox Contents

The inbox MUST include all `h3_insights` with `outcome_status = 'open'` for the reviewer's assigned city or cities.

### Required Sort Order

The inbox MUST be sorted by the following criteria, in order:

1. `priority_tier` — `high` before `medium` before `low`
2. `confidence` descending within tier
3. `created_at` ascending within same confidence (older unreviewed items surface first)

### Required Filters

The inbox MUST expose at minimum:

| Filter | Values |
|--------|--------|
| Priority tier | `high` / `medium` / `low` / all |
| Domain | Any single canonical domain, or all |
| Time window | Last 24h / 48h / 7d / custom |

### Staleness Indicator

The inbox MUST display a staleness indicator for any insight whose underlying signals are more than 2× the domain cadence old. A reviewer MUST be able to distinguish "insight based on fresh data" from "insight based on data that may no longer reflect current conditions."

---

## The Evidence Panel [NORMATIVE]

When a reviewer selects an insight from the inbox, the review interface MUST present an **evidence panel** containing all of the following:

### 1. Insight Summary

| Field | Display requirement |
|-------|-------------------|
| `finding` | Full text, untruncated |
| `confidence` | Numeric value AND `priority_tier` label |
| `domains_involved` | All domain names |
| `created_at` | Human-readable timestamp with timezone |
| `agent_type` | Agent identifier |

### 2. Hypothesis Chain

Each `HypothesisItem` in `hypothesis_chain_json` MUST be displayed with:
- The `proposition` text
- The `testable_by` verification method
- The item-level `confidence`

The review interface MUST NOT collapse or summarise the hypothesis chain. The reviewer must be able to read every proposition.

### 3. Recommended Actions

Each `RecommendedAction` MUST be displayed with its `action`, `actor`, `urgency`, `condition`, and `blocked_if` (if present). Urgency MUST be visually distinguished (e.g. `immediate` rendered differently from `plan`).

### 4. Uncertainty Notes

All `uncertainty_notes_json` entries MUST be displayed. The review interface MUST NOT hide uncertainty notes behind an expand/collapse. Uncertainty is a primary input to the reviewer's decision — it must be immediately visible.

### 5. Spatial Context

The review interface MUST display:
- The target cell on a map at an appropriate zoom level (the cell and at least its k=1 ring neighbours)
- The `risk_level` of the target cell per domain (colour-coded by severity)
- The `risk_level` of k=1 neighbours (sufficient to identify spatial spread)

### 6. Signal Evidence

For each domain involved in the insight, the review interface MUST display:
- The most recent signal values for the primary signals in that domain
- The `data_quality` tier (`real_station` / `satellite_derived` / `model_estimate`)
- The `DATA_CONFIDENCE` value
- A comparison to the 30-day baseline (e.g. "current value is at the 91st percentile")
- The circadian baseline comparison (e.g. "current value is at the 87th percentile for this hour of day")

### 7. Prior Outcomes

The review interface MUST display:
- All prior `h3_expert` insights for this cell with their `outcome_status` (confirmed / refuted / unverifiable)
- If prior insights for the same domain pair were `refuted`, this MUST be visually flagged — a reviewer acting on an insight that resembles a previously refuted finding should be aware of that history.

### 8. Safety Gates

For decision packets associated with the insight, the review interface MUST display all `safety_gates_json` entries with their status (`pass` / `fail` / `not_applicable`) and the evidence used to evaluate each gate.

### 9. Blocked Uses

All `blocked_uses_json` entries from associated decision packets MUST be displayed prominently. The review interface MUST NOT allow a reviewer to proceed to close an insight without having scrolled past or acknowledged the blocked uses. (The exact acknowledgement mechanism is implementation-defined; the requirement is that blocked uses are not suppressible.)

---

## Review Actions [NORMATIVE]

A conformant review interface MUST expose exactly the following close actions for an open insight:

| Action | `outcome_status` set to | When to use |
|--------|------------------------|------------|
| **Confirm** | `confirmed` | Officer investigated and the finding was accurate |
| **Refute** | `refuted` | Officer investigated and the finding was inaccurate or misleading |
| **Mark unverifiable** | `unverifiable` | Officer could not gather sufficient evidence to confirm or refute |

No other terminal states are permitted. The review interface MUST NOT offer an "escalate", "defer", or "reassign" action that changes `outcome_status` — those are workflow features outside the Knowledge Store contract. If a deployment needs such features, they MUST be implemented outside the `h3_insights` lifecycle.

### Close Operation Requirements [NORMATIVE]

When a reviewer takes a close action, the review interface MUST:

1. Record `outcome_status` with the chosen value.
2. Record `closed_by` — the reviewer's identity string. This MUST NOT be empty.
3. Record `closed_at` — the UTC timestamp of the close action. This MUST NOT be set by the reviewer; it MUST be set by the system at the moment the action is submitted.
4. Write the close record atomically — a partial write (e.g. `outcome_status` set but `closed_by` missing) is non-conformant.

### Reviewer Identity [NORMATIVE]

The `closed_by` field MUST uniquely identify the reviewer within the deployment. The format is deployment-defined (email address, username, officer ID) but MUST be non-empty and MUST be stable across sessions — a reviewer's identity MUST NOT change between login sessions.

An anonymous close action (empty `closed_by`) MUST be rejected by the review interface. The Knowledge Store write interface MUST also reject a `close_insight` call with an empty `closed_by`.

### No Automated Closure [NORMATIVE]

The close action MUST be triggered by an explicit human gesture (button click, form submission, or equivalent). The review interface MUST NOT:
- Auto-close insights based on confidence threshold
- Auto-close insights based on time elapsed
- Batch-close multiple insights in a single action without individual review of each

This prohibition is absolute. See [App Contract — Safety Posture](APP_CONTRACT.md#safety-posture).

---

## Re-open Prohibition [NORMATIVE]

Once an insight reaches a terminal `outcome_status` (`confirmed`, `refuted`, or `unverifiable`), the review interface MUST NOT offer a re-open action. The closed record is permanent.

If a situation that was previously `refuted` recurs and warrants fresh analysis, the agent will produce a new insight on the next sweep. The review interface SHOULD surface prior refutations in the evidence panel of the new insight (see §Evidence Panel — Prior Outcomes).

---

## Completeness Requirement [NORMATIVE]

A reviewer MUST be presented with the full evidence panel before the close action is available. A review interface that allows a reviewer to close an insight without having been presented with:

- The full finding text
- All uncertainty notes
- All blocked uses
- Signal evidence with DATA_CONFIDENCE values

…is non-conformant, regardless of whether the reviewer chose to read them.

The implementation mechanism (scroll gating, explicit acknowledgement, timed display) is deployment-defined. The requirement is that the interface cannot structurally prevent the reviewer from seeing this information before acting.

---

## Outcome Feedback Loop [NORMATIVE]

The review interface MUST make closed outcomes available to agents on subsequent sweeps. This is satisfied by the Knowledge Store's append-only model — closed insights remain in `h3_insights` with their `outcome_status` set, and agents read them as part of context assembly.

The review interface MUST NOT archive or hide closed insights in a way that removes them from the agent's context window. Closed insights are evidence; they remain part of the cell's history.

---

## What the Review Contract Does Not Specify [INFORMATIVE]

- **Visual design** — layout, colour scheme, map library, component library. These are implementation choices.
- **Authentication and authorisation** — how reviewers log in, which cities they are authorised to review. These are deployment-level concerns.
- **Notification and assignment** — how insights are routed to specific reviewers, how reviewers are notified. These are workflow features outside the Knowledge Store contract.
- **Reporting** — how confirmed/refuted ratios are tracked over time, how officer performance is measured. These are App-layer analytics outside the review flow.
- **Mobile vs web** — the contract applies equally to both.

**Planned for v1.1 [INFORMATIVE]:** The following workflow features are explicitly deferred and will be specified in a future version:

- **Richer lifecycle states** — escalation, assignment to a department, field inspection tracking, resolution status separate from finding status
- **Department routing** — rules for which `domains_involved` or `priority_tier` combinations are routed to which officer roles
- **Appeal and contestation** — process for an officer or affected party to contest a confirmed finding
- **Privacy and data access controls** — role-based access to sensitive signal data; retention policies for reviewer actions and evidence records
- **Bulk review workflows** — safely reviewing clusters of related insights (e.g. a city-wide AQ event with 30 co-elevated cells) without requiring 30 separate close actions
