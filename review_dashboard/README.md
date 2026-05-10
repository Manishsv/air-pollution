## Air Quality Review Console

This Streamlit dashboard is a **human review console** for officials and operational stakeholders.

### Run

From the **repo root**:

```bash
streamlit run review_dashboard/app.py
```

---

### Panels

#### Inbox

A prioritised list of AI-generated insights awaiting human review.

- **Priority tiers** — each insight is labelled high / medium / low (derived from agent confidence: ≥ 0.75 = high, 0.45–0.74 = medium, < 0.45 = low).
- **Outcome badges** — open (pending review), confirmed ✓, refuted ✗, or unverifiable ?.
- **Sort options** — by newest, highest confidence, or priority tier.
- **Detail modal** — clicking a row opens a four-tab dialog:
  - **Evidence** — signals, assessment summary, testable hypotheses.
  - **Recommended Actions** — agent-suggested interventions.
  - **Close** — field officer records a verdict (confirmed / refuted / unverifiable) and name; the outcome is written back to the knowledge store and surfaces to the agent on its next run.
  - **Ask agent** — re-run the H3 Expert Agent on-demand for this cell.

#### City Map

Spatial view of H3 cells with colour-coded risk levels.

- **Insights only toggle** (default on) — shows only cells that have at least one agent insight, matching what is in the Inbox. Toggle off to see all assessed cells.
- Cell colour reflects the highest risk level across all domains for that cell.

#### Infrastructure / Sensor Coverage

Sensor siting recommendations computed monthly. Shows coverage gaps by domain.

#### Ward Decisions / Reports

Aggregated summaries by administrative ward for briefings and reporting.

---

### What the dashboard must NOT be used for

- It must not be treated as automated decision-making.
- It must not claim causal attribution ("the AI found the cause").
- It must not be used for enforcement without field verification.

### Accountability note

The dashboard **does not automate government action**. It helps officials review evidence, confidence, and suggested next steps. The reviewer remains accountable for the final decision.

### Future integration (placeholder)

Decision actions can later be mapped to workflow systems (e.g. DIGIT/Airawat) by:
- sending the chosen action + reviewer note + packet_id
- attaching the decision packet JSON as evidence
