## Air Quality Review Console

This Streamlit dashboard is a **human review console** for officials and operational stakeholders.

### Run

From the `air_quality_mvp/` directory:

```bash
streamlit run review_dashboard/app.py
```

### What it shows

- **Areas Needing Review**: a prioritized list of areas that may require attention based on forecast category, confidence, interpolation, and sensor reliability.
- **Map View**: spatial context for the selected area and nearby sensors.
- **Review Summary**: plain-language summary of forecasted PM2.5, category, confidence, data type, and suggested handling.
- **Supporting Evidence**: tables for nearby sensors, weather, area characteristics, and sensor reliability (technical details hidden behind expanders).
- **System Data Quality**: run-level trust indicators (shown in the sidebar).
- **Reviewer Decision**: the reviewer records the next step and a required note (session-only action log).

### Layered evidence map

The **Map View** includes a layered evidence map. Reviewers can turn layers on/off to inspect:

- forecast category, confidence, and uncertainty
- observed vs estimated (interpolated) PM2.5 areas
- nearby sensors and sensor reliability
- static urban characteristics (e.g., road density, built-up ratio, green area)
- optional planning layers (sensor siting candidates, when available)

This helps reviewers understand not only forecast hotspots, but also the underlying evidence and uncertainty.

### What it must NOT be used for

- It must not be treated as automated decision-making.
- It must not claim causal attribution (“the AI found the cause”).
- It must not be used for enforcement without field verification.

### Accountability note

The dashboard **does not automate government action**. It helps officials review evidence, confidence, and suggested next steps.
The reviewer remains accountable for the final decision.

### Future integration (placeholder)

Decision actions can later be mapped to workflow systems (e.g. DIGIT/Airawat) by:
- sending the chosen action + reviewer note + packet_id
- attaching the decision packet JSON as evidence

