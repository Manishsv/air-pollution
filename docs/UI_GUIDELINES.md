# AirOS Review Dashboard — UI Guidelines (business-user oriented)

This document defines the shared layout, language, and interaction model for the AirOS Streamlit review dashboard (`review_dashboard/`).

The dashboard is used by city officials, state reviewers, domain experts, and technical teams to **review** data-backed outputs before any operational action is taken. It must be easy to understand, safe to use, and usable on both desktop and narrow (mobile-like) screens.

The dashboard is a **review console**, not an automated command system.

## 1) Purpose of the dashboard
The dashboard should help users answer five practical questions:
1. What is happening?
2. Where is it happening?
3. Why is AirOS showing this?
4. How reliable is the data?
5. What should a human reviewer do next?
Every tab should support review, verification, and coordination. It must not present recommendations as automatic orders, enforcement notices, fund-release approvals, penalties, demolition instructions, or emergency commands.

## 2) Core principles
### 2.1 Decision support, not automated action
AirOS outputs must always be framed as **decision support**.
Use language such as:
- “Needs review”
- “Suggested for verification”
- “Flagged for attention”
- “Ready for authorized review”
- “Requires clarification”
Avoid language such as:
- “Approve”
- “Reject”
- “Release funds”
- “Issue penalty”
- “Demolish”
- “Enforce”
- “Order issued”
Where a domain has operational, financial, legal, or safety consequences, show a visible safety note:
> AirOS provides review support only. Final decisions must be taken by authorized officials through the applicable government process.

### 2.1b Runtime traceability is not approval
If a tab shows runtime traceability (runs, validation receipts, audit events), it must be framed as **traceability evidence**:

- what ran
- what validated against a schema
- what outputs were stored

It must **not** be framed as approval, authorization, or a final decision.

### 2.2 Business-readable first
The dashboard should be understandable to a non-technical reviewer.
Prefer:
- Clear headings
- Short explanations
- Summary cards
- Tables with readable column names
- Status labels
- Simple charts
- “What this means” notes
Avoid showing raw JSON, internal keys, file names, or code-like labels as the primary UI.
For example:
| Avoid | Prefer |
|---|---|
| `property_registry_records` | Property registry records |
| `fund_release_review_status` | Fund release review status |
| `city_program_submission.v1` | City program submission |
| `low_fund_utilization` | Low fund utilization |
Raw technical data may be shown only inside collapsed sections titled:
> Technical details  
> Raw payload  
> Validation details  

### 2.3 Provenance and confidence must be visible
Users should always know where the data came from and whether it is reliable.
Each tab should show, where available:
- Data source
- Reporting period or timestamp
- Whether the data is live, fixture, demo, uploaded, or synthetic
- Data quality warnings
- Confidence level
- Missing data
- Blocked uses
- Human review requirements
Do not bury warnings or blocked uses in technical sections.

### 2.4 Same mental model across all tabs
All domain tabs should follow the same basic structure so users do not have to relearn the interface.
Recommended structure:
1. Domain header
2. Safety or review note
3. Key metrics
4. Filters
5. Main review area
6. Detail view
7. Technical details
The content will differ by domain, but the interaction pattern should remain familiar.

## 3) Standard page structure
Each tab should follow this layout.
### 3.1 Domain header
At the top of each tab, show:
- Domain name
- One-line description
- Reporting period or data timestamp, if available
- Safety/review note, if relevant
Example:
> Program Reporting and Fund Release Review  
> Review city-reported program progress and financial utilization for the selected reporting period.  
> AirOS supports review only. It does not authorize fund release.

### 3.2 Context metrics
Show 3–5 key metrics near the top.
Examples:
For Program Reporting:
- Cities reported
- Cities ready for authorized review
- Cities needing clarification
- Total amount released
- Total amount spent
For Flood:
- High-risk locations
- Field tasks generated
- Reports needing verification
- Last updated
For Property & Buildings:
- Properties reviewed
- Suspected changes
- Verification tasks
- Records with missing source data
Metrics should be meaningful to business users. Avoid technical metrics unless they directly affect review.

### 3.3 Filters
Filters should be simple and compact.
Common filters:
- City
- Ward
- Reporting period
- Status
- Risk level
- Review status
- Data source
- Date range
Use defaults that show useful information immediately. Do not require users to configure filters before seeing anything.
On mobile, filters should stack vertically.

### 3.4 Main review area
Use a browse-and-detail pattern where appropriate.
Desktop layout:
```text
┌──────────────────────────────┬──────────────────────┐
│ Browse / queue / map / table │ Selected item detail │
│ 60–65% width                 │ 35–40% width         │
└──────────────────────────────┴──────────────────────┘

Mobile layout:

┌──────────────────────────────┐
│ Filters                      │
├──────────────────────────────┤
│ Browse / queue / table       │
├──────────────────────────────┤
│ Selected item detail         │
└──────────────────────────────┘

If the tab does not have item-level review, a single-column layout is acceptable.

#### Recommended “Air Pollution tab” pattern (preferred default)

Use the Air Pollution tab as the reference interaction model:

- **Top**: domain header + 3–5 context metrics + visible safety/warnings.
- **Left pane**: `st.tabs(["List View", "Map View"])`
  - **List View**: primary queue/table for reviewers with readable column names.
  - **Map View**: optional; must have a list/table alternative and must not be the only navigation.
- **Right pane**: selected item detail, ideally with `st.tabs([...])` for summary/evidence/decision/log (or a smaller set for the domain).

This pattern is business-friendly (list-first), consistent across domains, and works acceptably at narrow widths when columns are kept minimal.

### 3.5 Detail view

When a user selects a row, card, or map item, the detail view should show:

* Summary
* Status
* Key reasons or flags
* Data source / provenance
* Warnings
* Blocked uses
* Suggested next human review step
* Technical details in collapsed expander

The detail view should be scoped to the selected item. If nothing is selected, show an empty state such as:

Select a city, location, packet, or task to view details.

## 4) Mobile and responsive design (Streamlit practical)

The dashboard must be usable on mobile screens.

### 4.1 Mobile-first rules

On small screens:

- Use a single-column layout where possible (avoid deep nested columns).
- Stack metric cards vertically (or in two columns max).
- Put filters above results.
- Avoid wide tables as the only way to understand information.
- Keep important warnings visible without horizontal scrolling.
- Keep technical expanders collapsed by default.

**Streamlit reality check:** Streamlit does not provide a robust “is mobile” API. Design for narrow widths by default:
- Prefer fewer columns and shorter labels.
- Avoid assuming a fixed 60/40 split always looks good.
- Provide a list/table alternative when using maps.

### 4.2 Tables on mobile

Tables are useful on desktop but often hard to read on mobile.

For mobile-friendly review:

* Show a compact card list above or instead of wide tables.
* Limit visible columns to the most important fields.
* Put less-used fields inside an expander.
* Avoid more than 4–5 primary columns in mobile views.

Example mobile card:

City Demo B
Status: Needs clarification
Flags: Low utilization, Progress delay
Utilization: 42%
Progress: 38%
Next step: State reviewer to request clarification

### 4.3 Maps on mobile

Maps should not be the only navigation mechanism.

If using a map:

* Provide a list/table alternative.
* Show selected item details below the map.
* Avoid requiring precise map clicks for review.
* Keep map controls simple.

## 5) Language and tone

Use plain, neutral, government-appropriate language.

Prefer:

* “Needs clarification”
* “Review required”
* “Data missing”
* “Flagged for attention”
* “Ready for authorized review”
* “Field verification suggested”

Avoid:

* “Failed”
* “Fraud”
* “Illegal”
* “Violation confirmed”
* “Release approved”
* “Penalty required”

Unless an authorized source explicitly states it, the dashboard should not imply wrongdoing or final administrative decision.

## 6) Status labels (consistent wording)

Use consistent status labels across domains.

Recommended labels:

Status	Meaning
Review ready	Sufficient information for authorized human review
Needs clarification	Missing or inconsistent information
Field verification required	Needs field-level confirmation
Data incomplete	Required input is missing
Demo / fixture data	Sample data, not real operational data
Blocked use	The output must not be used for a specified action

For financial or administrative workflows, prefer:

* “Ready for authorized review”
* “Clarification needed”
* “Not ready”
* “Human review required”

Do not use:

* “Approved for release”
* “Rejected for funding”
* “Penalty recommended”

unless the legally authorized workflow has produced that decision outside AirOS.

## 7) Safety, blocked uses, and review responsibility

Every tab that supports consequential decisions should clearly show:

* What AirOS output can be used for
* What it must not be used for
* Who must review it
* What process remains authoritative

Example:

This view supports program review only. It must not be used for automatic fund release, penalty, blacklisting, or public disclosure. Final action requires authorized departmental and finance review.

Blocked uses should be displayed as readable bullets, not hidden in JSON.

## 8) Empty states

Never show a blank page when data is missing.

A good empty state explains:

1. What is missing
2. Why it matters
3. What to do next

Example:

No Program Reporting outputs found.
Run the demo first:
python tools/airos_cli.py deployment run deployments/examples/program_reporting_state_demo

For Docker:

docker run --rm -v "$(pwd)/airos-data:/app/data" ghcr.io/manishsv/air-os:latest deployment run deployments/examples/program_reporting_state_demo

## 9) Technical details (for developers/auditors)

Technical details are useful for developers and auditors, but should not dominate the business user experience.

Use collapsed expanders for:

* Raw JSON
* Schema names
* Contract payloads
* Debug metadata
* Validation details
* Internal identifiers

Recommended labels:

* Technical details
* Raw payload
* Validation details
* Contract data

Do not use raw JSON as the primary view.

## 10) Domain logic belongs outside the UI

The dashboard must not create new domain decisions.

Domain rules, review packets, dashboard payloads, and field tasks should be generated in:

urban_platform/applications/<domain>/

and validated against:

specifications/consumer_contracts/

The Streamlit dashboard should only:

* Load generated payloads
* Render summaries
* Provide filters and navigation
* Display warnings and blocked uses
* Show technical details when requested

It must not silently add thresholds, eligibility rules, enforcement logic, or financial approval logic.

## 11) Recommended tab pattern

Each tab should use this pattern:

Header
Safety note
Key metrics
Filters
Main review area
Details
Warnings / blocked uses
Technical details

For example:

Program Reporting tab

* Header: Program Reporting and Fund Release Review
* Metrics: Cities reported, ready for review, needing clarification
* Filters: reporting period, review status, city
* Main table/cards: city-wise review status
* Detail: selected city review packet
* Warnings: no automatic fund release
* Technical: raw review packet and state summary

Flood tab

* Header: Flood Risk Review
* Metrics: high-risk areas, field tasks, recent incidents
* Filters: ward, risk level, date
* Main: risk queue/map
* Detail: selected location or task
* Warnings: decision support only, field verification required

Property & Buildings tab

* Header: Property and Building Change Review
* Metrics: suspected changes, verification tasks, missing records
* Filters: ward, status, confidence
* Main: change review queue
* Detail: selected property/building record
* Warnings: no automatic tax demand, no enforcement without authorized process

## 12) Accessibility and readability

Use accessible defaults:

* Clear contrast
* Short paragraphs
* Descriptive labels
* Avoid color-only meaning
* Use icons sparingly and always with text
* Avoid dense layouts
* Use captions to explain charts
* Keep table column names readable
* Avoid unexplained abbreviations

If using colors, always pair them with text labels such as:

* High risk
* Needs clarification
* Review ready
* Demo data

---

## 13) Contributor checklist

Before merging a dashboard change, confirm:

* The tab has a clear domain header and caption.
* Safety or review-only language is visible where needed.
* Key metrics are understandable to non-technical users.
* Filters are simple and optional.
* Empty states explain next steps.
* Tables use business-friendly column names.
* Mobile layout does not depend on wide tables.
* Warnings and blocked uses are visible.
* Raw JSON appears only in collapsed technical sections.
* The UI does not add new domain rules.
* No automatic approval, enforcement, penalty, or fund-release language is introduced.
* Demo/fixture/synthetic data is clearly marked.
* The tab works reasonably on desktop and mobile screens.

---

## 14) Implementation notes

Shared UI helpers should live in:

review_dashboard/ui_shell.py

Reusable formatting should live in:

review_dashboard/formatters.py

Dashboard components should be organized by domain:

review_dashboard/components/<domain>_panel.py

The UI should favor reusable helpers for:

* Domain headers
* Safety callouts
* Context metrics
* Empty states
* Browse/detail layouts
* Technical expanders
* Status formatting
* Responsive card lists

---

## 15) Mobile behavior checklist

For each tab, test at narrow width and verify:

* The page remains readable.
* Metrics stack cleanly.
* Filters are usable.
* Tables do not force excessive horizontal scrolling.
* Important status and warning information is visible.
* Detail view appears below the browse list.
* Technical sections remain collapsed.
* The user can understand the main message without opening raw data.

## 16) Streamlit contributor notes (practical)

These notes are meant for Streamlit contributors so tabs remain consistent, safe, and maintainable.

### 16.1 Render generated outputs; don’t invent them
- Tabs should **read generated outputs** (JSON, parquet, etc.) and render them.
- If an output file is missing, show an **empty state** with the exact command to generate it.
- Do not “fix up” semantics in the UI (e.g., don’t compute new thresholds, infer readiness, or override statuses).

### 16.2 Prefer stable, readable components
- Use `render_domain_header(...)`, `render_context_metrics(...)`, `render_section_title(...)`, `render_empty_state(...)`, and `render_technical_json_expander(...)`.
- Use `st.dataframe(..., use_container_width=True)` for tables.
- Limit tables to “reviewer-relevant” columns; put the rest in the technical expander.

### 16.3 Keep safety visible and repetitive (by design)
- Always show safety warnings near the top for consequential domains (funding, enforcement-adjacent, reputational harm).
- Always show `blocked_uses` as readable bullets.
- Avoid “approval” language; prefer “ready for authorized review”.

### 16.4 Narrow-width friendliness
- Keep column counts low; avoid deeply nested columns.
- Avoid assuming large fixed heights; use `st.container(height=...)` only when it prevents a UX problem.
- Provide a list/table alternative to maps and long JSON.
