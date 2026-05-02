# AirOS Review Dashboard — UI Guidelines

This document defines the **shared layout and interaction model** for the Streamlit **Review Console** (`review_dashboard/`). All use-case tabs (Air Pollution, Flood, Property & Buildings, Heat, Crowd, Events) follow these rules so city actors get a **consistent, verification-first** experience.

## Principles

1. **Decision support, not operations**  
   Surfaces must not read like orders, tax demands, penalties, demolition notices, or automated enforcement. Use explicit callouts where risk is high.

2. **Human-readable first**  
   Prefer **metrics, tables, bullets, and captions**. Do not use `st.json` / raw dict dumps as the primary UI. Internal keys (e.g. `property_registry_records`) must be shown as **human labels** (e.g. “Property registry records”), except inside **collapsed** technical expanders.

3. **Provenance and safety visible**  
   Each domain view should make **data quality**, **synthetic/demo flags**, **warnings**, and **blocked uses** (when present) easy to scan—not buried.

4. **One review shell per domain tab**  
   Within a tab, structure content as:
   - **Domain header** (title + short caption + primary safety callout if needed)
   - **Context strip** (key metrics or KPIs as `st.metric` columns)
   - **Optional filters** (compact row; domain-specific)
   - **Main body**: prefer **two columns** `[~62% browse | ~38% detail]` when there is a **queue + drill-down** (Air, Flood, Property). Simpler tabs (Crowd, Events) may use a **single column** but still use the same **header + context + empty states + technical expander** pattern.

5. **Browse vs detail**  
   - **Browse (left):** list, map, or table of items to triage.  
   - **Detail (right):** summary, evidence, reviewer actions, audit—**scoped to the selected item** when selection exists.

6. **Selection**  
   Prefer **dataframe / map selection** when the Streamlit version supports it; use **selectbox** only as a fallback for compatibility. Never rely on selection alone without an empty state when nothing is selected.

7. **Presentation vs domain logic**  
   Tabs implement **layout and navigation** only. **Consumer-shaped payloads** (dashboard, packets, field tasks) are built in **`urban_platform/applications/<domain>/`** and validated against **`specifications/consumer_contracts/`**—do not encode new domain semantics solely in Streamlit.

8. **Raw / technical data**  
   Full JSON or large blobs live only under a **collapsed by default** expander, titled e.g. **“Technical: Raw …”**.

9. **Empty states**  
   When there is no data, show a short **explanation + next step** (e.g. run pipeline, run conformance), not a blank area.

## Implementation

- Shared helpers live in `review_dashboard/ui_shell.py` (`render_domain_header`, `render_context_metrics`, `render_section_title`, `render_browse_detail_layout`, `render_empty_state`, `render_technical_json_expander`, etc.).
- Human-readable labels for repeated patterns may use `review_dashboard/formatters.py` where appropriate.

## Tab bar (top level)

Top-level `st.tabs` remain the **use-case switcher** (Air Pollution, Flood, Property & Buildings, …). Each tab implements the same **domain header + shell** conventions above; only **content and filters** differ by domain.

## Review checklist (for contributors)

- [ ] Domain header + caption + safety callout where needed  
- [ ] Context metrics (or explicit “not applicable”)  
- [ ] No primary `st.json` of large payloads  
- [ ] Tables use stakeholder-facing column names  
- [ ] Empty states with guidance  
- [ ] Collapsed “Technical: Raw …” expander for contract/debug payloads  
- [ ] No weakening of privacy / provenance / blocked-use messaging  
