# AirOS Core — Scheduler Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Core

---

## Purpose [INFORMATIVE]

The Scheduler is the heartbeat of an AirOS deployment. It runs as a long-lived background process and is responsible for two distinct periodic jobs:

1. **Ingest sweep** — triggers Driver fetches for each active city and domain, subject to per-domain cadence gates.
2. **Agent sweep** — selects which H3 cells to analyse and invokes the H3 Expert Agent on each, followed by the City Pattern Agent for city-wide synthesis.

The Scheduler knows about cities and domains. It does not know about the internal logic of any Driver or Agent — it only calls the interfaces defined in this specification.

---

## Sweep Cycle [NORMATIVE]

The Scheduler MUST execute sweeps on a fixed interval. The default sweep interval is 900 seconds (15 minutes). The interval MUST be configurable via the `SWEEP_INTERVAL_SEC` environment variable.

Each sweep cycle MUST execute the two passes in this order:

```
1. Ingest sweep   — for all active cities × all active domains
2. Agent sweep    — for all active cities (if agent is enabled)
```

The agent sweep MUST NOT begin until the ingest sweep for that cycle has completed. A failure in the ingest sweep MUST NOT prevent the agent sweep from running — the Scheduler MUST log the ingest errors and proceed.

---

## City and Domain Configuration [NORMATIVE]

### Cities

Each city in a deployment MUST be declared with:

| Field | Required | Description |
|-------|----------|-------------|
| `city_id` | YES | Unique string identifier (e.g. `bangalore`) |
| `bbox` | YES | Bounding box: `{lat_min, lon_min, lat_max, lon_max}` in WGS84 |
| `display_name` | NO | Human-readable city name for dashboards |

The Scheduler MUST NOT process a city that has no bounding box.

The active city list is configurable via the `SCHEDULER_CITIES` environment variable (comma-separated list of `city_id` values). When unset, all declared cities are active.

### Domains

The active domain list is configurable via the `SCHEDULER_DOMAINS` environment variable. When unset, all 14 canonical domains are active. Inactive domains are skipped in both the ingest sweep and the risk pool selection.

---

## Ingest Sweep [NORMATIVE]

### Cadence Gate

Every domain has a minimum re-run interval (cadence). The Scheduler MUST enforce this gate using the watermark stored in `h3_ingest_log`:

1. Before calling `fetch`, the Scheduler reads `h3_ingest_log` for `(city_id, domain)` to determine `last_ingested_at`.
2. If `now − last_ingested_at < cadence_hours`, the domain is **skipped** for this city in this sweep. The Scheduler MUST NOT call `fetch`.
3. If the Driver returns `-1`, the Driver itself detected the cadence constraint — the Scheduler treats this identically to a skip.
4. If `force=true` is passed (operator-triggered), the cadence gate is bypassed.

**Canonical domain cadences [NORMATIVE]:**

| Domain | Cadence |
|--------|---------|
| `air` | 15 min |
| `fire` | 15 min |
| `weather` | 15 min |
| `crowd` | 15 min |
| `heat` | 30 min |
| `flood` | 1 hour |
| `water` | 1 hour |
| `waste` | 1 hour |
| `construction` | 6 hours |
| `green` | 6 hours |
| `noise` | 6 hours |
| `buildings` | 2160 h (≈ 90 days; not calendar-quarter-aligned) |
| `roads` | 2160 h (≈ 90 days; not calendar-quarter-aligned) |
| `drains` | 2160 h (≈ 90 days; not calendar-quarter-aligned) |

These cadences are defaults. An implementation MAY make them configurable via the Rules Registry. A Driver's `cadence_hours` identity field MUST be consistent with its declared canonical cadence; if it differs, the Scheduler MUST log a warning and use the Driver's declared value.

### Driver Dispatch

For each active `(city_id, domain)` pair that passes the cadence gate:

1. Resolve the active Driver for the domain from the driver pool (see [Driver Interface](../drivers/DRIVER_INTERFACE.md)).
2. Call `driver.fetch(city_id, bbox, force=False)`.
3. On success: the Driver calls `record_ingest` internally. The Scheduler records the returned row count.
4. On `DriverFetchError`: the Scheduler logs the error and writes `status=error` to `h3_ingest_log` for `(city_id, domain)` via `record_ingest`. This is the only case where the Scheduler calls `record_ingest` directly — on success, the Driver calls it internally. The Scheduler then continues to the next domain. A single domain failure MUST NOT abort the sweep.

If no Driver is loaded for a domain, the Scheduler MUST fall back to the deployment's legacy ingest function for that domain (if one exists), or skip the domain with a logged warning.

### Sweep Isolation

The Scheduler MUST process each `(city_id, domain)` pair independently. An exception from one pair MUST NOT propagate to affect another pair.

---

## Agent Sweep [NORMATIVE]

The agent sweep selects H3 cells for analysis and submits them to the H3 Expert Agent. It uses a **two-pool selection algorithm** to balance coverage of high-risk cells with discovery of cells that have not been recently analysed.

### Two-Pool Selection Algorithm

Given a budget of `N` cells per city per sweep (configurable via `SCHEDULER_TOP_N`, default 10):

**Risk pool** — 70% of budget (⌊N × 0.7⌋ cells):

- Source: `h3_assessments` for the past 7 days.
- Selection: cells with the highest composite risk score, ranked by `max_risk_score DESC, domain_count DESC` (number of domains with elevated risk).
- Risk levels included: `severe`, `high`, `moderate`. The inclusion of `moderate` is intentional — moderate-risk cells with multiple domains co-elevated often represent emerging situations worth early analysis. Deployments where the `moderate` pool is very large MAY configure a higher minimum risk level via `SCHEDULER_MIN_RISK_LEVEL` to ensure the coverage pool receives meaningful representation.
- Cooldown gate: cells that already have an `h3_expert` insight written in the past 6 hours are **excluded**.

**Coverage pool** — 30% of budget (⌈N × 0.3⌉ cells):

- Source: all cells in `h3_metadata` for the city.
- Selection: cells whose most recent `h3_expert` insight is oldest (or NULL — never analysed, ranked first).
- Exclusion: cells already in the risk pool and cells within the 6-hour cooldown.

The final list is the risk pool followed by the coverage pool. The Scheduler MUST process cells in this order (risk cells first within each sweep).

### Cooldown Gate

A cell MUST NOT be submitted to the H3 Expert Agent more than once per 6-hour window (per `city_id`). The Scheduler enforces this by checking `h3_insights` for the most recent `created_at` per `(h3_id, city_id, agent_type='h3_expert')` before including a cell in either pool.

The cooldown period SHOULD be configurable. The default is 6 hours.

### Agent Invocation

For each cell in the merged pool:

1. Invoke the H3 Expert Agent with `(h3_id, city_id)`.
2. The agent assembles its own context (see [Agent Interface](../apps/AGENT_INTERFACE.md)) and writes its insight directly to `h3_insights`.
3. If the agent fails (timeout, LLM error, tool error): log the failure, continue to the next cell. A single cell failure MUST NOT abort the agent sweep.

### City Pattern Agent

After all cells in the pool have been processed, the Scheduler MUST invoke the City Pattern Agent once per city (if it is enabled). The City Pattern Agent synthesises the insights produced in this sweep into a city-level summary and writes to `city_patterns`.

The City Pattern Agent MUST be skipped if fewer than 3 **new insights** were produced in the current sweep. **"New insights"** means `h3_insights` rows with `created_at` between the sweep start timestamp and the current time (i.e. rows written during this sweep cycle), regardless of the `outcome_status` of prior insights for the same cells.

---

## Sweep Status [NORMATIVE]

After each sweep, the Scheduler MUST write a status record containing at minimum:

| Field | Description |
|-------|-------------|
| `sweep_count` | Total number of sweeps completed since process start |
| `last_sweep_at` | ISO-8601 UTC timestamp of sweep completion |
| `next_sweep_at` | ISO-8601 UTC timestamp of next scheduled sweep |
| `ingest_summary` | Per `(city_id, domain)`: rows written, status, skipped flag |
| `agent_summary` | Per `city_id`: cells analysed, insights written, errors |

The reference implementation writes this to `data/scheduler_status.json`. Alternative implementations MAY expose it via an API endpoint or metrics sink. The status record MUST be readable without querying the Knowledge Store.

---

## Environment Variables [NORMATIVE]

| Variable | Default | Description |
|----------|---------|-------------|
| `SWEEP_INTERVAL_SEC` | `900` | Seconds between sweep starts |
| `SCHEDULER_CITIES` | all | Comma-separated list of active `city_id` values |
| `SCHEDULER_DOMAINS` | all | Comma-separated list of active domain names |
| `SCHEDULER_AGENT` | `true` | Set to `false` to disable the agent sweep (ingest only) |
| `SCHEDULER_TOP_N` | `10` | Cells per city per agent sweep |
| `SCHEDULER_FORCE` | `false` | Bypass cadence gates for all domains (use for backfill only) |
| `SCHEDULER_MIN_RISK_LEVEL` | `moderate` | Minimum `risk_level` for inclusion in the agent sweep risk pool (`moderate` / `high` / `severe`) |

---

## Non-Goals [INFORMATIVE]

- The Scheduler does not determine thresholds, scoring formulas, or risk levels — those are owned by Drivers and the Rules Registry.
- The Scheduler does not parse or interpret signal values — it only calls `fetch` and records watermarks.
- The Scheduler does not expose a REST API — status is file-based or metrics-based. The reference API layer reads the status file independently.
- The Scheduler does not guarantee exactly-once delivery — it guarantees at-least-once with idempotent `write_signals` protecting against duplicates.
