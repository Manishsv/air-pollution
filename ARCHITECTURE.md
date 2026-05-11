# AirOS — Architecture & Developer Guide

## Three interaction modes

Every developer interaction with AirOS fits into one of three modes.
Pick the right mode for your use case before writing any code.

```
┌─────────────────────────────────────────────────────────────────────┐
│  MODE          │  IMPORT / ENDPOINT              │  READS FROM       │
├─────────────────────────────────────────────────────────────────────┤
│  DISCOVER      │  from airos.os.sdk import ...   │  specifications/  │
│  QUERY         │  from airos.os.sdk import store │  SQLite store     │
│                │  AirOSClient             │  SQLite store     │
│  INGEST/RUN    │  POST /records                  │  HTTP API         │
│                │  POST /applications/{id}/runs   │                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Mode 1 — DISCOVER (SDK metadata)

**Use when:** building adapters, validating data contracts, inspecting what the
platform supports — before the pipeline has ever run.

```python
from airos.os.sdk import (
    list_app_ids,           # what review apps exist?
    list_builders,          # what agents/builders run?
    get_builder_spec,       # what does builder X consume/produce?
    list_provider_adapter_ids,  # what data sources are wired up?
    get_contract_schema,    # what does contract "h3_signals" look like?
    validate_payload,       # does my payload conform?
    get_deployment_profile, # what are the config values for "production"?
)
```

All DISCOVER functions read from `specifications/` on disk.
**No store. No HTTP. No pipeline required.**

### Builder discovery

```python
from airos.os.sdk import list_builders, get_builder_spec

# All builders
for b in list_builders():
    print(b["builder_id"], "·", b["description"])

# Only LLM-backed builders
for b in list_builders(requires_llm=True):
    print(b["builder_id"], b["latency_class"])

# Single builder
spec = get_builder_spec("h3_expert")
print(spec["input_contracts"])   # ["h3_signals", "h3_metadata", "h3_assessments"]
print(spec["output_contracts"])  # ["h3_assessments", "h3_insights"]
```

---

## Mode 2 — QUERY (store helpers + AirOSClient)

**Use when:** building dashboards, running analysis, reading what the pipeline
has produced. **Requires the pipeline to have run at least once.**

### Option A — `store` module (recommended starting point)

```python
from airos.os.sdk import store

# Latest signals for a city
sigs = store.get_signals("bangalore")

# Assessments in the last 24 h, high-risk only
assessed = store.get_assessments("bangalore", risk_level="high")

# City-wide AI pattern narrative
patterns = store.get_city_patterns("bangalore")

# Health snapshot (cell counts, open insights, domain risk map)
health = store.get_city_health_summary("bangalore")

# Per-domain risk driver breakdown
drivers = store.get_domain_drivers("bangalore")

# Pending field-verification tasks
tasks = store.get_field_tasks("bangalore")

# Store stats / freshness
stats = store.get_stats("bangalore")
```

### Option B — `AirOSClient` (full runtime surface)

```python
from airos.os.sdk import AirOSClient

client = AirOSClient()  # base_path defaults to "."

# Decision / action packets (field-ready instructions)
packets = client.get_decision_packets(category="air_quality")

# Raw observations and features (pandas DataFrames)
obs = client.get_observations(variable="pm25")
feats = client.get_features(feature_name="aqi_index")

# AI-generated recommendations
recs = client.get_recommendations(min_confidence=0.7)

# Platform events and metrics
events = client.get_events(severity="high")
metrics = client.get_metrics()
```

`AirOSClient` is the surface used internally by the Streamlit dashboard.
Use it when you need decision packets, observations, features, or audit data.
Use `store.*` when you need signals, assessments, city patterns, or domain
risk breakdowns.

---

## Mode 3 — INGEST / RUN (HTTP API)

**Use when:** pushing new data into the store from an external system, or
triggering a pipeline run programmatically.

```
POST /records                        # ingest signals / observations
POST /applications/{app_id}/runs     # trigger a review-app run
GET  /runs                           # list run status
GET  /outputs                        # fetch run outputs
GET  /validation-receipts            # schema validation results
GET  /audit-events                   # audit trail
```

Discovery routes (GET-only, same surface as the SDK):

```
GET  /apps                           # list app descriptors
GET  /adapters                       # list provider adapters
GET  /contracts                      # list data contracts
GET  /builders                       # list builder specs
```

OpenAPI spec: `specifications/openapi/`.

---

## Data flow

```
External sources (GEE, OpenAQ, …)
        │  INGEST (POST /records)
        ▼
  h3_signals  ──────────────────────────────────────────┐
        │                                               │
        │  h3_expert builder (LLM, per cell)            │
        ▼                                               │
  h3_assessments                                        │
  h3_insights                                           │
        │                                               │
        │  city_pattern builder (LLM, city-wide)        │
        ▼                                               │
  city_patterns                                         │
        │                                               │
        │  QUERY (store.* / AirOSClient)        │
        ▼                                               │
  Dashboard / API consumers  ◄────────────────────────-─┘
```

---

## Builder execution model

Builders run in a **sweep** orchestrated by the pipeline. Each sweep:

1. GEE / OpenAQ connectors ingest fresh signals → `h3_signals`
2. `h3_expert` runs per active cell → `h3_assessments`, `h3_insights`
3. `city_pattern` synthesises insights → `city_patterns`

LLM-backed builders (`h3_expert`, `city_pattern`) call the configured LLM via
`airos.agents.llm_client`.  Connector builders (GEE, OpenAQ) are rule-based.

```python
from airos.os.sdk import list_builders

# See trigger mode and latency class for each builder
for b in list_builders():
    print(f"{b['builder_id']:25} trigger={b['trigger']}  llm={b['requires_llm']}  {b['latency_class']}")
```

---

## Common mistakes

| Mistake | Fix |
|---|---|
| `from airos.os.sdk.client import AirOSClient` | `from airos.os.sdk import AirOSClient` |
| Calling `store.*` before pipeline has run | Returns empty DataFrames — check `store.get_stats()` first |
| Using SDK DISCOVER functions to check pipeline state | Use `store.get_city_health_summary()` instead |
| Importing `airos.drivers.store.reader` directly | Use `airos.os.sdk.store` — it's the stable public surface |
| Expecting `get_decision_packets()` in `store.*` | Use `AirOSClient().get_decision_packets()` |

---

## Package map

```
airos/
  os/
    sdk/
      __init__.py       ← public surface (this is the entry point)
      store.py          ← QUERY: store helpers (signals, assessments, patterns)
      client.py         ← QUERY: AirOSClient (packets, obs, events)
      apps.py           ← DISCOVER: app descriptors
      builders.py       ← DISCOVER: builder / agent registry
      adapters.py       ← DISCOVER: provider adapter descriptors
      contracts.py      ← DISCOVER: data contract schemas
      deployments.py    ← DISCOVER: deployment profiles
      catalogs.py       ← DISCOVER: reference catalogs
      evidence.py       ← governance: evidence bundles
      store_backup.py   ← governance: store backup/restore
      hashing.py        ← utilities: deterministic payload hashing
      testing.py        ← utilities: fixture validation helpers
  agents/
    h3_expert.py        ← h3_expert builder implementation
    city_pattern_agent.py ← city_pattern builder implementation
  drivers/
    store/
      reader.py         ← internal: low-level store queries (used by sdk/store.py)
      ingestor.py       ← internal: signal/assessment ingest logic
      writer.py         ← internal: store write helpers
  network/
    api/                ← FastAPI routes (INGEST/RUN mode)
    dashboard/          ← Streamlit dashboard (uses AirOSClient + store)
specifications/         ← governed YAML/JSON specs (read by DISCOVER mode)
```
