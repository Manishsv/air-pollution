# Build Your First AirOS Decision Support App

A practical guide to building a domain-specific Decision Support App on top of the H3 Knowledge Store and agent layer — illustrated by building a **School Air Quality Monitor**.

---

## 1. What is an AirOS Decision Support App?

An AirOS Decision Support App is a purpose-built view over the H3 Knowledge Store. Rather than showing every cell in a city with equal weight, an App narrows focus to a specific set of cells that matter for a particular use case — schools, hospitals, industrial zones, flood-prone wards — and presents findings to a specific audience in the language they use. The platform already has the signals; your App decides *which cells to surface*, *what context to emphasise*, and *how to present the output* to a school inspector rather than a general ward officer.

---

## 2. What you will build

The **School Air Quality Monitor** will:

1. Query the H3 Knowledge Store to find cells that contain schools (using the `known_features` field in `h3_metadata`).
2. Run the H3 Expert Agent on those cells, with emphasis on air quality, heat, and green cover signals that affect children's health.
3. Display findings in a dedicated Streamlit panel (`school_aq_panel.py`) wired into the existing Review Dashboard, showing priority tiers, a filtered map, and outcome tracking.

By the end you will have a working panel visible at `streamlit run review_dashboard/app.py` under the Domains tab.

---

## 3. Step 1: Understand the data available

The primary query entry point is `get_h3_context()` in `urban_platform/h3_knowledge/reader.py`. Call it for any H3 cell to get a structured dict covering signals, assessments, packets, and prior insights.

```python
from urban_platform.h3_knowledge.reader import get_h3_context

# Pull the last 7 days of signals for a cell
ctx = get_h3_context(
    h3_id="8a1b00000007fff",
    city_id="bangalore",
    signals_lookback_days=7,
    max_insights=5,
)

# What comes back
print(ctx["metadata"])       # known_features, ward, lat/lon centroid
print(ctx["signals"])        # list of signal dicts: domain, signal, value, level, observed_at
print(ctx["assessments"])    # latest risk_level per domain
print(ctx["insights"])       # prior H3 Expert Agent findings with outcome_status
```

For a city-wide overview — e.g. to understand how many cells have elevated air risk right now — use `get_store_stats()`:

```python
from urban_platform.h3_knowledge.reader import get_store_stats

stats = get_store_stats()
print(stats["total_cells"], stats["domains_active"])
```

The underlying store is SQLite. You can run raw queries via `H3KnowledgeStore.get().fetchdf(sql, params)` if you need something the helpers don't expose.

---

## 4. Step 2: Identify target cells

School cells are flagged in `h3_metadata.known_features_json`. The ingestor encodes them as a JSON array of feature strings, e.g. `["school", "park"]`. Query for cells that contain `"school"`:

```python
from urban_platform.h3_knowledge.store import H3KnowledgeStore

store = H3KnowledgeStore.get()

school_cells_df = store.fetchdf(
    """
    SELECT h3_id, city_id, ward, lat, lon, known_features_json
    FROM h3_metadata
    WHERE city_id = ?
      AND known_features_json LIKE '%school%'
    ORDER BY h3_id
    """,
    ["bangalore"],
)

print(f"Found {len(school_cells_df)} cells containing schools")
print(school_cells_df[["h3_id", "ward", "lat", "lon"]].head())
```

If your deployment does not yet have `known_features_json` populated for school locations, you can seed it by cross-referencing an OpenStreetMap extract. The `urban_platform/h3_knowledge/geocoder.py` module provides `tag_h3_cells_from_geojson()` for exactly this purpose.

Alternatively, if you have air quality assessments already, you can find school cells that also have elevated air risk:

```python
high_risk_school_cells_df = store.fetchdf(
    """
    SELECT m.h3_id, m.city_id, a.risk_level, a.primary_value
    FROM h3_metadata m
    JOIN (
        SELECT h3_id, city_id, risk_level, primary_value,
               ROW_NUMBER() OVER (PARTITION BY h3_id, city_id ORDER BY assessed_at DESC) AS rn
        FROM h3_assessments
        WHERE domain = 'air' AND city_id = ?
    ) a ON a.h3_id = m.h3_id AND a.city_id = m.city_id AND a.rn = 1
    WHERE m.known_features_json LIKE '%school%'
      AND a.risk_level IN ('high', 'severe')
    ORDER BY a.primary_value DESC
    """,
    ["bangalore"],
)
```

---

## 5. Step 3: Run the agent on target cells

`H3ExpertAgent` takes a single cell and runs a multi-turn LLM analysis, then writes its finding to `h3_insights`. Run it for each school cell:

```python
from urban_platform.agents.h3_expert import H3ExpertAgent

def analyse_school_cells(city_id: str, h3_ids: list[str]) -> list[dict]:
    """Run the H3 Expert Agent on a list of school cells and return insights."""
    results = []
    for h3_id in h3_ids:
        try:
            agent = H3ExpertAgent(
                h3_id=h3_id,
                city_id=city_id,
                signals_lookback_days=7,
            )
            insight = agent.run()
            results.append({"h3_id": h3_id, "status": "ok", "insight": insight})
            print(f"  {h3_id}: {insight['priority_tier']} -- {insight['finding'][:80]}")
        except Exception as exc:
            results.append({"h3_id": h3_id, "status": "error", "error": str(exc)})
            print(f"  {h3_id}: ERROR -- {exc}")
    return results


if __name__ == "__main__":
    from urban_platform.h3_knowledge.store import H3KnowledgeStore

    store = H3KnowledgeStore.get()
    df = store.fetchdf(
        "SELECT h3_id FROM h3_metadata WHERE city_id = ? AND known_features_json LIKE '%school%'",
        ["bangalore"],
    )
    school_h3_ids = df["h3_id"].tolist()

    print(f"Analysing {len(school_h3_ids)} school cells...")
    results = analyse_school_cells("bangalore", school_h3_ids)
    ok      = sum(1 for r in results if r["status"] == "ok")
    print(f"Done: {ok}/{len(results)} succeeded.")
```

The agent writes its insight to `h3_insights` automatically via `write_insight()` in `urban_platform/h3_knowledge/writer.py`. You do not need to call the writer yourself.

**Tip:** For a large number of cells you can pre-fetch the city-level weather forecast once and pass it as the `forecast` argument to each agent to avoid redundant API calls:

```python
# forecast is a dict with keys "weather" and "aq" — fetched once per city per sweep
for h3_id in school_h3_ids:
    agent = H3ExpertAgent(h3_id, "bangalore", forecast=forecast)
    agent.run()
```

---

## 6. Step 4: Create a dashboard panel

Create the file `review_dashboard/components/school_aq_panel.py`. This panel queries `h3_insights` for school cells and displays them with priority tiers, a summary table, and a map of flagged cells.

```python
"""School Air Quality Monitor panel -- AirOS Decision Support App.

Displays H3 Expert Agent insights for cells containing schools,
filtered by priority tier and outcome status.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from urban_platform.h3_knowledge.store import H3KnowledgeStore


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def _load_school_insights(city_id: str) -> pd.DataFrame:
    """Load insights for cells tagged with 'school' in h3_metadata."""
    store = H3KnowledgeStore.get()
    return store.fetchdf(
        """
        SELECT i.insight_id,
               i.h3_id,
               i.created_at,
               i.priority_tier,
               i.confidence,
               i.finding,
               i.domains_involved,
               i.outcome_status,
               m.ward,
               m.lat,
               m.lon
        FROM h3_insights i
        JOIN h3_metadata m
          ON i.h3_id = m.h3_id AND i.city_id = m.city_id
        WHERE i.city_id = ?
          AND m.known_features_json LIKE '%school%'
          AND i.agent_type = 'h3_expert'
        ORDER BY i.created_at DESC
        LIMIT 200
        """,
        [city_id],
    )


# ---------------------------------------------------------------------------
# Priority tier colours (matches inbox_panel.py conventions)
# ---------------------------------------------------------------------------

_TIER_COLOUR = {
    "P1": "#b42318",
    "P2": "#c4520a",
    "P3": "#92670a",
    "P4": "#1a7f37",
}


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_school_aq_panel(city_id: str = "bangalore") -> None:
    st.markdown("### School Air Quality Monitor")
    st.caption(
        "H3 Expert Agent insights for cells containing schools. "
        "Findings are cross-domain -- air quality, heat, and green cover are "
        "all considered together. Review each finding before acting."
    )

    df = _load_school_insights(city_id)

    if df.empty:
        st.info(
            "No school-cell insights found. "
            "Run the agent on school cells first:\n\n"
            "```\npython -m urban_platform.agents.h3_expert "
            "--city bangalore --top-risk 20\n```\n\n"
            "Then tag school cells in h3_metadata.known_features_json."
        )
        return

    # Filters
    col_tier, col_outcome, col_metric = st.columns(3)

    with col_tier:
        tier_opts = ["All"] + sorted(df["priority_tier"].dropna().unique().tolist())
        tier = st.selectbox("Priority tier", tier_opts, key="school_tier")

    with col_outcome:
        outcome_opts = ["All"] + sorted(df["outcome_status"].dropna().unique().tolist())
        outcome = st.selectbox("Outcome", outcome_opts, key="school_outcome")

    with col_metric:
        st.metric("School cells with insights", df["h3_id"].nunique())

    filtered = df.copy()
    if tier != "All":
        filtered = filtered[filtered["priority_tier"] == tier]
    if outcome != "All":
        filtered = filtered[filtered["outcome_status"] == outcome]

    # Summary table
    st.divider()
    if filtered.empty:
        st.caption("No insights match the selected filters.")
        return

    display_cols = ["priority_tier", "h3_id", "ward", "finding", "confidence",
                    "outcome_status", "created_at"]
    display_cols = [c for c in display_cols if c in filtered.columns]

    st.dataframe(
        filtered[display_cols].rename(columns={
            "priority_tier":  "Tier",
            "h3_id":          "H3 Cell",
            "ward":           "Ward",
            "finding":        "Finding",
            "confidence":     "Confidence",
            "outcome_status": "Outcome",
            "created_at":     "Generated",
        }),
        hide_index=True,
        use_container_width=True,
    )

    # Map
    map_df = filtered.dropna(subset=["lat", "lon"])
    if not map_df.empty:
        st.divider()
        st.markdown("**Cell locations**")
        st.map(map_df[["lat", "lon"]], zoom=11)

    # Selected row detail
    st.divider()
    st.markdown("**Insight detail**")
    cell_options = filtered["h3_id"].unique().tolist()
    selected_cell = st.selectbox("Select cell", cell_options, key="school_cell_select")

    cell_rows = filtered[filtered["h3_id"] == selected_cell]
    if not cell_rows.empty:
        row = cell_rows.iloc[0]
        tier_colour = _TIER_COLOUR.get(str(row.get("priority_tier", "")), "#6b7280")
        st.markdown(
            f'<span style="color:{tier_colour};font-weight:600;">'
            f'{row.get("priority_tier", "--")}</span> &nbsp; '
            f'Confidence: {row.get("confidence", "--")}',
            unsafe_allow_html=True,
        )
        st.markdown(row.get("finding", "No finding text."))

        domains = row.get("domains_involved", "")
        if domains:
            st.caption(f"Domains involved: {domains}")

        current_outcome = row.get("outcome_status", "pending")
        outcome_options = ["pending", "verified", "false_positive", "actioned"]
        new_outcome = st.selectbox(
            "Record outcome",
            outcome_options,
            index=outcome_options.index(current_outcome)
                  if current_outcome in outcome_options else 0,
            key="school_outcome_record",
        )
        if st.button("Save outcome", key="school_save_outcome"):
            from urban_platform.h3_knowledge.writer import close_insight
            close_insight(row["insight_id"], outcome_status=new_outcome)
            st.success(f"Outcome recorded: {new_outcome}")
            st.cache_data.clear()
```

---

## 7. Step 5: Wire it into the dashboard

Open `review_dashboard/app.py`. Add three lines — one import at the top with the other component imports, and one entry in the `_DOMAIN_PANELS` dict.

**Add the import** near the other domain panel imports (around line 40):

```python
from review_dashboard.components.school_aq_panel import render_school_aq_panel
```

**Register the panel** in the `_DOMAIN_PANELS` dict (around line 318):

```python
_DOMAIN_PANELS = {
    # ... existing entries ...
    "School AQ Monitor": render_school_aq_panel,
}
```

That is all. The selectbox-based navigation means the panel only renders when selected, so there is no performance cost for other views.

---

## 8. Step 6: Run and verify

**1. Seed the knowledge store** — run the full ingest pipeline if you haven't already:

```bash
python main.py --step ingest-h3
```

**2. Tag school cells** — if `known_features_json` is not yet populated, seed it manually for a test cell:

```python
from urban_platform.h3_knowledge.store import H3KnowledgeStore

store = H3KnowledgeStore.get()
store.execute(
    "UPDATE h3_metadata SET known_features_json = ? WHERE h3_id = ? AND city_id = ?",
    ['["school"]', "8a1b00000007fff", "bangalore"],
)
store.commit()
```

**3. Run the agent on school cells**:

```bash
python -m urban_platform.agents.h3_expert --city bangalore --top-risk 20
```

Or run the targeted script from Step 3.

**4. Launch the dashboard**:

```bash
streamlit run review_dashboard/app.py
```

Navigate to **Domains -> School AQ Monitor**. You should see the insight table and map populated with findings for school cells.

**5. Check the conformance suite** to confirm the store is valid:

```bash
python main.py --step conformance
python tools/airos_cli.py doctor
```

---

## 9. Going further

**Scheduled sweeps for school cells.** The scheduler in `urban_platform/scheduler.py` runs the H3 Expert Agent for high-risk cells each sweep cycle. Add a school-specific pass that always analyses school cells regardless of their current assessed risk level — because even moderate risk near a school warrants officer attention.

**Custom thresholds for schools.** The Rules Registry at `data/config/rules_registry.yaml` controls the risk level thresholds for every domain. Add a `school_proximity` override section to lower the AQI threshold that triggers a `high` risk level when a school is present in the cell. No code change required — the ingestors read the registry at runtime.

**Outcome tracking workflow for school health officers.** The `close_insight()` function in `urban_platform/h3_knowledge/writer.py` accepts an `outcome_status` of `verified`, `false_positive`, or `actioned`. Build a weekly digest that queries all school-cell insights with `outcome_status = 'pending'` and routes the list to the school health officer for review. The data is already there — it just needs a reporting skin.

**Cross-domain compound risks specific to schools.** The H3 Expert Agent already looks for compound risks across domains. To make it more school-aware, extend the system prompt in `urban_platform/agents/h3_expert.py` with a school-context addendum that instructs the model to weight air + heat + noise compound risks more heavily when a school is present in the cell metadata.
