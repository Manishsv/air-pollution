# AirOS Core — Knowledge Store Specification

**Version:** 1.0.0-draft  
**Status:** Draft  
**Component:** Core

---

## Purpose [INFORMATIVE]

The Knowledge Store is the single authoritative persistent store in an AirOS deployment. All signals flow into it (written by Drivers). All reasoning flows out of it (read by Apps). It is the only place where state persists between scheduler runs.

Any storage technology that satisfies the interface contract below is a conformant Knowledge Store implementation. The reference implementation uses SQLite with WAL mode.

---

## Required Tables [NORMATIVE]

A conformant Knowledge Store MUST expose the following logical tables. The physical storage format is implementation-defined, but the logical schema (column names, types, deduplication semantics) MUST be satisfied.

---

### `h3_signals`

Stores one row per (cell, domain, signal name, hour). The finest-grained data in the system.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `h3_id` | string | YES | H3 cell identifier at the deployment's standard resolution (see Spatial Model) |
| `city_id` | string | YES | City partition key |
| `domain` | string | YES | Domain name (e.g. `air`, `flood`) — see Domain Catalogue |
| `signal` | string | YES | Signal name within the domain (e.g. `PM25`, `FLOOD_RISK_INDEX`) |
| `hour_bucket` | string | YES | ISO-8601 hour string — `YYYY-MM-DDTHH:00:00Z`. All timestamps are truncated to the hour. |
| `value` | float | YES | Signal value. Null values MUST NOT be written; skip the row instead. |
| `unit` | string | NO | Unit of measure (µg/m³, °C, index, ratio, …) |
| `source` | string | NO | Source identifier (API name, dataset name) |
| `data_quality` | string | NO | Provenance tier: `real_station` / `satellite_derived` / `model_estimate` / `unknown` |
| `observed_at` | string | NO | ISO-8601 timestamp of the original observation |
| `fetched_at` | string | NO | ISO-8601 timestamp when the Driver wrote this row |
| `level` | integer | NO | Hierarchy level (1 = raw signal) |

**Deduplication key:** `(h3_id, city_id, domain, signal, hour_bucket)`  
**Conflict rule:** On duplicate key, the row with the greater `fetched_at` value wins. If `fetched_at` is absent on either row, the incoming row wins. History accumulates across hours; rows are never deleted.

**Source provenance preservation [NORMATIVE]:** The `source` and `observed_at` fields MUST be preserved as written by the Driver. They MUST NOT be overwritten by the deduplication process. Any downstream system that reads signals MUST be able to trace every cell-level value back to its origin source identifier and original observation timestamp. Aggregation to the cell level is a transformation, not a deletion of provenance.

**Required signal [NORMATIVE]:** Every domain MUST write a `DATA_CONFIDENCE` signal row for every cell it writes any other signal for. `DATA_CONFIDENCE` MUST have a value in [0.0, 1.0]. A domain that does not write `DATA_CONFIDENCE` is non-conformant.

---

### `h3_assessments`

Stores one risk classification per (cell, domain, day). Written by risk-producing Drivers after each fetch.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `h3_id` | string | YES | H3 cell identifier |
| `city_id` | string | YES | City partition key |
| `domain` | string | YES | Domain name |
| `day_bucket` | string | YES | ISO-8601 date string — `YYYY-MM-DD` |
| `risk_level` | string | YES | One of: `good` / `moderate` / `high` / `severe` (or domain-defined equivalents — see Domain Catalogue) |
| `primary_index` | string | NO | Name of the composite index signal driving this assessment |
| `primary_value` | float | NO | Value of the primary index at assessment time |
| `dominant_issue` | string | NO | Human-readable label for the leading risk factor |
| `assessed_at` | string | NO | ISO-8601 timestamp |

**Deduplication key:** `(h3_id, city_id, domain, day_bucket)`  
**Conflict rule:** newer assessment wins within the same day.

**Structural domains:** Domains classified as structural (buildings, roads, drains, weather) MUST NOT write `h3_assessments` rows. They provide context signals only.

---

### `h3_insights`

Agent-produced findings. Written exclusively by Apps. Append-only — existing insights are never modified (only `outcome_status` is updated by the reviewer close flow).

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `insight_id` | string | YES | Unique identifier (UUID or equivalent) |
| `h3_id` | string | YES | H3 cell this insight concerns |
| `city_id` | string | YES | City partition key |
| `agent_type` | string | YES | Identifier of the agent that produced this insight |
| `finding` | string | YES | Human-readable summary of the cross-domain finding |
| `confidence` | float | YES | Agent confidence in this finding, in [0.0, 1.0] |
| `priority_tier` | string | YES | Derived from confidence: `high` (confidence ≥ 0.75) / `medium` (0.45 ≤ confidence < 0.75) / `low` (confidence < 0.45) |
| `domains_involved` | string | YES | Comma-separated list of domains involved in this insight |
| `hypothesis_chain_json` | string | NO | JSON array of testable propositions (see Insight Schema) |
| `recommended_actions_json` | string | NO | JSON array of recommended actions |
| `uncertainty_notes_json` | string | YES | JSON array of UncertaintyNote objects; MUST contain at least one entry for every insight regardless of confidence tier |
| `outcome_status` | string | YES | One of: `open` / `confirmed` / `refuted` / `unverifiable` — default `open` |
| `closed_by` | string | NO | Identifier of the officer who closed this insight |
| `closed_at` | string | NO | ISO-8601 timestamp of closure |
| `created_at` | string | YES | ISO-8601 timestamp when the insight was written |

**Write access:** Apps MUST be the only components that write to `h3_insights`. Drivers MUST NOT write insights.

**Append semantics:** New insights are always inserted. An App MUST NOT update any field of an existing insight except `outcome_status`, `closed_by`, and `closed_at` (the reviewer close fields).

**Frozen evidence principle [NORMATIVE]:** The signals, assessments, and context that informed an insight MUST be reproducible from the data that existed at `created_at`. Implementations MUST NOT allow a data update to silently alter what a reviewer sees when they open an insight. The recommended mechanism is to reference the `h3_packets` record (which is idempotent by `packet_id`) or to record the `fetched_at` watermarks of the source signals in `evidence_json`. An insight that cannot be traced back to the evidence that produced it is non-conformant for audit purposes.

---

### `h3_packets`

Decision packets — structured evidence bundles surfaced to human reviewers.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `packet_id` | string | YES | Unique identifier (idempotent — duplicate packet_id is silently ignored) |
| `h3_id` | string | YES | Target cell |
| `city_id` | string | YES | City partition key |
| `domain` | string | YES | Domain this packet concerns |
| `risk_level` | string | YES | Assessment at packet creation time |
| `summary` | string | YES | Human-readable decision support summary |
| `evidence_json` | string | NO | JSON blob of supporting signals and assessments |
| `safety_gates_json` | string | NO | JSON array of safety gate checks |
| `blocked_uses_json` | string | NO | JSON array of prohibited uses |
| `confidence` | float | NO | Overall evidence confidence |
| `created_at` | string | YES | ISO-8601 timestamp |

**Deduplication:** `packet_id` is the dedup key. Inserting the same `packet_id` twice MUST be a no-op.

---

### `h3_metadata`

Cell registry — records every cell that has ever received a signal.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `h3_id` | string | YES | H3 cell identifier |
| `city_id` | string | YES | City partition key |
| `centroid_lat` | float | NO | Cell centroid latitude |
| `centroid_lon` | float | NO | Cell centroid longitude |
| `first_seen` | string | NO | ISO-8601 timestamp of first signal |
| `last_active` | string | NO | ISO-8601 timestamp of most recent signal |
| `area_name` | string | NO | Human-readable area label |

**Deduplication key:** `(h3_id, city_id)`  
**Conflict rule:** update `last_active` on conflict. If `centroid_lat` / `centroid_lon` are already populated, a subsequent write MUST NOT overwrite them unless the incoming values differ by more than 1e-6 degrees (i.e. treat existing coordinates as authoritative once set).

---

### `h3_ingest_log`

Watermark table — records the last successful ingest per (city, domain). Drives the Scheduler cadence gate.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `city_id` | string | YES | City partition key |
| `domain` | string | YES | Domain name |
| `last_ingested_at` | string | YES | ISO-8601 timestamp of last ingest attempt |
| `rows_written` | integer | NO | Number of signal rows written in last run |
| `status` | string | YES | `ok` / `partial` / `error` |
| `error_msg` | string | NO | Error message for non-ok status |
| `conformance_ok` | boolean | NO | Whether the last conformance gate check passed |
| `conformance_failures` | string | NO | JSON array of conformance failure messages |

**Deduplication key:** `(city_id, domain)`  
**Conflict rule:** update all fields on conflict (latest run always wins).

---

### `city_patterns`

City-level pattern summaries produced by the City Pattern Agent after each sweep. Optional — a deployment without a City Pattern Agent need not implement this table.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `pattern_id` | string | YES | Unique identifier |
| `city_id` | string | YES | City partition key |
| `created_at` | string | YES | ISO-8601 timestamp |
| `lookback_hours` | integer | YES | Time window of insights that fed this summary |
| `n_insights` | integer | YES | Number of cell insights analysed |
| `theme_count` | integer | YES | Number of city-wide themes identified |
| `summary_json` | string | YES | Full structured JSON summary (executive summary + themed findings) |

---

## Insight vs Decision Packet [NORMATIVE]

An **insight** (`h3_insights`) and a **decision packet** (`h3_packets`) serve distinct roles and MUST NOT be conflated:

| | Insight | Decision Packet |
|---|---------|----------------|
| **Producer** | Any App (agent, statistical model, rule engine) | Apps only, typically after an insight reaches `high` priority |
| **Scope** | Cross-domain finding for a single cell | Actionable evidence bundle, often aggregating multiple insights |
| **Audience** | Agent review queue | Officer decision workflow |
| **Lifecycle** | Append-only; outcome tracked via `outcome_status` | Idempotent; `packet_id` deduplicates |
| **Required fields** | `finding`, `confidence`, `priority_tier`, `uncertainty_notes_json` | `summary`, `risk_level`, `domain` |

An App MAY produce a decision packet without a preceding insight (e.g. a threshold-breach packet). An App MUST NOT produce a decision packet that embeds raw signal rows — use `evidence_json` to reference signal identifiers, not copy signal data.

---

## Write Interface [NORMATIVE]

The Knowledge Store MUST expose a write interface that Drivers and Apps can call. The reference implementation exposes this as Python functions (`write_signals`, `write_assessment`, `write_insight`, `write_packet`). Alternative implementations may use REST, gRPC, or any IPC mechanism — the logical contract (not the transport) is what this specification normalises.

**Required write operations:**

| Operation | Caller | Target table |
|-----------|--------|-------------|
| `write_signals(rows, city_id, domain, source)` | Drivers | `h3_signals`, `h3_metadata` |
| `write_assessment(h3_id, city_id, domain, risk_level, …)` | Drivers | `h3_assessments` |
| `write_insight(h3_id, city_id, agent_type, finding, confidence, …)` | Apps | `h3_insights` |
| `write_packet(packet_id, h3_id, city_id, domain, …)` | Apps | `h3_packets` |
| `write_city_pattern(pattern_id, city_id, lookback_hours, n_insights, theme_count, summary_json)` | Apps | `city_patterns` |
| `record_ingest(city_id, domain, rows_written, status, …)` | Drivers (on success/partial); Scheduler (on Driver error) | `h3_ingest_log` |
| `close_insight(insight_id, outcome_status, closed_by)` | Apps (reviewer flow only — human-triggered) | `h3_insights` |

**Upsert semantics:** All write operations MUST be idempotent. Calling the same write with the same deduplication key twice MUST produce the same result as calling it once.

---

## Read Interface [NORMATIVE]

The Knowledge Store MUST expose a read interface that Apps can call. At minimum:

| Query | Returns |
|-------|---------|
| `get_h3_context(h3_id, city_id)` | All current signals and assessments for a cell |
| `get_signals_history(h3_id, city_id, domain, signal, days)` | Time series for a specific signal |
| `get_neighbors_summary(h3_id, city_id, k)` | Assessments for k-ring neighbours |
| `get_city_summary(city_id)` | City-wide risk distribution and top-risk cells |
| `get_domain_cross_correlation(city_id, domain_a, domain_b)` | Lift score for domain co-elevation |
| `get_store_stats(city_id)` | Row counts, last ingest timestamps, coverage metrics |

---

## Temporal Semantics [NORMATIVE]

All timestamps MUST be stored in UTC. The Knowledge Store MUST NOT store or interpret local time.

`hour_bucket` MUST be computed as: truncate the observation timestamp to the hour in UTC, format as `YYYY-MM-DDTHH:00:00Z`.

`day_bucket` MUST be computed as: truncate the assessment timestamp to the date in UTC, format as `YYYY-MM-DD`.

History is append-only at the hour level. Two observations of the same signal in the same hour are deduplicated to the later value. Observations from different hours accumulate indefinitely — the Knowledge Store MUST NOT expire or delete historical rows (implementations MAY archive them).
