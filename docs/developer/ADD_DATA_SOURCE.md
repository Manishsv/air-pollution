# Adding a New Driver to AirOS

This guide walks you through the full 11-step process for adding a new data
source — called a **driver** — from scratch. By the end you will have signals
appearing in the H3 Knowledge Store, the scheduler picking up the domain
automatically, and the dashboard rendering a dedicated panel.

We use the **terrain** driver (SRTM / Copernicus DEM elevation) as the worked
example throughout, because it was built following exactly this process and all
its files are in the repo for reference.

**Estimated time:** 3–4 hours for a developer familiar with Python.

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│  External world                                                  │
│  Open-Elevation API / SRTM tile cache / Copernicus DEM tiles     │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTP / local files
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1 — Connector                                             │
│  airos/drivers/connectors/<domain>/<source>.py                   │
│  Knows the API. Returns a plain list[dict].                      │
│  No H3, no DB, no business logic.                                │
└───────────────────────────┬──────────────────────────────────────┘
                            │ list[dict]
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 2 — Ingestor                                              │
│  airos/drivers/store/<domain>_ingestor.py                        │
│  Maps raw points to H3 cells.                                    │
│  Computes per-cell signals (and optionally assessments).         │
│  Calls write_signals(), record_ingest() from writer.py.          │
└───────────────────────────┬──────────────────────────────────────┘
                            │ SQL upserts
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3 — H3 Knowledge Store                                    │
│  data/h3/knowledge.sqlite (DuckDB, WAL mode)                     │
│  Tables: h3_signals, h3_assessments, h3_cell_metadata,           │
│          h3_ingest_log, h3_analysis_requests, …                  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ SELECT queries
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 4 — Driver class + registry                               │
│  airos/drivers/store/drivers/<domain>_driver.py                  │
│  data/config/drivers_registry.yaml                               │
│  Thin wrapper that the scheduler and conformance tools discover. │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 5 — Agents + Dashboard                                    │
│  airos/agents/ reads signals to produce insights.                │
│  airos/network/dashboard/components/<domain>_panel.py renders.   │
└──────────────────────────────────────────────────────────────────┘
```

Each layer has exactly one job. The connector is ignorant of H3. The ingestor
is ignorant of the API. The store is ignorant of domain logic. This makes each
piece independently testable and replaceable.

---

## Step 1 — Domain specification

**File:** `specifications/domain_specs/<domain>.v1.yaml`

The spec is the source of truth for what the domain measures, which signals it
produces, what cadence it runs at, and what safety gates apply. Write this
before any code so design decisions are captured explicitly.

**Reference:** `specifications/domain_specs/terrain.v1.yaml`

Key fields to fill in:

```yaml
domain_id: terrain
version: "1"
label: Terrain (DEM elevation context)
produces_assessments: false      # true for risk domains, false for context domains
cadence_hint: "90 days"

signals:
  - name: ELEVATION_M
    unit: metres
    description: Mean cell elevation above sea level (SRTM/Copernicus 30m DEM).

# ... more signals ...

safety_gates:
  - id: void_fill_notice
    description: >
      Cells with > 10% void-filled pixels get DATA_CONFIDENCE = 0.65.
      Dashboard must display a notice when any cell in view has void-filled data.

data_source_policy: >
  Both SRTM 30m (NASA, public domain) and Copernicus DEM 30m (ESA, free) are
  accepted. Copernicus preferred; SRTM as fallback. Source per cell recorded
  in provenance.
```

**Design question to answer before proceeding:** does your domain produce
**risk assessments** (e.g. flood risk score per cell) or is it **structural
context** (e.g. elevation, road network)? Context-only domains set
`produces_assessments: false` and are excluded from the assessment scheduler
loop (see Step 6).

---

## Step 2 — Provider contract

**File:** `specifications/provider_contracts/<domain>_<feed_name>.v1.schema.json`

A JSON Schema describing the raw data your connector will return. This is what
you will validate incoming data against before writing it to the store.

**Reference:** `specifications/provider_contracts/terrain_dem_feed.v1.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Terrain DEM feed (provider contract v1)",
  "type": "object",
  "required": ["provider_id", "source_name", "bbox", "samples"],
  "properties": {
    "provider_id": { "type": "string" },
    "bbox": {
      "type": "object",
      "required": ["lat_min", "lon_min", "lat_max", "lon_max"],
      "properties": {
        "lat_min": { "type": "number" },
        "lon_min": { "type": "number" },
        "lat_max": { "type": "number" },
        "lon_max": { "type": "number" }
      }
    },
    "samples": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["lat", "lon", "elevation_m", "quality_flag"],
        "properties": {
          "lat":          { "type": "number" },
          "lon":          { "type": "number" },
          "elevation_m":  { "type": ["number", "null"] },
          "quality_flag": { "type": "string",
                            "enum": ["ok", "void", "void_filled", "suspected_artefact"] }
        }
      }
    }
  }
}
```

---

## Step 3 — Consumer contract

**File:** `specifications/consumer_contracts/<domain>_signals.v1.schema.json`

A JSON Schema describing the per-H3-cell signal records that agents and the
dashboard will read from the store.

**Reference:** `specifications/consumer_contracts/terrain_signals.v1.schema.json`

Key point: if a signal is **agent-derived** (e.g. TERRAIN_CLASS is
classified by the H3 Expert Agent after ingest, not by the ingestor itself),
make it `["string", "null"]` so the schema accepts both the populated and
not-yet-classified states:

```json
"TERRAIN_CLASS": {
  "type": ["string", "null"],
  "description": "Agent-derived terrain classification. Null until the H3 Expert Agent runs."
}
```

---

## Step 4 — Example fixtures

**Directory:** `specifications/examples/<domain>/`

Two files:

| File | Purpose |
|------|---------|
| `provider_<domain>_samples.sample.json` | Raw data as the connector would return it — validates against the provider schema |
| `<domain>_signals_dashboard.sample.json` | Post-ingest H3 cell signals as the dashboard would read them — validates against the consumer schema |

Use real H3 cell IDs and real coordinates. Cover edge cases in the provider
fixture (all four `quality_flag` values, a void-fill cell, a low-confidence
cell). These fixtures double as schema regression tests (see Step 10).

**Reference:** `specifications/examples/terrain/`

---

## Step 5 — Connector

**File:** `airos/drivers/connectors/<domain>/<source>.py`

The connector has one job: call the external source and return a `list[dict]`.
No H3, no DB writes, no business logic.

**Reference:** `airos/drivers/connectors/terrain/srtm.py`

### Structure

```python
"""
<Domain> connector — <source description>.

Public API:
    fetch_<domain>_data(lat_min, lon_min, lat_max, lon_max, *, force_source=None)
    → list[dict]

Each dict must contain at minimum:
    lat            float
    lon            float
    <signal_field> float | None
    quality_flag   str
"""
from __future__ import annotations
import logging
...

logger = logging.getLogger(__name__)


def fetch_<domain>_data(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    *,
    force_source: str | None = None,
) -> list[dict]:
    ...
```

### Three-tier fallback pattern

For resilience, implement a priority chain:

1. **Live API** (preferred) — real data, may have rate limits or require a key
2. **Local cache / tile library** (fast fallback) — no network required
3. **Synthetic fallback** (test/CI fallback) — deterministic, marks
   `quality_flag="void_filled"` and includes `"synthetic_fallback"` in the
   `source_record_id` so the ingestor can set `DATA_CONFIDENCE = 0.0`

The `force_source` parameter lets tests pin to `"synthetic"` without network
calls.

### Connector rules

- Return an empty list (never `None`, never raise) when the source is
  unavailable. The ingestor handles empty gracefully.
- Normalise field names to `snake_case` in the connector, not the ingestor.
- Never import from `airos.drivers.store` inside a connector.
- Log a `WARNING` (not an exception) when falling back to a lower tier.

---

## Step 6 — Ingestor

**File:** `airos/drivers/store/<domain>_ingestor.py`

The ingestor takes the connector's output, maps it to H3 cells, computes
per-cell signals, and writes them to the store.

**Reference:** `airos/drivers/store/terrain_ingestor.py`

### Module-level connector import — important for testing

Import your connector's public function **at the module level**, not inside
the ingest function body:

```python
# CORRECT — patchable by tests
from airos.drivers.connectors.terrain.srtm import fetch_dem_samples

def ingest_terrain(...):
    samples = fetch_dem_samples(...)
```

```python
# WRONG — patch target does not exist as a module attribute
def ingest_terrain(...):
    from airos.drivers.connectors.terrain.srtm import fetch_dem_samples
    samples = fetch_dem_samples(...)
```

If the import is inside the function, `unittest.mock.patch(
"airos.drivers.store.<domain>_ingestor.fetch_<domain>_data")` will raise
`AttributeError` at test setup time.

### Ingestor skeleton

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
import h3 as _h3
import numpy as np

from airos.drivers.connectors.<domain>.<source> import fetch_<domain>_data  # module-level

logger = logging.getLogger(__name__)


def ingest_<domain>(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from airos.drivers.store.ingestor import _check_interval, DEFAULT_H3_RES
    from airos.drivers.store.writer import write_signals, upsert_metadata, record_ingest
    from airos.drivers.store.geo_agg import cells_for_bbox

    # 1. Watermark guard — raises _TooRecentError if run too recently
    try:
        _check_interval("<domain>", city_id, force)
    except Exception as e:
        logger.info("[%s/<domain>] %s", city_id, e)
        return 0

    # 2. Fetch raw data
    raw = fetch_<domain>_data(
        bbox["lat_min"], bbox["lon_min"],
        bbox["lat_max"], bbox["lon_max"],
    )
    if not raw:
        record_ingest(city_id=city_id, domain="<domain>", rows_written=0,
                      status="partial", error_msg="connector returned empty")
        return 0

    # 3. Map to H3 cells, compute signals, build signal_rows list
    signal_rows = []
    # ... domain-specific aggregation logic ...

    # 4. Write to store
    written = write_signals(signal_rows, city_id=city_id, domain="<domain>",
                            source="<source_name>")
    record_ingest(city_id=city_id, domain="<domain>", rows_written=written)
    return written
```

### write_signals() field reference

Every dict in `signal_rows` supports:

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `h3_id` | Yes | str | H3 cell ID at resolution 8 |
| `signal` | Yes | str | `UPPER_SNAKE_CASE` name matching the domain spec |
| `value` | Yes | float\|None | None writes a null row (cell appears in store but unclassified) |
| `unit` | No | str | e.g. `metres`, `degrees`, `ratio` |
| `city_id` | No | str | Overrides the function-level `city_id` |
| `domain` | No | str | Overrides the function-level `domain` |
| `source` | No | str | Used to infer `data_quality` tier automatically |
| `observed_at` | No | str | ISO-8601 UTC. Defaults to now |

### Context domains — no assessments

If your domain produces structural context rather than risk scores (terrain,
roads, buildings, drains), register it in `_NO_ASSESSMENT_DOMAINS` in
`airos/drivers/store/ingestor.py`:

```python
_NO_ASSESSMENT_DOMAINS = {"weather", "buildings", "roads", "drains", "terrain"}
```

The scheduler checks this set and skips the assessment-generation step for
listed domains.

---

## Step 7 — Wire into the ingestor dispatcher

**File:** `airos/drivers/store/ingestor.py`

Four places:

```python
# 1. Add to ALL_DOMAINS (controls which domains the CLI and scheduler know about)
ALL_DOMAINS = [
    "air", "fire", ..., "terrain",   # <-- add here
]

# 2. Add to _DOMAIN_INTERVAL (watermark cadence)
_DOMAIN_INTERVAL: dict[str, timedelta] = {
    # ...
    "terrain": timedelta(days=90),   # quarterly — terrain is static
}

# 3. Add a dispatcher wrapper function
def _ingest_terrain(city_id: str, bbox: dict, *, force: bool = False) -> int:
    from airos.drivers.store.terrain_ingestor import ingest_terrain
    return ingest_terrain(city_id, bbox, force=force)

# 4. Register in _DOMAIN_FN
_DOMAIN_FN: dict[str, Callable] = {
    # ...
    "terrain": _ingest_terrain,
}
```

Note: the `_check_interval` call lives inside the ingestor function itself
(see Step 6), not in the dispatcher wrapper. The dispatcher's job is purely
to route by domain name.

Common cadence values:

| Cadence | When to use |
|---------|-------------|
| `timedelta(minutes=15)` | Real-time sensor networks |
| `timedelta(hours=1)` | API-polled feeds (flood gauges, weather) |
| `timedelta(hours=6)` | Satellite passes, permit APIs |
| `timedelta(days=90)` | Near-static context (terrain, roads, buildings) |

---

## Step 8 — Driver class

**File:** `airos/drivers/store/drivers/<domain>_driver.py`

A thin `_InTreeDriver` subclass. The scheduler and conformance tools discover
drivers through this class, not the ingestor directly.

**Reference:** `airos/drivers/store/drivers/terrain_driver.py`

```python
"""AirOS built-in <domain> driver."""
from __future__ import annotations
from airos.drivers.store.drivers._base import _InTreeDriver


class TerrainDriver(_InTreeDriver):
    domain             = "terrain"
    cadence_hours      = 24 * 90        # must match _DOMAIN_INTERVAL in ingestor.py
    produces_assessments = False        # True for risk domains

    signal_names = [
        "ELEVATION_M",
        "SLOPE_DEG",
        "ASPECT_DEG",
        "RUGGEDNESS_INDEX",
        "DATA_CONFIDENCE",
        # Omit agent-derived signals — they are not written by this driver
    ]
    data_sources = [
        "Open-Elevation API (SRTM-backed, free, no key)",
        "SRTM 30m DEM — NASA public domain (srtm.py local tile cache)",
    ]
    _required_env_vars = []    # list any env vars needed, e.g. ["MY_API_KEY"]

    def fetch(self, city_id: str, bbox: dict, *, force: bool = False) -> int:
        from airos.drivers.store.ingestor import _ingest_terrain
        return _ingest_terrain(city_id, bbox, force=force)
```

`signal_names` is used by `conformance_check()` to verify that the driver's
declared signals match what the ingestor actually writes.

---

## Step 9 — Registry entry

**File:** `data/config/drivers_registry.yaml`

Add your driver so the loader and scheduler trust it:

```yaml
  terrain:
    builtin_class: airos.drivers.store.drivers.terrain_driver:TerrainDriver
    trust_level: core
    trusted: true
    cadence_hint: "90 days"
    notes: >
      SRTM 30m / Copernicus DEM. No API key required. Quarterly refresh.
      Signals: ELEVATION_M, SLOPE_DEG, ASPECT_DEG, RUGGEDNESS_INDEX,
      DATA_CONFIDENCE. TERRAIN_CLASS is agent-derived.
```

The `builtin_class` path format is `<dotted.module.path>:<ClassName>`. After
adding the entry, verify the loader picks it up:

```python
from airos.drivers.loader import load_drivers
drivers = load_drivers()
assert "terrain" in drivers
print(drivers["terrain"].conformance_check())
# ConformanceResult(ok=True, warnings=[], failures=[])
```

### Scheduler auto-discovery

The scheduler calls `load_drivers()` on startup. Any driver with
`trusted: true` in the registry is automatically included in every sweep.
No scheduler code needs to change when you add a new driver.

---

## Step 10 — Dashboard panel

**File:** `airos/network/dashboard/components/<domain>_panel.py`

**Reference:** `airos/network/dashboard/components/terrain_panel.py`

### Panel skeleton

```python
"""<Domain> domain panel."""
from __future__ import annotations
import streamlit as st
from airos.network.dashboard.ui_shell import render_domain_header


def render_<domain>_panel() -> None:
    render_domain_header(
        title="<Domain Label>",
        caption="One-line description of what this panel shows.",
        primary_alert=None,
    )

    city_id = st.session_state.get("city_id", "bangalore")

    # Load signals from the store
    signals = _load_<domain>_signals(city_id)
    if signals is None or signals.empty:
        st.info("No <domain> data. Run: python main.py --step ingest-h3 --domains <domain>")
        return

    # Metrics row, map, tabs, expanders ...
```

### Wire into app.py

In `airos/network/dashboard/app.py`, add the import and the panel entry:

```python
from airos.network.dashboard.components.<domain>_panel import render_<domain>_panel

# Inside main(), in _DOMAIN_PANELS:
_DOMAIN_PANELS = {
    # ...
    "🏔️ Terrain":   render_terrain_panel,
    # ...
}
```

---

## Step 11 — Tests

**File:** `tests/test_<domain>_pipeline.py`

**Reference:** `tests/test_terrain_pipeline.py` (54 tests)

### Test structure

```
TestConnector         — unit tests for the connector (use force_source="synthetic")
TestCellAggregation   — unit tests for the ingestor's aggregation helpers
TestIngestEndToEnd    — integration test: ingest → store → verify
TestDriverClass       — driver metadata and conformance_check
TestDispatcherWiring  — ALL_DOMAINS, _DOMAIN_FN, _DOMAIN_INTERVAL, _NO_ASSESSMENT_DOMAINS
TestSchemaValidation  — JSON Schema validates provider and consumer example fixtures
```

### Key patterns

**Avoid network calls in tests.** Use `force_source="synthetic"` and
`unittest.mock.patch` to pin the connector to its synthetic fallback:

```python
from unittest.mock import patch
from airos.drivers.store.terrain_ingestor import ingest_terrain

with patch(
    "airos.drivers.store.terrain_ingestor.fetch_dem_samples",   # module-level import
    wraps=lambda *a, **kw: __import__(
        "airos.drivers.connectors.terrain.srtm",
        fromlist=["fetch_dem_samples"],
    ).fetch_dem_samples(*a, **{**kw, "force_source": "synthetic"}),
):
    rows = ingest_terrain("bangalore", BBOX, force=True)
```

**Test that agent-derived signals are NOT written by the ingestor:**

```python
def test_terrain_class_not_written_by_ingestor(self, rows_written):
    from airos.drivers.store.store import H3KnowledgeStore
    df = H3KnowledgeStore.get().fetchdf(
        "SELECT COUNT(*) AS n FROM h3_signals "
        "WHERE domain = 'terrain' AND signal_name = 'TERRAIN_CLASS'"
    )
    assert int(df["n"].iloc[0]) == 0
```

**Test the watermark guard** — the second call with `force=False` must
return 0. Declare `rows_written` as a fixture parameter to guarantee the
first ingest ran before the watermark test:

```python
def test_force_false_skips_on_second_call(self, rows_written):
    assert rows_written > 0
    with patch("airos.drivers.store.terrain_ingestor.fetch_dem_samples", ...):
        result = ingest_terrain("bangalore", BBOX, force=False)
    assert result == 0
```

**Validate example fixtures against your JSON Schemas:**

```python
import json, jsonschema

def test_provider_example_validates(self):
    schema  = json.loads(Path("specifications/provider_contracts/terrain_dem_feed.v1.schema.json").read_text())
    example = json.loads(Path("specifications/examples/terrain/provider_dem_samples.sample.json").read_text())
    jsonschema.validate(example, schema)  # raises on failure
```

---

## Step 12 — Domain checklist

**File:** `airos/network/cli/ai_dev_supervisor/domain_checklists/<domain>.yaml`

**Reference:** `airos/network/cli/ai_dev_supervisor/domain_checklists/terrain.yaml`

Lists every required file path. The `airos maturity <domain>` command checks
each path exists and reports gaps.

```yaml
domain_id: terrain
label: Terrain (DEM elevation context)

checklist_groups:
  - id: domain_spec
    items:
      - id: terrain_domain_spec_v1
        path: specifications/domain_specs/terrain.v1.yaml
        required: true

  # ... provider_contracts, consumer_contracts, examples,
  #     connector, ingestor, driver_class, registry,
  #     dashboard_panel, tests, checklist (self) ...
```

---

## Running your driver

### One-off ingest (CLI)

```bash
# Ingest terrain for Bangalore, respect the watermark
python main.py --step ingest-h3 --domains terrain

# Force re-ingest even if run recently
python main.py --step ingest-h3 --domains terrain --force
```

### Verify signals in the store

```python
from airos.drivers.store.store import H3KnowledgeStore

store = H3KnowledgeStore.get()

# Signals written
df = store.fetchdf(
    "SELECT h3_id, signal_name, value, unit, ingested_at "
    "FROM h3_signals WHERE domain = 'terrain' LIMIT 10"
)
print(df)

# Ingest log
log = store.fetchdf(
    "SELECT city_id, domain, last_ingested_at, rows_written, status "
    "FROM h3_ingest_log WHERE domain = 'terrain'"
)
print(log)
```

### Run the tests

```bash
pytest tests/test_terrain_pipeline.py -v
```

### Scheduler pickup

Once the registry entry exists with `trusted: true`, the scheduler picks up
the domain automatically on the next sweep. No scheduler code changes needed.

Check scheduler status in the dashboard sidebar → **Scheduler status**, or:

```bash
python main.py --step scheduler   # starts the scheduler in the foreground
```

---

## Checklist summary

| Step | What you create |
|------|----------------|
| 1 | `specifications/domain_specs/<domain>.v1.yaml` |
| 2 | `specifications/provider_contracts/<domain>_<feed>.v1.schema.json` |
| 3 | `specifications/consumer_contracts/<domain>_signals.v1.schema.json` |
| 4 | `specifications/examples/<domain>/*.sample.json` (×2) |
| 5 | `airos/drivers/connectors/<domain>/<source>.py` |
| 6 | `airos/drivers/store/<domain>_ingestor.py` |
| 7 | Four edits to `airos/drivers/store/ingestor.py` |
| 8 | `airos/drivers/store/drivers/<domain>_driver.py` |
| 9 | Entry in `data/config/drivers_registry.yaml` |
| 10 | `airos/network/dashboard/components/<domain>_panel.py` + `app.py` wiring |
| 11 | `tests/test_<domain>_pipeline.py` |
| 12 | `airos/network/cli/ai_dev_supervisor/domain_checklists/<domain>.yaml` |

---

## Common gotchas

**Connector import must be at module level for tests to patch it.**
If `fetch_<domain>_data` is imported inside the ingest function body, the
`patch()` target does not exist as a module attribute and test setup fails with
`AttributeError`. Always import the connector function at the top of the
ingestor module.

**`datetime.fromisoformat` rejects the `Z` suffix on Python 3.9.**
Timestamps stored as `2026-05-11T04:48:20Z` will silently fail to parse on
Python 3.9. The watermark reader in `writer.py` normalises this:

```python
ts_str = str(ts).replace("Z", "+00:00")
return datetime.fromisoformat(ts_str)
```

If you find the watermark guard not blocking re-ingests, this is the most
likely cause.

**`_check_interval` lives in the ingestor, not the dispatcher wrapper.**
The dispatcher in `ingestor.py` just routes by domain name. The interval check
and the `record_ingest` call both live inside the ingestor function in
`<domain>_ingestor.py`.

**Agent-derived signals must NOT be written by the ingestor.**
If a signal requires city-wide context to classify (e.g. `TERRAIN_CLASS`
needs the elevation distribution of the whole city before labelling a cell
"hill" vs "plain"), leave it to the H3 Expert Agent. Omit it from
`signal_names` in the driver class so `conformance_check()` does not flag
a missing write.

**`produces_assessments: false` must be set in two places.**
Both in `specifications/domain_specs/<domain>.v1.yaml` (documentation) and
in the driver class (`produces_assessments = False`) and in
`_NO_ASSESSMENT_DOMAINS` in `ingestor.py` (runtime enforcement).
